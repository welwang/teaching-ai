"""Read-only bridge: only explicitly designated primary sources enter the catalog."""
import json,sqlite3
from pathlib import Path
from .store import ROOT

def units():
    path=ROOT/'data/curriculum.sqlite'
    if not path.exists():return []
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    try:
        rows=c.execute("SELECT d.id,d.title,d.metadata,b.source,b.sha256,b.metadata AS classification FROM documents d JOIN batch_sources b ON b.document_id=d.id WHERE b.batch_id='115-1' AND b.role='primary'").fetchall()
    finally:c.close()
    candidates={}
    for r in rows:
        meta=json.loads(r['classification']);doc=json.loads(r['metadata']);source=doc.get('source_file','')
        if not meta.get('candidate') or not meta.get('in_scope') or not source or not Path(source).is_file():continue
        key=(r['sha256'],meta.get('unit_code'))
        candidates[key]=dict(meta,title=r['title'],source=r['source'],path=source,document_id=r['id'])
    return sorted(candidates.values(),key=lambda u:(u['grade'],u['subject'],u.get('publisher',''),u.get('order',999)))
