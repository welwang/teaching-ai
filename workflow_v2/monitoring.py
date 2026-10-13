"""Read-only live metrics for the local generation queue."""
import json
import re
import statistics
import subprocess
import time
from functools import lru_cache
from collections import Counter
import psutil

from .store import STAGES
from .store import DATA
from .monitor_report import job_report, explain_error

STAGE_NAMES = {
    'source': '讀取主教材', 'plan': '規劃大綱', 'write': '逐頁編寫',
    'review': '本地模型審核', 'render': '製作簡報',
    'preview': '製作預覽', 'publish': '最後內容優化與整理成果',
}
ACTIVE = {'running', 'rendering', 'reviewing', 'pausing', 'removing'}


def duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours} 小時 {minutes} 分 {seconds} 秒' if hours else f'{minutes} 分 {seconds} 秒'


def _gpu_query():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'nvidia-smi 失敗')
        fields = [int(value.strip()) for value in result.stdout.splitlines()[0].split(',')]
        if len(fields) != 3:
            raise ValueError('GPU 回覆格式錯誤')
        return {'utilization': fields[0], 'memory_used_mb': fields[1], 'memory_total_mb': fields[2]}
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError, RuntimeError) as exc:
        return {'error': str(exc)}


_GPU_CACHE = {'at': 0.0, 'value': None}
GPU_TTL = 3.0


def gpu():
    """nvidia-smi 每次最多等 4 秒；3 秒內重複讀取（例如多個畫面同時更新）直接用快取。"""
    now = time.monotonic()
    if _GPU_CACHE['value'] is not None and now - _GPU_CACHE['at'] < GPU_TTL:
        return dict(_GPU_CACHE['value'])
    value = _gpu_query()
    _GPU_CACHE.update(at=time.monotonic(), value=value)
    return dict(value)


_USAGE_KEYS = ('prompt_eval_count', 'eval_count', 'total_duration', 'load_duration',
               'prompt_eval_duration', 'eval_duration', 'done_reason')


@lru_cache(maxsize=4096)
def _usage_record(path,mtime_ns,size):
    """Cache only immutable inference replies, never the live job status.

    Keep only the numeric fields: caching whole replies kept thousands of
    generated slide texts in memory for the life of the web process."""
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        return value
    return {key: value.get(key) for key in _USAGE_KEYS}

def usage(folder, since=None, seen=None):
    prompt = output = 0
    durations = []
    calls = 0
    load_seconds=prompt_seconds=generation_seconds=0.0
    truncated_calls=0
    seen=seen if seen is not None else set()
    for path in folder.rglob('*-attempt-*.json'):
        try:
            stat=path.stat()
            if since is not None and stat.st_mtime < since:continue
            value = _usage_record(path,stat.st_mtime_ns,stat.st_size)
            if not isinstance(value, dict):
                continue
            # A revision may contain a legacy copy of its parent's replies.
            # Modern reply filenames identify an actual request + attempt.
            if re.search(r'-attempt-\d+-[0-9a-f]{12}\.json$',path.name):
                if path.name in seen:continue
                seen.add(path.name)
            prompt += max(0, int(value.get('prompt_eval_count') or 0))
            output += max(0, int(value.get('eval_count') or 0))
            elapsed = float(value.get('total_duration') or 0) / 1_000_000_000
            load_seconds+=float(value.get('load_duration') or 0)/1_000_000_000
            prompt_seconds+=float(value.get('prompt_eval_duration') or 0)/1_000_000_000
            generation_seconds+=float(value.get('eval_duration') or 0)/1_000_000_000
            truncated_calls+=value.get('done_reason')=='length'
            if elapsed > 0:
                durations.append(elapsed)
            calls += 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return {'prompt_tokens': prompt, 'output_tokens': output,
            'total_tokens': prompt + output, 'calls': calls, 'call_seconds': durations,
            'load_seconds':load_seconds,'prompt_seconds':prompt_seconds,
            'generation_seconds':generation_seconds,'truncated_calls':truncated_calls}

def session_started():
    marker=DATA/'session-start.json'
    try:return float(json.loads(marker.read_text(encoding='utf-8'))['started'])
    except (OSError,ValueError,KeyError,TypeError):
        return 0.0

def session_usage(store, since=None):
    since=session_started() if since is None else since
    total={'prompt_tokens':0,'output_tokens':0,'total_tokens':0,'calls':0,'call_seconds':[],
           'load_seconds':0.0,'prompt_seconds':0.0,'generation_seconds':0.0,'truncated_calls':0}
    folders=[store.folder(row['id']) for row in store.list()]
    # Removed or restarted work still consumed tokens during this session.
    # Moving a job to trash/history must not reduce the startup total.
    for name in ('trash','history'):
        parent=store.root/name
        if parent.is_dir():folders.extend(path for path in parent.iterdir()
                                         if path.is_dir() and not path.is_symlink())
    seen=set()
    for folder in folders:
        value=usage(folder,since,seen=seen)
        for key in ('prompt_tokens','output_tokens','total_tokens','calls','load_seconds',
                    'prompt_seconds','generation_seconds','truncated_calls'):
            total[key]+=value[key]
        total['call_seconds'].extend(value['call_seconds'])
    return total


_SESSION_CACHE = {}
SESSION_TTL = 10.0
_EMPTY_SESSION = {'prompt_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'calls': 0, 'call_seconds': [],
                  'load_seconds': 0.0, 'prompt_seconds': 0.0, 'generation_seconds': 0.0, 'truncated_calls': 0}


def _session_usage_cached(store, fresh=False):
    """全部歷史工作的用量掃描很重，頁面每 5 秒更新時只需每 10 秒重算一次。"""
    key = str(store.root)
    hit = _SESSION_CACHE.get(key)
    if not fresh and hit and time.monotonic() - hit[0] < SESSION_TTL:
        return hit[1]
    try:
        value = session_usage(store)
    except Exception:
        value = hit[1] if hit else dict(_EMPTY_SESSION, call_seconds=[])
    _SESSION_CACHE[key] = (time.monotonic(), value)
    return value


_REQUEST_DEFAULTS = {'unit': '未命名教材', 'grade': 6, 'semester': '—', 'subject': '—',
                     'model': '未知', 'slide_count': 12}


def _request(row):
    """工作內容損毀或缺欄位時仍能顯示監控，而不是整頁出錯。"""
    try:
        value = json.loads(row['request'])
    except (ValueError, TypeError, KeyError):
        value = {}
    request = dict(_REQUEST_DEFAULTS)
    if isinstance(value, dict):
        request.update({key: item for key, item in value.items() if item is not None})
    if not isinstance(request['grade'], int):
        request['grade'] = 6
    if not isinstance(request['slide_count'], int) or request['slide_count'] < 1:
        request['slide_count'] = 12
    return request


def _safe_report(folder, now):
    try:
        return job_report(folder, now)
    except Exception:
        return None


def _events(store, job_id):
    with store.db() as connection:
        return [dict(row) for row in connection.execute(
            'SELECT stage,message,created FROM events WHERE job=? ORDER BY created,id', (job_id,))]


def _run_seconds(events, now, active):
    total = 0.0
    started = None
    for event in events:
        if event['message'] == '開始執行':
            started = event['created']
        elif started is not None:
            total += max(0, event['created'] - started)
            started = None
    if active and started is not None:
        total += max(0, now - started)
    return total


def production_seconds(store, row, now=None):
    """Recorded stage execution time, excluding queue and outline approval waits.

    Use the same clock as live monitoring; missing historical records stay unknown.
    """
    events = _events(store, row['id'])
    if not any(event['message'] == '開始執行' for event in events):
        return 0.0 if row['status'] in ('pending', 'staging') else None
    return _run_seconds(events, time.time() if now is None else now, row['status'] in ACTIVE)


def _summary_total(source):
    chunks = source.get('chunks', [])
    if len(json.dumps(chunks, ensure_ascii=False)) < 8000:
        return 0
    batches = 0
    size = 0
    for chunk in chunks:
        length = len(chunk.get('text', ''))
        if size and size + length > 6000:
            batches += 1
            size = 0
        size += length
    return batches + bool(size)


def _json_file(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _page_total(folder, request):
    plan = _json_file(folder / 'plan.json')
    return len(plan['slides']) if isinstance(plan.get('slides'), list) else request['slide_count']


def _stage_progress(folder, row, request):
    """Return a stage-local checkpoint, never a misleading whole-job percentage."""
    stage = STAGES[min(row['stage'], len(STAGES) - 1)]
    planned = max(1, _page_total(folder, request))
    if stage == 'source':
        return {'label': '讀取並整理主教材', 'completed': None, 'total': None, 'unit': None, 'remaining_calls': 1}
    if stage == 'plan':
        source = _json_file(folder / 'source.json')
        total = _summary_total(source) if isinstance(source.get('chunks'), list) else 0
        completed = len([path for path in (folder / 'source-summary').glob('batch-*.json')
                         if '-attempt-' not in path.name])
        if total and completed < total:
            return {'label': '整理主教材片段', 'completed': min(completed, total), 'total': total,
                    'unit': '片段', 'remaining_calls': total - completed + 1}
        if not (folder / 'analysis.json').exists():
            return {'label': '教材解析並規劃投影片大綱', 'completed': None, 'total': None,
                    'unit': None, 'remaining_calls': 2}
        return {'label': '規劃投影片大綱', 'completed': None, 'total': None,
                'unit': None, 'remaining_calls': 1}
    if stage == 'write':
        completed = len(list((folder / 'slides').glob('[0-9][0-9][0-9].json')))
        return {'label': f'編寫第 {min(completed + 1, planned)} 頁',
                'completed': min(completed, planned), 'total': planned, 'unit': '頁',
                'remaining_calls': max(0, planned - completed)}
    if stage == 'review':
        checkpoint = _json_file(folder / 'review-progress.json')
        try: completed = max(0, min(planned, int(checkpoint.get('completed_pages') or 0)))
        except (TypeError, ValueError): completed = 0
        if not checkpoint:
            # Jobs started before review-progress checkpoints existed still
            # expose the current page in activity.json. Review is sequential.
            activity = _json_file(folder / 'activity.json')
            if (activity.get('stage') in ('review', 'write') and activity.get('status') in ('waiting_gpu', 'inference')
                    and float(activity.get('updated') or 0) >= row['updated'] - 1):
                match = re.search(r'第\s*(\d+)\s*頁', str(activity.get('label', '')))
                if match:
                    completed = max(0, min(planned, int(match.group(1)) - 1))
        return {'label': f'審核第 {min(completed + 1, planned)} 頁', 'completed': completed,
                'total': planned, 'unit': '頁', 'remaining_calls': max(0, planned - completed)}
    if stage == 'render':
        deck = _json_file(folder / 'reviewed-deck.json')
        slides = deck.get('slides', [])
        expected = sum(bool(slide.get('visual_asset', {}).get('is_required'))
                       for slide in slides if isinstance(slide, dict))
        records = _json_file(folder / 'visual-assets.json')
        completed = sum(isinstance(record, dict) and record.get('status') in
                        ('generated', 'cached', 'diagram_fallback', 'unavailable', 'failed', 'skipped')
                        for record in records.values())
        if expected:
            return {'label': '搜尋插圖與排版', 'completed': min(completed, expected),
                    'total': expected, 'unit': '張插圖', 'remaining_calls': 0}
        return {'label': '編排可編輯簡報', 'completed': None, 'total': None,
                'unit': None, 'remaining_calls': 0}
    if stage == 'preview':
        rendered = _json_file(folder / 'rendered-deck.json')
        # Staged question pages make the rendered deck longer than the plan;
        # the PDF/preview target is always the rendered page count.
        total = len(rendered['slides']) if isinstance(rendered.get('slides'), list) else planned
        pages = len(list((folder / 'previews').glob('*.png')))
        return {'label': '製作 PDF 與逐頁預覽', 'completed': min(pages, total),
                'total': total, 'unit': '頁', 'remaining_calls': 0}
    if stage=='publish':
        checkpoint=_json_file(folder/'final-optimization-progress.json')
        total=int(checkpoint.get('total_pages') or planned)
        completed=min(total,int(checkpoint.get('completed_pages') or 0))
        done=_json_file(folder/'final-optimization.json')
        return {'label':'確認最後優化並整理下載檔案' if done else f'依不改排版準則優化第 {min(completed+1,total)} 頁',
            'completed':completed,'total':total,'unit':'頁','remaining_calls':max(0,(total-completed+3)//4)}
    return {'label': '整理下載檔案', 'completed': None, 'total': None,
            'unit': None, 'remaining_calls': 0}


def _stage_call_seconds(folder, stage):
    if stage == 'write':
        paths = (folder / 'calls').glob('page-*-attempt-*.json')
    elif stage == 'review':
        paths = (folder / 'calls').glob('review-*-attempt-*.json')
    elif stage=='publish':
        paths=(folder/'calls').glob('final-optimize-*-attempt-*.json')
    else:
        return []
    seconds = []
    for path in paths:
        value = _json_file(path)
        try: elapsed = float(value.get('total_duration') or 0) / 1_000_000_000
        except (TypeError, ValueError): continue
        if path.name.startswith('review-batch-'):
            try:elapsed/=max(1,len(json.loads(value['message']['content'])['results']))
            except (ValueError,KeyError,TypeError):continue
        if elapsed > 0:
            seconds.append(elapsed)
    return seconds


def _worker_alive(root):
    try:
        pid = int((root / 'worker.pid').read_text(encoding='utf-8').strip())
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE and any(
            'workflow_v2.worker' in part for part in process.cmdline())
    except (OSError, ValueError, psutil.Error):
        return False


def snapshot(store, now=None):
    fresh = now is not None
    now = time.time() if now is None else now
    rows = store.list()
    counts = Counter(row['status'] for row in rows)
    active = next((row for row in rows if row['status'] in ACTIVE), None)
    recent = None
    if rows:
        row = rows[0]
        try: request = json.loads(row['request'])
        except (ValueError, TypeError): request = {}
        recent = {'unit': request.get('unit', '未命名教材'), 'status': row['status'],
                  'stage': STAGE_NAMES[STAGES[min(row['stage'], len(STAGES) - 1)]],
                  'error': str(row.get('error') or '')[:300]}
    result = {'counts': dict(counts), 'job': None, 'recent': recent, 'gpu': gpu(),
              'worker_alive': _worker_alive(store.root), 'queue_paused': (store.root / 'pause').exists(),
              'session_tokens': _session_usage_cached(store, fresh)}
    if active is None:
        result['status'] = overall_status(result)
        return result
    request = _request(active)
    folder = store.folder(active['id'])
    stage = STAGES[min(active['stage'], len(STAGES) - 1)]
    stage_progress = _stage_progress(folder, active, request)
    progress = stage_progress['label']
    model = request.get('page_model',request['model']) if stage=='write' else request['model']
    activity_state = None
    activity_age = None
    activity = folder / 'activity.json'
    if activity.exists():
        try:
            value = json.loads(activity.read_text(encoding='utf-8'))
            if ((value.get('stage') == stage or stage == 'review' and value.get('stage') == 'write')
                    and value.get('status') in ('waiting_gpu', 'inference', 'loading_model')
                    and float(value.get('updated') or 0) >= active['updated'] - 1):
                progress = value.get('label') or progress
                if stage == 'review' and value.get('stage') == 'write':
                    progress = progress.replace('編寫', '修復', 1)
                model = value.get('model') or model
                activity_state = value['status']
                activity_age = max(0, now - float(value['updated']))
                if value['status'] == 'waiting_gpu':
                    progress += '（等待 GPU）'
        except (OSError, ValueError, TypeError, KeyError):
            pass
    tokens = usage(folder)
    elapsed = _run_seconds(_events(store, active['id']), now, True)
    # Only estimate the current model stage. Later stages and image generation
    # have different costs; a whole-job ETA here would be misleading.
    stage_calls = _stage_call_seconds(folder, stage)
    median_call = statistics.median(stage_calls) if stage_calls else None
    if median_call is None:
        eta = None
    else:
        eta = max(0, round(stage_progress['remaining_calls'] * median_call * 1.25))
    result['job'] = {
        'id': active['id'], 'unit': request['unit'], 'grade': request['grade'],
        'semester': request['semester'], 'subject': request['subject'],
        'stage': stage, 'stage_name': STAGE_NAMES[stage], 'progress': progress,
        'stage_number': active['stage'] + 1, 'stage_count': len(STAGES),
        'completed_stages': [STAGE_NAMES[name] for name in STAGES[:active['stage']]],
        'next_stage': STAGE_NAMES[STAGES[active['stage'] + 1]] if active['stage'] + 1 < len(STAGES) else None,
        'stage_completed': stage_progress['completed'], 'stage_total': stage_progress['total'],
        'stage_unit': stage_progress['unit'],
        'activity_state': activity_state, 'activity_age_seconds': activity_age,
        'model': model, 'elapsed_seconds': elapsed,
        'eta_seconds': eta, 'tokens': tokens,
        'report': _safe_report(folder, now),
    }
    result['status'] = overall_status(result)
    return result


def overall_status(state, now=None):
    """一句話總結目前狀況：level 為 ok／info／warn／error，供頁面頂端橫幅使用。"""
    now = time.time() if now is None else now
    job = state.get('job')
    counts = state.get('counts', {})
    waiting = counts.get('pending', 0) + counts.get('repairing', 0)
    if job:
        report = job.get('report') or {}
        age = job.get('activity_age_seconds')
        last_error = report.get('last_error')
        if not state.get('worker_alive'):
            return {'level': 'error', 'title': '背景工作程序已停止',
                    'detail': '任務仍標示為執行中，但沒有程序在處理。請到「工作與成果」按「啟動／繼續新版工作程序」。'}
        if age is not None and age > 180:
            return {'level': 'warn', 'title': '超過 3 分鐘沒有新結果',
                    'detail': f"已 {duration(age)} 沒有新的模型回覆；模型仍在計算時屬正常，若長時間不動請到「運行紀錄」查看。"}
        if job.get('activity_state') == 'waiting_gpu':
            return {'level': 'warn', 'title': '正在等待顯卡',
                    'detail': '顯卡被其他工作占用，空出後會自動繼續。'}
        if last_error and last_error.get('time') and now - last_error['time'] < 300:
            return {'level': 'warn', 'title': '剛剛發生模型錯誤，系統正在自動處理',
                    'detail': last_error.get('text') or '詳情請看下方「錯誤與提醒」。'}
        detail = f"第 {job['stage_number']}／{job['stage_count']} 階段「{job['stage_name']}」，已運行 {duration(job['elapsed_seconds'])}"
        if job.get('eta_seconds') is not None:
            detail += f"，本階段約剩 {duration(job['eta_seconds'])}"
        return {'level': 'ok', 'title': '正常製作中', 'detail': detail + '。'}
    recent = state.get('recent') or {}
    if waiting:
        if state.get('queue_paused'):
            return {'level': 'info', 'title': '佇列已暫停', 'detail': f'{waiting} 份教材等待繼續。'}
        if not state.get('worker_alive'):
            return {'level': 'warn', 'title': '工作程序未運行',
                    'detail': f'有 {waiting} 份教材待處理，請到「工作與成果」按「啟動／繼續新版工作程序」。'}
        return {'level': 'info', 'title': '等待工作程序接手', 'detail': f'{waiting} 份教材排隊中。'}
    if counts.get('paused', 0):
        return {'level': 'info', 'title': '工作已暫停', 'detail': f"{counts['paused']} 份教材已暫停，可到「工作與成果」繼續。"}
    if recent.get('status') == 'failed':
        hint = explain_error(recent.get('error')) or '請到「工作與成果」查看錯誤，修正後按「從失敗階段重試」。'
        return {'level': 'error', 'title': f"最近一份教材製作失敗（{recent.get('unit', '未命名教材')}）", 'detail': hint}
    if recent.get('status') == 'done':
        return {'level': 'info', 'title': '目前沒有進行中的工作',
                'detail': f"最近一份「{recent.get('unit', '未命名教材')}」已完成，可到「工作與成果」下載。"}
    return {'level': 'info', 'title': '目前沒有進行中的工作', 'detail': '可到「製作教材」建立新的簡報。'}
