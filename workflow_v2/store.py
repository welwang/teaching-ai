"""SQLite job state and stage artifacts. No writes to the legacy database."""
import hashlib,json,os,sqlite3,time,uuid
from pathlib import Path
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1]
# TEACHING_AI_DATA lets tests and screenshot previews run on a throw-away data folder.
DATA=Path(os.environ['TEACHING_AI_DATA']) if os.environ.get('TEACHING_AI_DATA') else ROOT/'data/workflow-v2'
STAGES=('source','plan','write','review','render','preview','publish')

class JobInterrupted(Exception):
    """A page or stage stopped because its owner requested pause/removal."""

def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    from .change_log import before_write,after_write
    snapshot=before_write(path)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(6):
            try:
                os.replace(tmp,path)
                after_write(path,data,snapshot)
                return
            except PermissionError:
                if attempt==5:raise
                time.sleep(.2*(attempt+1))
    finally:tmp.unlink(missing_ok=True)

class Store:
    def __init__(self,root=DATA):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created REAL, updated REAL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job TEXT, stage TEXT, message TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS queue_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.root/'jobs.sqlite',timeout=20);c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=WAL')
            with c:yield c
        finally:c.close()
    def submit(self,request,ready=True):
        from .contracts import REQUEST,validate
        from .strata import is_strata
        from .model_policy import bind
        request=bind(request)
        if is_strata(request.get('model','')) != is_strata(request.get('page_model',request.get('model',''))):
            raise ValueError('同一教材不可混用 Strata 與 Ollama；請將規劃、編寫與審核指定為同一 Strata 模型')
        validate(REQUEST,request);jid=uuid.uuid4().hex
        with self.db() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
            (jid,json.dumps(request,ensure_ascii=False),'pending' if ready else 'staging',0,0,'',time.time(),time.time()))
        self.folder(jid).mkdir(parents=True,exist_ok=True)
        from .runlog import log_event
        log_event('job_submitted',jid,root=self.root,unit=request['unit'],model=request['model'],
                  page_model=request.get('page_model',request['model']))
        if request.get('teaching_prompt_override','').strip():
            from .curriculum_prompts import full_prompt
            from .change_log import record
            default_request={k:v for k,v in request.items() if k!='teaching_prompt_override'}
            record(self.folder(jid),'teaching_prompt_customized',before=full_prompt(default_request),
                   after=request['teaching_prompt_override'],actor='user',reason='僅套用本次任務的教學提示詞')
        return jid
    def folder(self,jid):
        if len(jid)!=32 or any(ch not in '0123456789abcdef' for ch in jid):raise ValueError('無效工作ID')
        return self.root/'jobs'/jid
    def get(self,jid):
        with self.db() as c:r=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not r:raise KeyError(jid)
        return dict(r)
    def list(self):
        with self.db() as c:return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC')]
    def claim(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute("SELECT value FROM queue_state WHERE key='current_job'").fetchone()
            r=c.execute('SELECT * FROM jobs WHERE id=?',(current['value'],)).fetchone() if current else None
            # A stage may still be running when another worker starts. Never claim a second deck.
            active=c.execute("SELECT id FROM jobs WHERE status IN ('running','rendering','reviewing','pausing','removing') LIMIT 1").fetchone()
            if active:return None
            from .model_policy import bind
            from .contracts import REQUEST,validate
            while True:
                if r is None or r['status'] not in ('pending','repairing'):
                    r=c.execute("SELECT * FROM jobs WHERE status IN ('pending','repairing') ORDER BY created,id LIMIT 1").fetchone()
                if not r:return None
                try:
                    request=bind(json.loads(r['request']));validate(REQUEST,request)
                except (ValueError,TypeError) as exc:
                    c.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?",
                              ('工作輸入損毀：'+str(exc)[:500],time.time(),r['id']))
                    r=None;continue
                break
            c.execute('UPDATE jobs SET request=? WHERE id=?',
                      (json.dumps(request,ensure_ascii=False),r['id']))
            r=dict(r);r['request']=json.dumps(request,ensure_ascii=False)
            c.execute("INSERT INTO queue_state(key,value) VALUES('current_job',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value",(r['id'],))
            state={3:'reviewing',4:'rendering'}.get(r['stage'],'running')
            c.execute("UPDATE jobs SET status=?,error='',updated=? WHERE id=?",(state,time.time(),r['id']))
            return dict(r)
    def event(self,jid,stage,message):
        with self.db() as c:c.execute('INSERT INTO events(job,stage,message,created) VALUES(?,?,?,?)',(jid,stage,message,time.time()))
        from .runlog import log_event
        log_event('job_event',jid,root=self.root,stage=stage,message=str(message)[:500])
    def success(self,jid):
        with self.db() as c:
            r=c.execute('SELECT stage,status FROM jobs WHERE id=?',(jid,)).fetchone()
            if r['status']=='removing':return
            stage=r['stage']+1
            c.execute('UPDATE jobs SET stage=?,status=?,attempts=0,error=?,updated=? WHERE id=?',
                (stage,'done' if stage==len(STAGES) else ('paused' if r['status']=='pausing' else 'pending'),'',time.time(),jid))
    def fail(self,jid,error):
        with self.db() as c:
            row=c.execute('SELECT attempts,status FROM jobs WHERE id=?',(jid,)).fetchone()
            if row['status']=='removing':return
            n=row['attempts']+1
            c.execute('UPDATE jobs SET attempts=?,status=?,error=?,updated=? WHERE id=?',
                (n,'paused' if row['status']=='pausing' else ('repairing' if n<3 else 'failed'),str(error)[-3000:],time.time(),jid))
    def pause_job(self,jid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise KeyError(jid)
            status=row['status']
            if status in ('pending','repairing','failed'):
                c.execute("UPDATE jobs SET status='paused',updated=? WHERE id=?",(time.time(),jid))
                from .runlog import log_event
                log_event('job_paused',jid,root=self.root,previous_status=status)
                return 'paused'
            if status in ('running','rendering','reviewing'):
                c.execute("UPDATE jobs SET status='pausing',updated=? WHERE id=?",(time.time(),jid))
                from .runlog import log_event
                log_event('job_pause_requested',jid,root=self.root,previous_status=status)
                return 'pausing'
            raise ValueError('此工作目前無法暫停')
    def acknowledge_pause(self,jid):
        """Stop an interrupted stage without advancing its checkpoint."""
        with self.db() as c:
            changed=c.execute("UPDATE jobs SET status='paused',updated=? WHERE id=? AND status='pausing'",
                              (time.time(),jid)).rowcount
        if changed:
            from .runlog import log_event
            log_event('job_paused',jid,root=self.root,interrupted=True)
        return bool(changed)
    def complete_interruption(self,jid):
        """Resolve pause/resume/remove races after the stage process has stopped."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:return 'removed'
            status=row['status']
            if status=='pausing':
                c.execute("UPDATE jobs SET status='paused',updated=? WHERE id=?",(time.time(),jid))
                result='paused'
            elif status in ('running','rendering','reviewing'):
                # A Resume arrived while the old process was being stopped.
                c.execute("UPDATE jobs SET status='pending',updated=? WHERE id=?",(time.time(),jid))
                result='pending'
            else:result=status
        if result=='removing':self.finish_remove(jid);return 'removed'
        from .runlog import log_event
        log_event('stage_interrupt_resolved',jid,root=self.root,status=result)
        return result
    def resume_job(self,jid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status,stage FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise KeyError(jid)
            if row['status'] not in ('paused','pausing'):raise ValueError('此工作目前沒有暫停')
            if row['status']=='pausing':
                state={3:'reviewing',4:'rendering'}.get(row['stage'],'running')
            else:state='pending'
            c.execute('UPDATE jobs SET status=?,updated=? WHERE id=?',(state,time.time(),jid))
        from .runlog import log_event
        log_event('job_resumed',jid,root=self.root,status=state)
    def remove_job(self,jid):
        """Remove idle work now; signal the active stage for prompt interruption."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise KeyError(jid)
            if row['status'] in ('running','rendering','reviewing','pausing','removing'):
                c.execute("UPDATE jobs SET status='removing',updated=? WHERE id=?",(time.time(),jid))
                from .runlog import log_event
                log_event('job_remove_requested',jid,root=self.root,previous_status=row['status'])
                return None
            if row['status']=='staging':raise ValueError('工作仍在準備中')
            # Claim cannot pick this job after the transaction commits.
            c.execute("UPDATE jobs SET status='removing',updated=? WHERE id=?",(time.time(),jid))
        return self.finish_remove(jid)
    def finish_remove(self,jid):
        import shutil
        if self.get(jid)['status']!='removing':raise ValueError('工作尚未停止')
        source=self.folder(jid)
        trash=self.root/'trash';trash.mkdir(parents=True,exist_ok=True)
        target=trash/(jid+'-'+uuid.uuid4().hex[:8])
        if source.exists():shutil.move(str(source),str(target))
        with self.db() as c:
            c.execute('DELETE FROM events WHERE job=?',(jid,))
            c.execute('DELETE FROM jobs WHERE id=? AND status=?',(jid,'removing'))
        from .runlog import log_event
        log_event('job_removed',jid,root=self.root,job_file=False,trash_path=str(target) if target.exists() else '')
        return target if target.exists() else None
    def retry(self,jid):
        with self.db() as c:c.execute("UPDATE jobs SET status='pending',attempts=0,error='',updated=? WHERE id=? AND status='failed'",(time.time(),jid))
    def reset_changed_source(self,jid):
        """Archive stale checkpoints and restart after the textbook changes."""
        import shutil
        source=self.folder(jid)
        history=self.root/'history';history.mkdir(parents=True,exist_ok=True)
        target=history/(jid+'-'+uuid.uuid4().hex[:8])
        if source.exists():shutil.move(str(source),str(target))
        source.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.execute("UPDATE jobs SET stage=0,status='pending',attempts=0,error='',updated=? WHERE id=?",(time.time(),jid))
        return target
    def delete_done(self,jid):
        """Move a completed job out of the active catalog; keep a recoverable copy."""
        import shutil
        row=self.get(jid)
        if row['status']!='done':raise ValueError('只能刪除已完成的教材')
        source=self.folder(jid)
        if not source.is_dir():raise ValueError('找不到教材成果資料夾')
        trash=self.root/'trash';trash.mkdir(parents=True,exist_ok=True)
        target=trash/jid
        if target.exists():target=trash/(jid+'-'+str(int(time.time())))
        shutil.move(str(source),str(target))
        with self.db() as c:
            c.execute('DELETE FROM events WHERE job=?',(jid,))
            c.execute('DELETE FROM jobs WHERE id=?',(jid,))
        return target
    def await_outline(self,jid):
        with self.db() as c:c.execute("UPDATE jobs SET status='awaiting_outline',updated=? WHERE id=? AND status IN ('pending','paused') AND stage=2",(time.time(),jid))
    def approve_outline(self,jid):
        with self.db() as c:c.execute("UPDATE jobs SET status='pending',updated=? WHERE id=? AND status='awaiting_outline' AND stage=2",(time.time(),jid))
    def recover(self):
        # Caller must own the lifetime worker lock, so no live work is stolen.
        with self.db() as c:
            c.execute("UPDATE jobs SET status='pending' WHERE status IN ('running','rendering','reviewing')")
            c.execute("UPDATE jobs SET status='paused' WHERE status='pausing'")
        for row in self.list():
            if row['status']=='removing':self.finish_remove(row['id'])
