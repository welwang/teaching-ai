"""Manage only the Ollama server owned by this workspace on port 11435."""
import os,shutil,subprocess,time
from pathlib import Path
import psutil,requests
from .store import ROOT,Store
from .runlog import log_event

PORT=11435
PID_FILE=ROOT/'logs/ollama.pid'
BINARY_FILE=ROOT/'logs/ollama-binary.txt'
ACTIVE={'running','rendering','reviewing','pausing'}

def listener():
    for connection in psutil.net_connections(kind='tcp'):
        if connection.status=='LISTEN' and connection.laddr.port==PORT and connection.pid:
            return psutil.Process(connection.pid)
    return None

def _owned(process):
    return (process is not None and process.name().lower()=='ollama.exe'
            and Path(process.cwd()).resolve()==ROOT.resolve()
            and process.cmdline()[-1:] == ['serve'])

def _binary(existing=None):
    # Prefer this installation's runtime over an old cached executable path.
    choices=[ROOT/'runtime/ollama/ollama.exe',
        Path(os.getenv('LOCALAPPDATA',''))/'Programs/Ollama/ollama.exe']
    on_path=shutil.which('ollama')
    if on_path:choices.append(Path(on_path))
    if existing:
        try:choices.append(Path(existing.exe()))
        except (OSError,psutil.Error):pass
    if BINARY_FILE.exists():
        choices.append(Path(BINARY_FILE.read_text(encoding='utf-8').strip()))
    for path in choices:
        try:
            if path.is_file():return path
        except OSError:
            continue
    raise FileNotFoundError('找不到本機 Ollama 執行檔')

def start_server(binary,parallel=1):
    if listener() is not None:raise RuntimeError('11435 埠已有模型服務，不能重複啟動')
    env=os.environ.copy()
    env.update(OLLAMA_HOST=f'127.0.0.1:{PORT}',OLLAMA_MODELS=str(ROOT/'models/ollama'),
               OLLAMA_NUM_PARALLEL=str(parallel),OLLAMA_FLASH_ATTENTION='1',
               OLLAMA_KV_CACHE_TYPE='q8_0',OLLAMA_MAX_LOADED_MODELS='1',
               OLLAMA_NO_CLOUD='1')
    (ROOT/'logs').mkdir(exist_ok=True)
    from .runlog import rotate
    for name in ('ollama.out.log','ollama.err.log'):rotate(ROOT/'logs'/name)
    with (ROOT/'logs/ollama.out.log').open('a',encoding='utf-8') as out, \
         (ROOT/'logs/ollama.err.log').open('a',encoding='utf-8') as err:
        process=subprocess.Popen([str(binary),'serve'],cwd=ROOT,env=env,
            stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    PID_FILE.write_text(str(process.pid),encoding='utf-8')
    BINARY_FILE.write_text(str(binary),encoding='utf-8')
    try:
        from . import concurrency
        concurrency.note_server(parallel)
    except OSError:pass
    for _ in range(40):
        if process.poll() is not None:break
        try:
            if requests.get(f'http://127.0.0.1:{PORT}/api/tags',timeout=1).ok:
                log_event('engine_started',parallel=parallel,pid=process.pid)
                return process.pid
        except requests.RequestException:pass
        time.sleep(.5)
    raise RuntimeError('本地模型服務未能啟動，請查看 logs/ollama.err.log')

def restart_owned_server(parallel=1):
    if parallel not in (1,2):raise ValueError('並行數只允許 1 或 2')
    if any(row['status'] in ACTIVE for row in Store().list()):
        raise RuntimeError('仍有教材工作執行中，不能重啟模型服務')
    owner=listener()
    if owner is not None and not _owned(owner):
        raise RuntimeError('11435 埠由其他系統持有，不能重啟')
    binary=_binary(owner)
    if owner is not None:
        old_pid=owner.pid
        workers=[child for child in owner.children(recursive=True)
                 if child.name().lower()=='llama-server.exe']
        owner.terminate()
        try:owner.wait(timeout=15)
        except psutil.TimeoutExpired:raise RuntimeError('舊模型服務未停止，沒有強制結束')
        for worker in workers:
            try:
                if worker.is_running() and not any(
                    connection.status=='ESTABLISHED'
                    for connection in worker.net_connections(kind='tcp')):
                    worker.terminate()
                    worker.wait(timeout=15)
                    log_event('orphan_model_worker_stopped',pid=worker.pid,parent_pid=old_pid)
            except (psutil.NoSuchProcess,psutil.ZombieProcess):pass
        log_event('engine_stopped',pid=old_pid)
    return start_server(binary,parallel)

def ensure_server(parallel=None):
    """Start the model service if it is not running. `parallel=None` lets concurrency decide (2 slots when the
    card can afford it, otherwise 1) and writes the decision in plain Chinese to the system log."""
    try:
        if listener() is not None:return
        if parallel is None:
            from . import concurrency
            parallel,reason=concurrency.choose_ollama_parallel()
            log_event('concurrency_decision',parallel=parallel,message=f'模型服務每次可處理 {parallel} 頁：{reason}')
        start_server(_binary(),parallel)
    except (OSError,RuntimeError,psutil.Error) as exc:
        log_event('engine_start_failed',error=str(exc)[:300])

if __name__=='__main__':
    import sys
    print(restart_owned_server(int(sys.argv[1]) if len(sys.argv)>1 else 1))
