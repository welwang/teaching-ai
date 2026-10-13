"""依顯存和服務槽位決定編寫並行度；記憶體不足時回退至單槽。
刪除 data/workflow-v2/concurrency.json 可重設回退紀錄。"""
import json
import os
import re
import time

import psutil
import yaml

from .runlog import log_event
from .store import ROOT, DATA, atomic

STATE_NAME = 'concurrency.json'
DEFAULTS = {'ollama_parallel': 2, 'write_concurrency': 2, 'parallel_min_total_vram_mb': 28000, 'parallel_min_free_vram_mb': 20000}
CAPACITY = re.compile(r'out of memory|cudamalloc|cuda error|failed to allocate|unable to allocate|insufficient memory|'
                      r'not enough memory|memory layout cannot be allocated|runner process has terminated|'
                      r'顯存不足|記憶體不足', re.I)
RETRY_RESTART_SECONDS = 300


def _config():
    try:
        return yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return {}


def settings(config=None):
    config = _config() if config is None else config
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        try:
            out[key] = int(config.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            pass
    out['ollama_parallel'] = max(1, min(out['ollama_parallel'], 2))
    out['write_concurrency'] = max(1, min(out['write_concurrency'], 2))
    return out


def _path():
    return DATA / STATE_NAME


def _read():
    try:
        value = json.loads(_path().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(state):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        atomic(_path(), state)
    except OSError:
        pass


def degraded():
    return bool(_read().get('degraded'))


def is_capacity_error(text):
    return bool(CAPACITY.search(str(text or '')))


def degrade(reason):
    """Remember that two slots did not fit; idempotent."""
    state = _read()
    if state.get('degraded'):
        return False
    state.update(degraded=True, reason=str(reason)[:300], time=time.time(), restarted=False)
    _write(state)
    log_event('concurrency_degraded', message='顯存可能不足，已改成一次只編寫一頁：' + str(reason)[:120])
    return True


def reset():
    try:
        _path().unlink()
    except OSError:
        pass


def note_server(parallel):
    state = _read()
    state['server_parallel'] = int(parallel)
    _write(state)


def choose_ollama_parallel(gpu=None, config=None):
    """(slots, plain-Chinese reason) for starting the model service."""
    cfg = settings(config)
    if cfg['ollama_parallel'] <= 1:
        return 1, '設定為一次處理一頁'
    if degraded():
        return 1, '先前發生過顯存不足，維持一次處理一頁（刪除 data/workflow-v2/concurrency.json 可重新嘗試）'
    if gpu is None:
        try:
            from .monitoring import gpu as read_gpu
            gpu = read_gpu()
        except Exception:                                   # noqa: BLE001 - a monitoring problem must not stop startup
            gpu = {'error': 'unreadable'}
    if not gpu or 'error' in gpu:
        return 1, '讀不到顯卡資訊，保守地一次處理一頁'
    total, free = gpu['memory_total_mb'], gpu['memory_total_mb'] - gpu['memory_used_mb']
    if total < cfg['parallel_min_total_vram_mb']:
        return 1, f'顯卡記憶體 {total / 1024:.0f} GB 不夠同時處理兩頁（約需 {cfg["parallel_min_total_vram_mb"] / 1024:.0f} GB 以上），一次處理一頁'
    if free < cfg['parallel_min_free_vram_mb']:
        return 1, f'目前可用顯存只有 {free / 1024:.1f} GB（約需 {cfg["parallel_min_free_vram_mb"] / 1024:.0f} GB），先一次處理一頁'
    return 2, f'顯存足夠（可用 {free / 1024:.1f} GB），可同時編寫兩頁'


def server_parallel(config=None):
    """Slots of the model service we talk to: read from the running process; the configured value when none runs yet."""
    try:
        from .engine import listener
        owner = listener()
    except Exception:                                       # noqa: BLE001
        owner = None
    if owner is None:
        return settings(config)['ollama_parallel']
    try:
        return max(1, min(int(owner.environ().get('OLLAMA_NUM_PARALLEL', '1')), 2))
    except (psutil.Error, ValueError, OSError):
        return max(1, min(int(_read().get('server_parallel') or 1), 2))


def write_workers(request=None, config=None):
    """How many pages the write stage may draft at the same time (1 or 2)."""
    if degraded():
        return 1
    try:
        from .strata import is_strata
        if request and is_strata(request.get('page_model') or request.get('model', '')):
            return 1
    except Exception:                                      # noqa: BLE001
        pass
    override = os.getenv('MAX_PPT_CONCURRENCY')
    if override in ('1', '2'):                             # explicit operator choice
        return int(override)
    return max(1, min(settings(config)['write_concurrency'], server_parallel(config)))


def status():
    """For the details panel: (workers, plain-Chinese sentence)."""
    if degraded():
        return 1, '目前一次編寫 1 頁（曾偵測到顯存不足）'
    workers = write_workers()
    return workers, (f'同時編寫 {workers} 頁' if workers > 1 else '目前一次編寫 1 頁')


def restart_if_degraded():
    """Idle-time hook for the worker: after a memory error, restart the model service with one slot."""
    state = _read()
    if not state.get('degraded') or state.get('restarted'):
        return False
    if server_parallel() <= 1:
        state['restarted'] = True
        _write(state)
        return False
    if time.time() - float(state.get('restart_tried') or 0) < RETRY_RESTART_SECONDS:
        return False
    state['restart_tried'] = time.time()
    _write(state)
    from . import engine
    try:
        engine.restart_owned_server(1)
    except (RuntimeError, OSError, ValueError, psutil.Error) as exc:
        log_event('concurrency_restart_failed', message='想把模型服務改回一次處理一頁，但這次沒成功，稍後會再試：' + str(exc)[:100])
        return False
    state['restarted'] = True
    _write(state)
    log_event('concurrency_decision', parallel=1, message='已把模型服務改回一次處理一頁並重新啟動')
    return True
