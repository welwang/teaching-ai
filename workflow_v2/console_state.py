"""Console data layer: plain dicts for the mission-control panel (no Streamlit, no pandas)."""
import shutil
import time

from .store import DATA, ROOT, STAGES
from .monitor_report import (EVENT_LABELS, LEVELS, STAGE_LABELS, clock_text, describe, explain_error, pages_in,
                             parse_time, recent_events)

STATUS_TEXT = {
    'staging': '準備中', 'pending': '排隊中', 'running': '製作中', 'rendering': '排版中',
    'reviewing': '審核中', 'repairing': '自動重試中', 'awaiting_outline': '等待確認大綱',
    'paused': '已暫停', 'pausing': '暫停中', 'removing': '移除中', 'done': '已完成', 'failed': '失敗',
}
LIVE_STATUSES = ('running', 'rendering', 'reviewing', 'pausing', 'removing')
WAITING_STATUSES = ('pending', 'repairing', 'awaiting_outline', 'paused', 'staging')
# Typical share of wall time per stage on the fixed local model; used only for the overall estimate.
STAGE_WEIGHTS = {'source': 3, 'plan': 12, 'write': 40, 'review': 25, 'render': 8, 'preview': 5, 'publish': 7}
QUIET_EVENTS = {'system_snapshot', 'job_snapshot', 'model_call_started', 'job_event'}


def refresh_seconds(config=None):
    '''Seconds between live updates of the console (config.yaml console_refresh_seconds; default 1, 1-60).'''
    if config is None:
        try:
            import yaml
            config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        except Exception:
            config = {}
    try:
        value = float(config.get('console_refresh_seconds', 1))
    except (TypeError, ValueError, AttributeError):
        return 1
    if value != value:
        return 1
    return int(min(60, max(1, round(value))))


def status_text(status):
    return STATUS_TEXT.get(status, '狀態未知')


def overall_percent(job):
    """Estimated 0-99 completion of an active job from finished stages plus the current stage's checkpoint."""
    if not job:
        return 0
    done = 0.0
    for name in STAGES:
        if name == job.get('stage'):
            break
        done += STAGE_WEIGHTS[name]
    weight = STAGE_WEIGHTS.get(job.get('stage'), 0)
    total = job.get('stage_total')
    fraction = 0.0
    if total:
        fraction = min(1.0, max(0.0, float(job.get('stage_completed') or 0) / total))
    return int(min(99, round(done + weight * fraction)))


def overall_eta(job, percent=None):
    """Extrapolate the whole job; None until enough has happened for it to mean anything."""
    percent = overall_percent(job) if percent is None else percent
    elapsed = (job or {}).get('elapsed_seconds') or 0
    if percent < 10 or elapsed < 60 or percent >= 99:
        return None
    return int(elapsed * (100 - percent) / percent)


def current_page(job):
    """Page being worked on (1-based) or None when the stage is not page-based."""
    if not job:
        return None
    found = pages_in(job.get('progress'))
    if found:
        return found[0]
    if job.get('stage_total') and job.get('stage_unit') == '頁':
        return min(job['stage_total'], (job.get('stage_completed') or 0) + 1)
    return None


def stage_chips(job):
    """[{'name','state'}] for the seven stages: done / active / todo."""
    chips = []
    index = STAGES.index(job['stage']) if job and job.get('stage') in STAGES else -1
    for i, name in enumerate(STAGES):
        chips.append({'name': STAGE_LABELS[name], 'state': 'done' if i < index else 'active' if i == index else 'todo'})
    return chips


def queue_rows(rows, limit=8):
    """Waiting and running jobs in processing order, then the latest finished ones."""
    import json
    live, waiting, finished = [], [], []
    for row in rows:
        try:
            unit = json.loads(row['request']).get('unit') or '未命名教材'
        except (ValueError, TypeError, AttributeError, KeyError):
            unit = '（資料損毀）'
        item = {'id': row['id'], 'unit': unit, 'status': row['status'], 'status_text': status_text(row['status']),
                'stage_text': STAGE_LABELS.get(STAGES[min(max(row['stage'], 0), len(STAGES) - 1)], ''),
                'error': str(row.get('error') or '')[:200], 'created': row.get('created') or 0}
        if row['status'] in LIVE_STATUSES:
            live.append(item)
        elif row['status'] in WAITING_STATUSES:
            waiting.append(item)
        elif row['status'] in ('done', 'failed'):
            finished.append(item)
    waiting.sort(key=lambda r: r['created'])
    finished.sort(key=lambda r: r['created'], reverse=True)
    ordered = live + waiting + finished[:3]
    for position, item in enumerate(ordered, 1):
        item['position'] = position
    return ordered[:limit]


def live_feed(store, job_id=None, limit=8):
    """Latest meaningful events (newest first) as small dicts; empty when no log exists yet."""
    if job_id:
        path = store.folder(job_id) / 'run.jsonl'
    else:
        path = store.root / 'run.jsonl'
        if not path.exists():
            from .runlog import SYSTEM_LOG
            path = SYSTEM_LOG
    feed = []
    for event in recent_events(path, 200):
        name = str(event.get('event'))
        if name in QUIET_EVENTS:
            continue
        when = parse_time(event.get('time'))
        text = describe(event)
        feed.append({'time': clock_text(when).split(' ')[-1] if when else '—', 'epoch': when or 0,
                     'label': EVENT_LABELS.get(name, '其他事件'), 'text': text,
                     'level': LEVELS.get(name, 'info'), 'page': event.get('page')})
        if len(feed) >= limit:
            break
    return feed


_HEALTH_CACHE = {}


def _cached(key, ttl, producer):
    hit = _HEALTH_CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _HEALTH_CACHE[key] = (now, value)
    return value


def probe_model_service(timeout=1.2):
    """Ask the local model server what is loaded; every failure is a result, never an exception."""
    try:
        import requests
        from .model import endpoint
        response = requests.get(endpoint() + '/api/ps', timeout=timeout)
        response.raise_for_status()
        loaded = [item.get('name', '') for item in response.json().get('models', []) if item.get('name')]
        return {'reachable': True, 'loaded': loaded}
    except Exception as exc:  # noqa: BLE001 - a monitor must survive any probe failure
        return {'reachable': False, 'reason': str(exc)[:160]}


def probe_image_service(timeout=0.6):
    try:
        import requests
        from .local_images import endpoint
        base = endpoint().rsplit('/sdapi/v1/txt2img', 1)[0]
        requests.get(base + '/sdapi/v1/options', timeout=timeout).raise_for_status()
        return {'reachable': True}
    except Exception as exc:  # noqa: BLE001
        return {'reachable': False, 'reason': str(exc)[:160]}


def service_health(state, model_probe=None, image_probe=None, disk_path=None):
    """List of {'key','name','state','detail'}; state is ok / warn / error / off."""
    rows = []
    alive = bool(state.get('worker_alive'))
    waiting = sum((state.get('counts') or {}).get(k, 0) for k in ('pending', 'repairing'))
    busy = bool(state.get('job'))
    if alive:
        rows.append(('worker', '工作程序', 'ok', '運作中'))
    elif busy or waiting:
        rows.append(('worker', '工作程序', 'error', '未運行，請按「啟動／繼續」'))
    else:
        rows.append(('worker', '工作程序', 'off', '待命（有新工作時啟動）'))
    model = (model_probe or (lambda: _cached('model', 4.0, probe_model_service)))()
    if model.get('reachable'):
        loaded = model.get('loaded') or []
        rows.append(('model', '本地模型服務', 'ok', ('已載入 ' + '、'.join(loaded)) if loaded else '服務正常，模型待命（工作開始時載入）'))
    else:
        rows.append(('model', '本地模型服務', 'error' if (busy or waiting) else 'warn', '連不上本機模型服務，請確認已啟動'))
    gpu = state.get('gpu') or {}
    if 'error' in gpu or not gpu:
        rows.append(('gpu', '顯卡', 'warn', '無法讀取顯卡狀態'))
    else:
        used, total = gpu['memory_used_mb'] / 1024, gpu['memory_total_mb'] / 1024
        level = 'warn' if total and used / total > 0.97 else 'ok'
        rows.append(('gpu', '顯卡', level, f"使用率 {gpu['utilization']}%，顯存 {used:.1f}／{total:.1f} 吉位元組" + ('（接近滿載）' if level == 'warn' else '')))
    from . import local_images
    if image_probe is None and not local_images.enabled():
        rows.append(('image', '本機生圖（選用）', 'off', local_images.describe(False)[1]))
    else:
        image = (image_probe or (lambda: _cached('image', 30.0, probe_image_service)))()
        if image_probe is None:
            kind, text = local_images.describe(bool(image.get('reachable')))
            rows.append(('image', '本機生圖（選用）', {'ready': 'ok', 'missing': 'warn', 'failed': 'warn'}.get(kind, 'off'), text))
        else:
            rows.append(('image', '本機生圖（選用）', 'ok' if image.get('reachable') else 'off',
                         '已就緒' if image.get('reachable') else '已啟用但尚未開啟生圖服務；沒開時自動改用授權素材與圖解'))
    try:
        free = shutil.disk_usage(disk_path or DATA).free / 2 ** 30
        rows.append(('disk', '磁碟空間', 'warn' if free < 10 else 'ok', f'剩餘 {free:.0f} 吉位元組' + ('，空間不足' if free < 10 else '')))
    except OSError:
        rows.append(('disk', '磁碟空間', 'warn', '無法讀取'))
    return [{'key': k, 'name': n, 'state': s, 'detail': d} for k, n, s, d in rows]


HEALTH_NAMES = {'database': '資料庫', 'models': '模型服務', 'gpu': '顯卡', 'disk': '磁碟空間', 'browser': '預覽轉圖',
                'office': '簡報轉 PDF', 'local_image': '本機生圖', 'strata': '輕量模型部署'}


def health_rows(report):
    """Chinese rows from health.run(): [{'name','state','detail'}]; optional parts are never errors."""
    rows = []
    for key, value in (report or {}).items():
        ready = bool(value.get('ready'))
        optional = bool(value.get('optional'))
        detail = value.get('detail')
        if isinstance(detail, dict):
            detail = '，'.join(f'{k}：{v}' for k, v in detail.items() if k != 'ready')
        elif isinstance(detail, list):
            detail = '、'.join(map(str, detail))
        text = str(detail or '')[:200]
        rows.append({'key': key, 'name': HEALTH_NAMES.get(key, key), 'state': 'ok' if ready else ('off' if optional else 'error'),
                     'detail': text if ready else ((text or '未就緒') + ('（選用功能，不影響文字簡報）' if optional else ''))})
    return rows


def minutes_text(seconds):
    """'約 3 分鐘' style remaining-time phrase; None when unknown."""
    if seconds is None:
        return None
    seconds = int(max(0, seconds))
    if seconds < 60:
        return '不到 1 分鐘'
    minutes = round(seconds / 60)
    if minutes < 60:
        return f'約 {minutes} 分鐘'
    hours, rest = divmod(minutes, 60)
    return f'約 {hours} 小時' + (f' {rest} 分鐘' if rest else '')


def elapsed_text(seconds):
    seconds = int(max(0, seconds or 0))
    if seconds < 60:
        return '不到 1 分鐘'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes} 分鐘'
    hours, rest = divmod(minutes, 60)
    return f'{hours} 小時' + (f' {rest} 分鐘' if rest else '')


def _short(text, limit=22):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def headline(state, queue, health, now=None):
    """What to tell the user right now: {'level','title','hint','action','action_label','job_id'}.

    level is ok / info / warn / error; error and warn mean the user has something to do.
    action is None or one of start / resume / retry (one button at most).
    """
    now = time.time() if now is None else now
    job = state.get('job')
    rows = {row['key']: row for row in (health or [])}
    queue = queue or []
    out = {'level': 'ok', 'title': '', 'hint': '', 'action': None, 'action_label': '', 'job_id': None}
    if rows.get('worker', {}).get('state') == 'error':
        waiting = sum(1 for r in queue if r['status'] in ('pending', 'repairing', 'running', 'rendering', 'reviewing'))
        out.update(level='error', title='需要你處理：製作程式沒有在運作',
                   hint=(f'有 {waiting} 份教材在等。' if waiting else '') + '已完成的內容都保留著，按下按鈕就會接著做。',
                   action='start', action_label='啟動並接著製作')
        return out
    if job and rows.get('model', {}).get('state') == 'error':
        out.update(level='error', title='需要你處理：AI 模型沒有回應',
                   hint='請確認模型服務已開啟。已完成的頁面都保留著，恢復後會自動接著做。',
                   action='resume', action_label='再試一次')
        return out
    if job:
        percent = overall_percent(job)
        eta = overall_eta(job, percent)
        page = current_page(job)
        total = job.get('stage_total') if job.get('stage_unit') == '頁' else None
        title = f'正在製作第 {page} 頁（共 {total} 頁）' if page and total else f"正在{job.get('stage_name') or '製作'}"
        remaining = minutes_text(eta)
        if remaining:
            title += f'，{remaining}後完成'
        out.update(title=title, hint=_short(job.get('unit'), 40))
        return out
    if any(r['status'] == 'awaiting_outline' for r in queue):
        out.update(level='warn', title='需要你處理：請確認大綱',
                   hint='到「我的教材」看一下頁序和主題，按「確認大綱並繼續生成」。')
        return out
    if state.get('queue_paused') or any(r['status'] == 'paused' for r in queue):
        out.update(level='warn', title='已暫停', hint='已完成的頁面都保留著。想繼續時按下按鈕。',
                   action='resume', action_label='繼續製作')
        return out
    waiting = [r for r in queue if r['status'] in ('pending', 'repairing', 'staging')]
    if waiting:
        out.update(level='info', title=f'有 {len(waiting)} 份教材在排隊，很快就會開始',
                   hint=_short(waiting[0]['unit'], 40))
        return out
    finished = next((r for r in queue if r['status'] in ('done', 'failed')), None)
    if finished:
        age = now - float(finished.get('created') or 0)
        if finished['status'] == 'failed' and age < 3 * 86400:
            hint = explain_error(finished.get('error')) or '過程中發生了一點問題。'
            out.update(level='error', title=f"需要你處理：「{_short(finished['unit'])}」沒有做完",
                       hint=hint + ' 已完成的頁面都保留著，重試會從失敗的地方接著做。',
                       action='retry', action_label='從失敗處重試', job_id=finished['id'])
            return out
        if finished['status'] == 'done' and age < 12 * 3600:
            out.update(title=f"「{_short(finished['unit'])}」做好了", hint='到「我的教材」下載簡報檔。')
            return out
    out.update(title='一切正常，目前沒有進行中的工作', hint='到「製作教材」選好單元，按「開始製作簡報」就會開始。')
    return out


TRACK_NAMES = {'source': '讀取教材', 'plan': '規劃', 'write': '撰寫', 'review': '審查', 'render': '排版', 'preview': '預覽', 'publish': '發佈'}
HISTORY_LENGTH = 60


def hms(seconds):
    """'01:22:10' (hours may exceed 99); '--:--:--' when unknown."""
    if seconds is None:
        return '--:--:--'
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    return '%02d:%02d:%02d' % (hours, rest // 60, rest % 60)


def stage_track(job):
    """[{'name','state'}] in launch order with short names; state is done / active / todo."""
    index = STAGES.index(job['stage']) if job and job.get('stage') in STAGES else -1
    return [{'name': TRACK_NAMES[name], 'state': 'done' if i < index else 'active' if i == index else 'todo'}
            for i, name in enumerate(STAGES)]


def speed_per_second(job):
    """Generated tokens per second over the whole job (None until the model has produced something)."""
    tokens = (job or {}).get('tokens') or {}
    seconds = tokens.get('generation_seconds') or 0
    produced = tokens.get('output_tokens') or 0
    return produced / seconds if seconds > 0 and produced > 0 else None


def gpu_numbers(state):
    """{'util','used_gb','total_gb','percent'} or None when the card cannot be read."""
    gpu = (state or {}).get('gpu') or {}
    if 'error' in gpu or 'memory_total_mb' not in gpu:
        return None
    total = max(1.0, float(gpu['memory_total_mb']))
    used = float(gpu.get('memory_used_mb') or 0)
    return {'util': int(min(100, max(0, gpu.get('utilization') or 0))), 'used_gb': used / 1024,
            'total_gb': total / 1024, 'percent': int(min(100, max(0, round(used * 100 / total))))}


def push_history(history, value, limit=HISTORY_LENGTH):
    """Append one sample (0-100) and keep only the most recent `limit`."""
    history = list(history or [])
    history.append(int(min(100, max(0, value or 0))))
    return history[-limit:]