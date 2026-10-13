"""Windows-native Strata adapter. The engine owns one resident, serial sequence."""
import json, os, subprocess, time
from pathlib import Path
from urllib.parse import urlparse

import psutil, requests, yaml
from filelock import FileLock
from .store import ROOT
from .runlog import log_event

MODEL = 'strata:qwen3.8-flash-next-iq3_s'
CONTEXT_LIMIT = 131072
PID_FILE = ROOT / 'logs/strata.pid'
INSTALL_PID_FILE = ROOT / 'logs/strata-installer.pid'


def settings():
    return yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}


def is_strata(model):
    return isinstance(model, str) and model.startswith('strata:')


def endpoint():
    url = settings().get('strata_url', 'http://127.0.0.1:8088').rstrip('/')
    parsed = urlparse(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
        raise ValueError('Strata 僅允許本機 HTTP 服務端點')
    return url


def config_path():
    return ROOT / settings().get('strata_config', 'runtime/strata/strata-iq3_s.json')


def python_path():
    return ROOT / 'runtime/strata/.venv/Scripts/python.exe'


def installed():
    return config_path().is_file() and python_path().is_file()


def installer_process():
    try:
        process = psutil.Process(int(INSTALL_PID_FILE.read_text(encoding='utf-8')))
        if (Path(process.cwd()).resolve() == ROOT.resolve()
                and any(Path(arg).name == 'install_strata.py' for arg in process.cmdline())):
            return process
    except (OSError, ValueError, psutil.Error):
        pass
    return None


def start_installation():
    if installer_process() is not None:
        return
    (ROOT / 'logs').mkdir(exist_ok=True)
    import sys
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    with (ROOT / 'logs/strata-install.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(ROOT / 'install_strata.py')],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    INSTALL_PID_FILE.write_text(str(process.pid), encoding='utf-8')


def install_status():
    path = ROOT / 'logs/strata-install.log'
    tail = ''
    if path.is_file():
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 6000))
            tail = stream.read().decode('utf-8', errors='replace')
    return {'installed': installed(), 'running': installer_process() is not None,
            'log': tail}


def context_limit():
    if config_path().is_file():
        args = json.loads(config_path().read_text(encoding='utf-8')).get('args', [])
        if '--max-context' in args:
            value = int(args[args.index('--max-context') + 1])
            if not 0 < value <= CONTEXT_LIMIT:
                raise ValueError('本系統 Strata 上下文上限為 128K，不啟用 1M；請重新設定引擎配置')
            return value
    return CONTEXT_LIMIT


def probe():
    response = requests.get(endpoint() + '/health', timeout=(1, 2))
    response.raise_for_status()
    data = response.json()
    if data.get('status') not in ('ok', 'ready'):
        raise RuntimeError('Strata 模型尚未就緒：' + str(data.get('status')))
    expected = MODEL.removeprefix('strata:')
    if config_path().is_file():
        expected = json.loads(config_path().read_text(encoding='utf-8')).get('model_name', expected)
    if data.get('model') != expected:
        raise RuntimeError('Strata 端點上的模型與安裝配置不一致')
    return {'model': MODEL, 'context': context_limit(), 'detail': data}


def owned_process():
    """A PID file alone never authorizes stopping a reused or foreign PID."""
    try:
        process = psutil.Process(int(PID_FILE.read_text(encoding='utf-8')))
        command = process.cmdline()
        if (Path(process.cwd()).resolve() == (ROOT / 'runtime/strata').resolve()
                and any(command[i:i + 2] == ['-m', 'serve.server'] for i in range(len(command) - 1))
                and '--config' in command
                and Path(command[command.index('--config') + 1]).resolve() == config_path().resolve()):
            return process
    except (OSError, ValueError, IndexError, psutil.Error):
        pass
    return None


def start_server():
    """Start without blocking the control UI while weights are loading."""
    (ROOT / 'logs').mkdir(exist_ok=True)
    with FileLock(str(ROOT / 'logs/strata-start.lock'), timeout=60):
        _start_server()


def _start_server():
    if not installed():
        raise RuntimeError('Strata 尚未安裝完成，請查看 logs/strata-install.log')
    context_limit()  # Refuse a stale 1M engine config before allocating memory.
    try:
        probe()
        return
    except requests.RequestException:
        pass
    if owned_process() is not None:
        return
    port = urlparse(endpoint()).port or 80
    if any(c.status == 'LISTEN' and c.laddr.port == port for c in psutil.net_connections(kind='tcp')):
        raise RuntimeError(f'Strata 埠 {port} 已被其他服務使用，沒有重複啟動')
    # Free the other backend's resident weights, never terminate unrelated programs.
    from .model import endpoint as ollama_endpoint, release_image_checkpoint
    release_image_checkpoint()
    try:
        response = requests.get(ollama_endpoint() + '/api/ps', timeout=3)
        response.raise_for_status()
        for item in response.json().get('models', []):
            response = requests.post(ollama_endpoint() + '/api/generate', json={
                'model': item['name'], 'prompt': '', 'stream': False, 'keep_alive': 0}, timeout=30)
            response.raise_for_status()
    except requests.ConnectionError:
        pass
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    (ROOT / 'logs').mkdir(exist_ok=True)
    with (ROOT / 'logs/strata.out.log').open('a', encoding='utf-8') as out, \
            (ROOT / 'logs/strata.err.log').open('a', encoding='utf-8') as err:
        process = subprocess.Popen([str(python_path()), '-m', 'serve.server', '--engine', 'strata',
            '--config', str(config_path()), '--host', '127.0.0.1', '--port', str(port)],
            cwd=ROOT / 'runtime/strata', env=env, stdout=out, stderr=err,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    PID_FILE.write_text(str(process.pid), encoding='utf-8')
    log_event('engine_started', provider='strata', pid=process.pid, context_limit=context_limit())


def stop_server():
    process = owned_process()
    if process is not None:
        from .worker import stop_tree
        stop_tree(process)
        if owned_process() is not None:
            raise RuntimeError('Strata 尚未停止，不能載入另一個模型')
        PID_FILE.unlink(missing_ok=True)
        log_event('engine_stopped', provider='strata', pid=process.pid)


def ensure_ready(timeout=600):
    start_server()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            probe()
            return
        except requests.RequestException:
            if owned_process() is None:
                raise RuntimeError('Strata 啟動失敗，請查看 logs/strata.err.log')
            time.sleep(1)
    raise RuntimeError('Strata 載入模型超時，請查看 logs/strata.err.log')


def normalize_reply(data, elapsed):
    """Keep existing token counters and duration reports backend independent."""
    choice = data['choices'][0]
    content = (choice['message'].get('content') or '').strip()
    if content.startswith('```') and '\n' in content and content.rstrip().endswith('```'):
        content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    usage = data.get('usage', {})
    timings = data.get('timings', {})
    return {'provider': 'strata', 'model': data.get('model'), 'message': {'content': content},
        'done': True, 'done_reason': choice.get('finish_reason', ''),
        'prompt_eval_count': usage.get('prompt_tokens', 0), 'eval_count': usage.get('completion_tokens', 0),
        'cached_tokens': usage.get('prompt_tokens_details', {}).get('cached_tokens', 0),
        'total_duration': round(elapsed * 1e9),
        'prompt_eval_duration': round(timings.get('prompt_ms', 0) * 1e6),
        'eval_duration': round(timings.get('predicted_ms', 0) * 1e6)}


def request(model, messages, schema, output_limit):
    """Collect local SSE internally so a killed stage closes the socket and stops inference.

    v0.1.30 ignores response_format: schema validation stays in model.call.
    No intermediate tokens are exposed in the user interface.
    """
    instructions = '\n輸出必須符合此 JSON Schema；不要使用 Markdown 程式碼框：\n' + json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
    messages = [dict(m) for m in messages]
    messages[0]['content'] += instructions
    response = requests.post(endpoint() + '/v1/chat/completions', json={
        'model': model.removeprefix('strata:'), 'messages': messages, 'stream': True,
        'max_tokens': output_limit, 'temperature': .18, 'repetition_penalty': 1.1,
        'chat_template_kwargs': {'enable_thinking': False}, 'strata_mcp': False},
        stream=True, timeout=(10, 480))
    if not response.ok:
        return response, None
    started = time.monotonic()
    parts = []
    final = None
    try:
        for line in response.iter_lines():
            if not line.startswith(b'data: '):
                continue
            raw = line[6:]
            if raw == b'[DONE]':
                break
            chunk = json.loads(raw)
            if 'error' in chunk:
                raise RuntimeError('Strata 推論失敗：' + str(chunk['error']))
            choice = chunk['choices'][0]
            parts.append(choice.get('delta', {}).get('content') or '')
            if choice.get('finish_reason') is not None:
                final = chunk
        if final is None:
            raise ValueError('Strata 回覆未完成，不採用截斷內容')
        data = dict(final, choices=[{'message': {'content': ''.join(parts)},
            'finish_reason': final['choices'][0]['finish_reason']}])
        return response, normalize_reply(data, time.monotonic() - started)
    finally:
        response.close()
