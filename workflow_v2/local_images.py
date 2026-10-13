"""Optional, local-only image generation for reviewed teaching slides."""
import base64
import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from filelock import FileLock, Timeout
from PIL import Image

from .contracts import VISUAL_STYLE
from .model import gpu_slot, unload_model, endpoint as model_endpoint
from .runlog import log_event
from .store import ROOT, DATA, atomic
from .images import valid_image


def endpoint():
    config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
    url = config.get('image_generation_url', 'http://127.0.0.1:7860/sdapi/v1/txt2img')
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path != '/sdapi/v1/txt2img':
        raise ValueError('生圖服務只能使用本機 SD WebUI 相容端點')
    return url


def enabled():
    """Local image generation is optional and off unless config.yaml says image_generation_enabled: true."""
    try:
        config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return False
    return config.get('image_generation_enabled', False) is True


def explain_unavailable(reason):
    """One plain Chinese sentence for why the local image service cannot be used."""
    raw = str(reason or '')
    low = raw.lower()
    if '啟動失敗' in raw:
        return raw[:160]
    if '10061' in raw or 'refused' in low or 'max retries' in low or 'connection' in low or '拒絕連線' in raw:
        return '本機生圖服務（Forge）沒有開啟，連不上 7860 連接埠'
    if 'timed out' in low or 'timeout' in low:
        return '本機生圖服務回應逾時'
    return '本機生圖服務目前無法使用：' + raw[:80]


def probe(session=requests):
    try:
        url = endpoint().rsplit('/sdapi/v1/txt2img', 1)[0] + '/sdapi/v1/options'
        response = session.get(url, timeout=(5, 3))
        response.raise_for_status()
        return {'ready': True, 'checkpoint': response.json().get('sd_model_checkpoint', '')}
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {'ready': False, 'reason': str(exc)[:250]}


def _config():
    try:
        return yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _paths(config=None):
    config = _config() if config is None else config
    return Path(str(config.get('image_generation_python') or '')), Path(str(config.get('image_generation_launcher') or ''))


def install_problem(config=None):
    """Plain Chinese reason Forge cannot be started from here; '' when everything needed is in place."""
    config = _config() if config is None else config
    if not str(config.get('image_generation_python') or '').strip() or not str(config.get('image_generation_launcher') or '').strip():
        return '還沒有設定本機生圖程式（config.yaml 的 image_generation_python 與 image_generation_launcher）'
    python, launcher = _paths(config)
    if not python.is_file():
        return '找不到生圖程式的 Python：' + str(python)
    if not launcher.is_file() or launcher.name != 'launch.py':
        return '找不到 Forge 的 launch.py：' + str(launcher)
    models = launcher.parent / 'models' / 'Stable-diffusion'
    if not any(models.glob('*.safetensors')) and not any(models.glob('*.ckpt')):
        return 'Forge 還沒有放入繪圖模型檔：' + str(models)
    return ''


def _marker_running(python):
    marker = DATA / 'image-service.pid'
    if not marker.is_file():
        return False
    try:
        import psutil
        process = psutil.Process(int(marker.read_text().strip()))
        return process.is_running() and str(python).casefold() == process.exe().casefold()
    except (ValueError, OSError, ImportError):
        return False
    except Exception:  # psutil.Error
        return False


BOOT = Path(__file__).with_name('forge_boot.py')
START_TIMEOUT = 300      # seconds a start may take (cold torch import is ~1-5 min) before it counts as hung
MAX_FAILURES = 2         # automatic starts allowed to fail before we stop trying
FAILURE_WINDOW = 6 * 3600
HINT = ('本機生圖服務（Forge）連續啟動失敗，已暫停自動啟動以免一直跳出錯誤視窗；目前改用授權素材與圖解，簡報不受影響。'
        '請查看 logs\\forge-api.err.log；處理後刪除 data\\workflow-v2\\image-service-state.json 即可恢復自動啟動')


def _state_file():
    return DATA / 'image-service-state.json'


def _state():
    try:
        value = json.loads(_state_file().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(value):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        _state_file().write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


READY_LINE = 'Running on local URL'


def _out_log():
    return ROOT / 'logs' / 'forge-api.out.log'


def _note_start(pid):
    value = _state()
    try:
        offset = _out_log().stat().st_size
    except OSError:
        offset = 0
    value.update(pid=pid, started=time.time(), settled=False, log_offset=offset)
    _save_state(value)


def _reached_ready(value):
    """True when this start printed Forge's ready line after it was launched (it worked, then was closed)."""
    if 'log_offset' not in value:
        return False  # recorded by an older version: no reliable place to look from
    try:
        with _out_log().open('rb') as handle:
            handle.seek(int(value['log_offset'] or 0))
            return READY_LINE.encode() in handle.read(4 * 1024 * 1024)
    except (OSError, ValueError):
        return False


def _before_this_boot(value):
    """True when the recorded start happened before the computer last booted (a reboot ended it, not a crash)."""
    try:
        import psutil
        return float(value.get('started', 0)) < psutil.boot_time()
    except Exception:
        return False


def mark_stopped_by_us():
    """Our own shutdown ended Forge: that is not a failed start."""
    value = _state()
    if value.get('pid') and not value.get('settled'):
        value.update(settled=True, reason='')
        _save_state(value)


def _kill(pid):
    try:
        import psutil
        process = psutil.Process(pid)
        for child in process.children(recursive=True):
            child.kill()
        process.kill()
    except Exception:
        pass


def settle_previous_start(python=None, ready=None, session=requests):
    """Judge the last automatic start once: it answered (failures reset), died, or hung (killed). Returns the state."""
    value = _state()
    if not value.get('pid') or value.get('settled'):
        return value
    if ready is None:
        ready = probe(session)['ready']
    if ready:
        value.update(settled=True, fails=0, reason='')
        _save_state(value)
        return value
    running = False
    try:
        import psutil
        process = psutil.Process(int(value['pid']))
        running = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        if running and python:
            running = str(python).casefold() == process.exe().casefold()
    except Exception:
        running = False
    reason = ''
    if not running and (_reached_ready(value) or _before_this_boot(value)):
        # It answered and was later closed (shutdown, reboot, window closed): a good start, not a failure.
        value.update(settled=True, fails=0, reason='')
        _save_state(value)
        return value
    if not running:
        reason = 'Forge 啟動後沒有就緒就結束了（請查看 logs\\forge-api.err.log 最後幾行）'
    elif time.time() - float(value.get('started', 0)) > START_TIMEOUT:
        _kill(int(value['pid']))
        reason = 'Forge 超過 %d 分鐘仍沒有開啟 7860 連接埠（可能卡在錯誤視窗），已結束該程序' % (START_TIMEOUT // 60)
    if reason:
        value.update(settled=True, fails=int(value.get('fails', 0)) + 1, last_fail=time.time(), reason=reason)
        _save_state(value)
        log_event('image_service_start_failed', None, message='啟動失敗：' + reason, fails=value['fails'])
    return value


def blocked_reason():
    """Chinese hint when automatic starts are paused after repeated failures, else ''."""
    value = _state()
    if int(value.get('fails', 0)) >= MAX_FAILURES and time.time() - float(value.get('last_fail', 0)) < FAILURE_WINDOW:
        return HINT + ('（最後原因：' + value['reason'] + '）' if value.get('reason') else '')
    return ''


def _spawn(python, launcher, port):
    DATA.mkdir(parents=True, exist_ok=True)
    forge_data = DATA / 'forge-data'
    forge_data.mkdir(parents=True, exist_ok=True)
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(SKIP_VENV='1', PYTHONUTF8='1')
    from .runlog import rotate
    for name in ('forge-api.out.log', 'forge-api.err.log'):
        rotate(logs / name)
    with (logs / 'forge-api.out.log').open('a', encoding='utf-8') as stdout, \
            (logs / 'forge-api.err.log').open('a', encoding='utf-8') as stderr:
        process = subprocess.Popen([str(python), '-u', str(BOOT), str(launcher), '--api', '--port', str(port),
                                    '--data-dir', str(forge_data), '--models-dir', str(launcher.parent / 'models'),
                                    '--disable-xformers', '--skip-torch-cuda-test', '--skip-prepare-environment'],
                                   cwd=launcher.parent, env=env, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (DATA / 'image-service.pid').write_text(str(process.pid), encoding='utf-8')
    _note_start(process.pid)
    log_event('image_service_started', None, pid=process.pid, message='已啟動本機生圖服務（Forge），約 1～2 分鐘後可用')
    return process


def describe(reachable, config=None):
    """(state, plain Chinese sentence) for the health panel. state: off / missing / ready / starting / stopped."""
    config = _config() if config is None else config
    if config.get('image_generation_enabled', False) is not True:
        return 'off', '未啟用：圖片改用授權素材搜尋與可編輯圖解，不影響簡報'
    problem = install_problem(config)
    if problem:
        return 'missing', problem + '；目前改用授權素材與圖解'
    if reachable:
        settle_previous_start(ready=True)  # record the good start the moment the console sees it answer
        return 'ready', '已就緒，可以用本機 AI 製作教學插圖'
    settle_previous_start(_paths(config)[0], ready=False)  # a start that died or hung is noticed here too
    paused = blocked_reason()
    if paused:
        return 'failed', paused
    if _marker_running(_paths(config)[0]):
        return 'starting', '正在啟動，約需 1～2 分鐘；這段時間完成的教材先用授權素材與圖解'
    return 'stopped', '還沒開啟：下次開啟教材AI會自動啟動；現在先用授權素材與圖解'


def start_in_background(session=requests):
    """Start Forge without waiting (used by 開啟教材AI.cmd and for auto-recovery). Never raises.
    Returns {'state': off|missing|ready|starting|failed, 'message': plain Chinese}."""
    try:
        config = _config()
        if config.get('image_generation_enabled', False) is not True:
            return {'state': 'off', 'message': describe(False, config)[1]}
        problem = install_problem(config)
        if problem:
            log_event('image_service_missing', None, message=problem)
            return {'state': 'missing', 'message': problem}
        if probe(session)['ready']:
            settle_previous_start(ready=True)
            return {'state': 'ready', 'message': '本機生圖服務已經在執行'}
        python, launcher = _paths(config)
        port = urlparse(endpoint()).port or 7860
        DATA.mkdir(parents=True, exist_ok=True)
        settle_previous_start(python, ready=False)
        paused = blocked_reason()
        if paused:
            return {'state': 'failed', 'message': paused}
        with FileLock(str(DATA / 'image-service-start.lock'), timeout=10):
            if probe(session)['ready']:
                return {'state': 'ready', 'message': '本機生圖服務已經在執行'}
            if _marker_running(python):
                return {'state': 'starting', 'message': '本機生圖服務正在啟動中，約需 1～2 分鐘'}
            _spawn(python, launcher, port)
        return {'state': 'starting', 'message': '已在背景啟動本機生圖服務，約 1～2 分鐘後可用；這段時間先用授權素材'}
    except (OSError, ValueError, Timeout) as exc:
        message = '本機生圖服務啟動失敗：' + str(exc)[:120] + '；改用授權素材與圖解'
        try:
            log_event('image_service_start_failed', None, message=message)
        except Exception:
            pass
        return {'state': 'failed', 'message': message}


def wait_ready(session=requests, seconds=60):
    """Wait for a Forge that is already starting; returns the last probe."""
    deadline = time.monotonic() + seconds
    current = probe(session)
    while not current['ready'] and time.monotonic() < deadline:
        time.sleep(2)
        current = probe(session)
    return current


def ensure_service(session=requests, wait_seconds=90):
    """Start the configured local Forge and wait until it answers (blocking variant)."""
    current = probe(session)
    if current['ready'] or session is not requests:
        return current
    config = _config()
    if install_problem(config):
        return current
    python, launcher = _paths(config)
    port = urlparse(endpoint()).port or 7860
    DATA.mkdir(parents=True, exist_ok=True)
    settle_previous_start(python, ready=False)
    paused = blocked_reason()
    if paused:
        return {'ready': False, 'reason': '本機生圖服務啟動失敗（已暫停自動啟動）：' + paused}
    with FileLock(str(DATA / 'image-service-start.lock'), timeout=65):
        current = probe(session)
        if current['ready']:
            return current
        launched = None if _marker_running(python) else _spawn(python, launcher, port)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current = probe(session)
            if current['ready']:
                return current
            if launched is not None and launched.poll() is not None:
                settle_previous_start(python, ready=False)
                return {'ready': False, 'reason': '本機 Forge 啟動失敗；請查看 logs/forge-api.err.log'}
            time.sleep(2)
    return current


def _image_bytes(value):
    encoded = value.split(',', 1)[-1] if value.startswith('data:') else value
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 16_000_000:
        raise ValueError('本機生圖回覆超過 16 MB')
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('PNG', 'JPEG') or min(image.size) < 256 or max(image.size) > 4096:
            raise ValueError('本機生圖回覆的圖片格式或尺寸無效')
        suffix = '.png' if image.format == 'PNG' else '.jpg'
    return raw, suffix


def generate_assets(deck, out, existing=None, models=(), session=requests, max_images=None,start_service=True):
    """Generate only approved illustrative scenes, one GPU task at a time."""
    out = Path(out)
    media = dict(existing or {})
    tasks = [(number, slide) for number, slide in enumerate(deck['slides'], 1)
             if slide.get('visual_asset', {}).get('is_required') and
             slide['layout_id'] in ('Cover', 'Text_Visual') and number not in media]
    manifest = out / 'visual-assets.json'
    records = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    reusable=[]
    for number, slide in tasks:
        prior=records.get(str(number),{})
        expected=slide['visual_asset']['image_prompt']+', '+VISUAL_STYLE
        image=Path(prior.get('path',''))
        if prior.get('prompt')==expected and valid_image(image):
            media[number]=str(image)
        else:reusable.append((number,slide))
    tasks=reusable
    if not tasks:
        atomic(manifest, records)
        return media
    try:
        if start_service:
            status = ensure_service(session)
        else:
            status = probe(session)
            if not status['ready'] and session is requests:
                if describe(False)[0] == 'starting':
                    status = wait_ready(session, 60)
                elif not install_problem():
                    started = start_in_background(session)
                    log_event('image_service_recovering', out.name, stage='render', message=started['message'])
                    if started['state'] == 'failed':
                        status = {'ready': False, 'reason': '本機生圖服務啟動失敗：' + started['message']}
    except (OSError,ValueError,TimeoutError,Timeout) as exc:
        status={'ready':False,'reason':'本機生圖服務啟動失敗：'+str(exc)[:180]}
    if not status['ready']:
        friendly = explain_unavailable(status['reason'])
        for number, slide in tasks:
            records[str(number)] = {'status': 'unavailable', 'reason': friendly, 'detail': str(status['reason'])[:200],
                                    'teaching_purpose': slide['visual_asset']['reasoning']}
        atomic(manifest, records)
        log_event('image_generation_unavailable', out.name, stage='render', reason=friendly, detail=str(status['reason'])[:200])
        return media
    sources_path = out / 'image-sources.json'
    sources = json.loads(sources_path.read_text(encoding='utf-8')) if sources_path.exists() else {}
    count = 0
    unloaded = False
    priorities = dict.fromkeys(model for model in models if model)
    if session is requests:
        config=yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8')) or {}
        if config.get('image_priority_unload_resident_models'):
            try:
                response=requests.get(model_endpoint()+'/api/ps',timeout=5)
                response.raise_for_status()
                priorities.update(dict.fromkeys(item['name'] for item in response.json().get('models',[])
                                                if item.get('name')))
            except (requests.RequestException,ValueError,KeyError) as exc:
                log_event('image_priority_probe_failed',out.name,stage='render',reason=str(exc)[:300])
    for number, slide in tasks:
        visual = slide['visual_asset']
        if max_images is not None and count >= max_images:
            records[str(number)] = {'status': 'skipped', 'reason': '每份簡報的生圖上限已達',
                                    'teaching_purpose': visual['reasoning']}
            continue
        full_prompt = visual['image_prompt'] + ', ' + VISUAL_STYLE
        key = hashlib.sha256((full_prompt + '\n' + status['checkpoint']).encode('utf-8')).hexdigest()
        folder = out / 'generated-images'
        cached = next((p for ext in ('.png', '.jpg') if valid_image(p := folder / (key + ext))), None)
        started = time.monotonic()
        try:
            if cached is None:
                if not unloaded:
                    for model in priorities:
                        try:unload_model(model)
                        except (requests.RequestException,ValueError) as exc:
                            log_event('image_priority_unload_failed',out.name,stage='render',
                                      model=model,reason=str(exc)[:300])
                    unloaded = True
                with gpu_slot():
                    response = session.post(endpoint(), json={
                        'prompt': full_prompt,
                        'negative_prompt': 'text, letters, numbers, watermark, logo, photorealistic, scary',
                        'steps': 20, 'width': 1024, 'height': 1024,
                        'batch_size': 1, 'n_iter': 1,
                    }, timeout=(5, 60))
                    response.raise_for_status()
                    raw, suffix = _image_bytes(response.json()['images'][0])
                folder.mkdir(parents=True, exist_ok=True)
                cached = folder / (key + suffix)
                temp = folder / (key + '.partial')
                temp.write_bytes(raw)
                temp.replace(cached)
                result = 'generated'
            else:
                result = 'cached'
            media[number] = str(cached)
            sources[str(number)] = {'title': '本機 AI 生成插圖', 'generated': True,
                                    'description_url': '', 'license': '本機生成', 'license_url': '',
                                    'model': status['checkpoint'], 'local_path': str(cached),
                                    'teaching_purpose': visual['reasoning']}
            records[str(number)] = {'status': result, 'path': str(cached),
                                    'model': status['checkpoint'], 'prompt': full_prompt,
                                    'teaching_purpose': visual['reasoning'],
                                    'seconds': round(time.monotonic() - started, 2)}
            count += 1
            log_event('image_generation_finished', out.name, stage='render', page=number,
                      result=result, seconds=records[str(number)]['seconds'])
        except (requests.RequestException, OSError, ValueError, KeyError, IndexError) as exc:
            records[str(number)] = {'status': 'failed', 'reason': str(exc)[:500],
                                    'teaching_purpose': visual['reasoning']}
            log_event('image_generation_failed', out.name, stage='render', page=number,
                      reason=str(exc)[:500])
    atomic(manifest, records)
    atomic(sources_path, sources)
    return media
