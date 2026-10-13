"""Each stage runs in a killable subprocess, with a single lifetime worker lock."""
import argparse,hashlib,json,os,subprocess,sys,time
import psutil
from filelock import FileLock,Timeout
from .store import Store,STAGES,ROOT,atomic,JobInterrupted
from .runlog import log_event

TIMEOUTS={'source':180,'plan':1800,'write':3600,'review':3600,'render':1800,'preview':420,'publish':600}
# Seconds added per planned page. A fixed ceiling killed long (up to 50 page) decks halfway and made the
# queue redo finished work; the ceiling now grows with the deck but never drops below the base value.
PAGE_SECONDS={'write':150,'review':120,'render':25,'preview':8,'publish':35}
PAGE_BASE={'write':0,'review':0,'render':300,'preview':120,'publish':60}
STAGE_NAMES={'source':'讀取主教材','plan':'規劃大綱','write':'逐頁編寫','review':'本地模型審核','render':'製作簡報',
             'preview':'製作預覽','publish':'最後內容優化與整理成果'}

def stage_timeout(stage,request):
    pages=max(1,int(request.get('slide_count') or 1))
    return max(TIMEOUTS[stage],PAGE_BASE.get(stage,0)+PAGE_SECONDS.get(stage,0)*pages)

def stop_tree(proc):
    try:
        parent=psutil.Process(proc.pid);children=parent.children(recursive=True)
        for p in children+[parent]:
            try:p.kill()
            except psutil.NoSuchProcess:pass
        psutil.wait_procs(children+[parent],timeout=5)
    except psutil.NoSuchProcess:pass


def source_changed(request,out):
    """Do not reuse pages built from an older version of the primary textbook."""
    snapshot=out/'source.json'
    path=__import__('pathlib').Path(request['source_path'])
    if not snapshot.is_file() or not path.is_file():return False
    expected=json.loads(snapshot.read_text(encoding='utf-8')).get('sha256')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return bool(expected) and digest.hexdigest()!=expected

def step(store):
    row=store.claim()
    if not row:return False
    try:return _claimed_step(store,row)
    except Exception as exc:
        # A launch/checkpoint failure must not strand a claimed job or kill
        # the scheduler before it can handle the next pending presentation.
        jid=row['id']
        stage=STAGES[row['stage']] if 0<=row['stage']<len(STAGES) else 'unknown'
        log_event('stage_failed',jid,root=store.root,stage=stage,
                  error=str(exc)[:500],error_type=type(exc).__name__)
        status=store.get(jid)['status']
        if status in ('pausing','removing'):store.complete_interruption(jid)
        else:store.fail(jid,str(exc))
        return True


def _claimed_step(store,row):
    if not 0<=row['stage']<len(STAGES):raise ValueError('無效工作階段')
    jid=row['id'];stage=STAGES[row['stage']];out=store.folder(jid)
    request=json.loads(row['request'])
    if row['stage']>0 and source_changed(request,out):
        archived=store.reset_changed_source(jid)
        log_event('source_changed_restart',jid,root=store.root,stage=stage,
                  archived_to=str(archived))
        return True
    started=time.monotonic()
    log_event('stage_started',jid,root=store.root,stage=stage,attempt=row['attempts']+1)
    (out/'last-error.json').unlink(missing_ok=True)
    store.event(jid,stage,'開始執行')
    env=os.environ.copy();env['PYTHONUTF8']='1'
    with (out/(stage+'.log')).open('a',encoding='utf-8') as log:
        p=subprocess.Popen([sys.executable,'-m','workflow_v2.worker','--stage',stage,'--job',jid,'--root',str(store.root)],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        limit=stage_timeout(stage,request);deadline=started+limit
        try:
            while p.poll() is None:
                status=store.get(jid)['status']
                if status in ('pausing','removing'):
                    stop_tree(p)
                    log_event('stage_interrupted',jid,root=store.root,stage=stage,
                              action=status,duration_seconds=round(time.monotonic()-started,3))
                    log.close()
                    store.complete_interruption(jid)
                    return True
                if time.monotonic()>=deadline:
                    stop_tree(p)
                    log_event('stage_failed',jid,root=store.root,stage=stage,
                              duration_seconds=round(time.monotonic()-started,3),error='階段超時')
                    if store.get(jid)['status'] in ('removing','pausing'):
                        log.close()
                        store.complete_interruption(jid)
                    else:store.fail(jid,f'階段超時：{STAGE_NAMES.get(stage,stage)}（{limit//60} 分鐘內未完成）')
                    return True
                time.sleep(.3)
        finally:
            if p.poll() is None:stop_tree(p)
    if store.get(jid)['status']=='removing':
        log_event('stage_cancelled',jid,root=store.root,stage=stage,
                  duration_seconds=round(time.monotonic()-started,3))
        store.finish_remove(jid);return True
    if store.get(jid)['status']=='pausing' and p.returncode:
        store.complete_interruption(jid);return True
    if p.returncode:
        error_file=out/'last-error.json'
        error=json.loads(error_file.read_text(encoding='utf-8'))['error'] if error_file.exists() else '工作程序異常結束，請查看'+stage+'.log'
        log_event('stage_failed',jid,root=store.root,stage=stage,
                  duration_seconds=round(time.monotonic()-started,3),error=error[:500])
        store.event(jid,stage,error);store.fail(jid,error)
    else:
        log_event('stage_completed',jid,root=store.root,stage=stage,
                  duration_seconds=round(time.monotonic()-started,3))
        store.success(jid);store.event(jid,stage,'完成')
        if stage=='plan' and json.loads(row['request']).get('review_outline'):
            store.await_outline(jid);store.event(jid,stage,'等待使用者確認大綱')
    if store.get(jid)['status']=='removing':store.finish_remove(jid)
    return True

def run(store,once=False):
    with FileLock(str(store.root/'worker.lock'),timeout=0):
        store.recover()
        while True:
            if (store.root/'pause').exists():
                if once:return
                time.sleep(2);continue
            worked=step(store)
            if once:return
            if not worked:
                try:
                    from . import concurrency
                    concurrency.restart_if_degraded()
                except Exception:pass        # a failed tuning attempt must never stop the worker
                time.sleep(2)

def start():
    store=Store()
    try:
        with FileLock(str(store.root/'worker.lock'),timeout=0):pass
    except Timeout:return
    env=os.environ.copy();env['PYTHONUTF8']='1'
    with (store.root/'worker.log').open('a',encoding='utf-8') as log:
        p=subprocess.Popen([sys.executable,'-m','workflow_v2.worker'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (store.root/'worker.pid').write_text(str(p.pid))

def pause():
    """Finish the current checkpoint; do not interrupt an atomic output write."""
    store=Store();(store.root/'pause').touch()

def resume():
    from .engine import ensure_server, listener
    from . import strata
    # Start only the backend required by the next saved task. Loading the
    # resident engine must not prevent the control UI from remaining usable.
    store=Store()
    row=next((r for r in store.list() if r['status'] in ('running','pending','repairing')),None)
    model=json.loads(row['request'])['model'] if row else (
        strata.settings().get('preferred_model',''))
    if strata.is_strata(model):
        if not strata.installed():
            raise RuntimeError('Strata 尚未安裝完成，請查看 logs/strata-install.log')
    else:
        ensure_server()
        if listener() is None:
            raise RuntimeError('本地模型服務無法啟動，請查看服務檢查與 logs/ollama.err.log')
        from .health import models_probe
        models_probe()
    (store.root/'pause').unlink(missing_ok=True);start()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage');parser.add_argument('--job');parser.add_argument('--root');parser.add_argument('--once',action='store_true');a=parser.parse_args()
    store=Store(a.root) if a.root else Store()
    if a.stage:
        from .pipeline import HANDLERS
        row=store.get(a.job);out=store.folder(a.job)
        from .change_log import change_context
        try:
            with change_context(stage=a.stage,reason=STAGE_NAMES.get(a.stage,a.stage)):
                HANDLERS[a.stage](json.loads(row['request']),out)
        except JobInterrupted:
            sys.exit(75)
        except Exception as exc:
            atomic(out/'last-error.json',{'stage':a.stage,'error':str(exc)});raise
    else:run(store,a.once)
