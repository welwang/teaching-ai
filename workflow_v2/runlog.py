"""Bounded, process-safe JSONL audit trail for the local workflow."""
import json,time
from collections import deque
from datetime import datetime,timezone
from pathlib import Path
from filelock import FileLock,Timeout
from .store import ROOT,DATA

SYSTEM_LOG=ROOT/'logs'/'workflow-v2.jsonl'
MAX_BYTES=5_000_000

def rotate(path,max_bytes=MAX_BYTES):
    """Before a service is (re)started: keep one previous copy of a large log instead of growing forever.
    Never fails (a log another process still holds open on Windows is simply left as is)."""
    path=Path(path)
    try:
        if path.exists() and path.stat().st_size>max_bytes:
            older=path.with_name(path.name+'.1')
            older.unlink(missing_ok=True)
            path.replace(older)
            return True
    except OSError:
        pass
    return False

def _append(path,line):
    path.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(path)+'.lock',timeout=3):
        if path.exists() and path.stat().st_size+len(line.encode('utf-8'))>MAX_BYTES:
            older=path.with_name(path.name+'.1')
            older.unlink(missing_ok=True)
            path.replace(older)
        with path.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(line+'\n')

def log_event(event,job_id=None,root=DATA,job_file=True,**fields):
    """Log metadata only; model prompts and textbook text stay in job artifacts."""
    if job_id and (len(job_id)!=32 or any(ch not in '0123456789abcdef' for ch in job_id)):
        return
    record={'time':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'event':event,'job_id':job_id or '',**fields}
    line=json.dumps(record,ensure_ascii=False,default=str,separators=(',',':'))
    root=Path(root)
    if root.resolve()==DATA.resolve() and job_id and len(set(job_id))<=3:
        return  # 'aaaa…'-style ids are test fixtures; they must never reach the real audit trail
    system_path=SYSTEM_LOG if root.resolve()==DATA.resolve() else root/'run.jsonl'
    try:
        _append(system_path,line)
        if job_file and job_id and len(job_id)==32 and all(ch in '0123456789abcdef' for ch in job_id):
            _append(root/'jobs'/job_id/'run.jsonl',line)
    except (OSError,Timeout):
        # Logging must not turn a valid PPTX into a failed job.
        pass

def tail_events(job_id=None,limit=100):
    if job_id and (len(job_id)!=32 or any(ch not in '0123456789abcdef' for ch in job_id)):
        raise ValueError('無效工作ID')
    path=DATA/'jobs'/job_id/'run.jsonl' if job_id else SYSTEM_LOG
    if not path.exists():return []
    with path.open(encoding='utf-8') as stream:
        rows=deque(stream,maxlen=max(1,min(limit,500)))
    result=[]
    for row in rows:
        try:value=json.loads(row)
        except ValueError:continue  # A crash may leave one partial final line.
        if isinstance(value,dict):result.append(value)
    return result


def clear_log(job_id=None):
    """Clear only the selected runtime log, never job artifacts or state."""
    if job_id is not None and (len(job_id)!=32 or any(ch not in '0123456789abcdef' for ch in job_id)):
        raise ValueError('無效工作ID')
    path=DATA/'jobs'/job_id/'run.jsonl' if job_id else SYSTEM_LOG
    if not path.parent.is_dir():return 0
    with FileLock(str(path)+'.lock',timeout=5):
        size=path.stat().st_size if path.exists() else 0
        path.write_text('',encoding='utf-8')
        if job_id is None:
            rotated=path.with_name(path.name+'.1')
            rotated.unlink(missing_ok=True)
    return size

def record_snapshot(store):
    """Mark the current state when structured logging is first enabled."""
    from .store import STAGES
    rows=store.list()
    log_event('system_snapshot',root=store.root,job_count=len(rows))
    for row in rows:
        log_event('job_snapshot',row['id'],root=store.root,status=row['status'],
                  stage=STAGES[min(row['stage'],len(STAGES)-1)],attempts=row['attempts'],
                  error=row['error'][:500])

if __name__=='__main__':
    from .store import Store
    record_snapshot(Store())
