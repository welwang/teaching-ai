"""Durable, local JSONL history of deck edits, independent of runtime-log clearing."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from filelock import FileLock, Timeout

from .store import DATA

_context = ContextVar('deck_change_context', default={})
_missing = object()
TRACKED = {'plan.json', 'reviewed-deck.json', 'rendered-deck.json', 'final-optimized-deck.json', 'design.json', 'layout.json'}


@contextmanager
def change_context(**values):
    token = _context.set(dict(_context.get(), **values))
    try:
        yield
    finally:
        _context.reset(token)


def _target(path):
    path = Path(path)
    page = int(path.stem) if path.parent.name == 'slides' and re.fullmatch(r'\d+', path.stem) and path.suffix == '.json' else None
    if page is None and path.name not in TRACKED:
        return None
    out = path.parent.parent if page is not None else path.parent
    if out.parent.name != 'jobs' or not re.fullmatch(r'[0-9a-f]{32}', out.name):
        return None
    return out, page


def before_write(path):
    target = _target(path)
    if target is None:
        return None
    try:
        before = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        before = None
    return target, before


def differences(before, after, path=''):
    """JSON-pointer field changes; preserve additions, removals and null values."""
    if before is _missing or after is _missing:
        return [dict(path=path or '/', operation='add' if before is _missing else 'remove',
                     before=None if before is _missing else before, after=None if after is _missing else after)]
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            pointer = str(key).replace('~', '~0').replace('/', '~1')
            result.extend(differences(before.get(key, _missing), after.get(key, _missing), path + '/' + pointer))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = []
        for index in range(max(len(before), len(after))):
            result.extend(differences(before[index] if index < len(before) else _missing,
                                      after[index] if index < len(after) else _missing, path + '/' + str(index)))
        return result
    return [dict(path=path or '/', operation='replace', before=before, after=after)]


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _request(out):
    database = out.parent.parent / 'jobs.sqlite'
    if not database.exists():
        return {}
    try:
        with closing(sqlite3.connect(database, timeout=2)) as connection:
            row = connection.execute('SELECT request FROM jobs WHERE id=?', (out.name,)).fetchone()
        value = json.loads(row[0]) if row else {}
        return value if isinstance(value, dict) else {}
    except (sqlite3.Error, ValueError):
        return {}


def record(out, action, before=None, after=None, **metadata):
    out = Path(out)
    if out.parent.name != 'jobs' or not re.fullmatch(r'[0-9a-f]{32}', out.name):
        return None
    root = out.parent.parent
    if root.resolve() == DATA.resolve() and len(set(out.name)) <= 3:
        return None  # Never send fixture records into the real history.
    now = datetime.now(timezone.utc)
    request = _request(out)
    from .curriculum_prompts import policy_fingerprint
    try:
        policy = policy_fingerprint(request) if request.get('grade') and request.get('subject') else ''
    except (OSError, ValueError, KeyError, TypeError):
        policy = ''
    values = dict(_context.get(), **metadata)
    actor = values.pop('actor', 'system')
    entry = dict(schema_version=1, change_id=uuid.uuid4().hex, time=now.isoformat(timespec='milliseconds'),
                 job_id=out.name, actor=actor, action=values.pop('action', action),
                 unit=request.get('unit', ''), grade=request.get('grade'), subject=request.get('subject', ''),
                 model=request.get('model', ''), teaching_policy_fingerprint=policy, **values,
                 before_sha256=_fingerprint(before), after_sha256=_fingerprint(after),
                 changes=differences(before, after), before=before, after=after)
    central = root / 'deck-changes' / (now.strftime('%Y-%m') + '.jsonl')
    line = json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + '\n'
    try:
        central.parent.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        # One shared lock protects both copies across worker processes/threads.
        with FileLock(str(root / 'deck-changes' / 'history.lock'), timeout=10):
            for destination in (central, out / 'changes.jsonl'):
                with destination.open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(line)
        return entry
    except (OSError, Timeout) as error:
        from .runlog import log_event
        log_event('deck_change_log_failed', out.name, root=root, action=action, error=str(error)[:300])
        return None


def after_write(path, value, snapshot):
    if snapshot is None:
        return
    (out, page), before = snapshot
    metadata = {}
    revision = out / 'regenerate.json'
    if revision.exists():
        try:
            info = json.loads(revision.read_text(encoding='utf-8'))
            metadata['parent_job'] = info.get('parent_job', '')
            if page is not None and info.get('page') == page - 1:
                metadata.update(trigger='user_revision', instruction=info.get('instruction', ''), requested_field=info.get('field', 'slide'))
                original = out / 'regenerate-original.json'
                if before is None and original.exists():
                    before = json.loads(original.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            pass
    if before == value:
        return
    stages = {'plan.json': 'plan', 'reviewed-deck.json': 'review', 'rendered-deck.json': 'render',
              'final-optimized-deck.json': 'publish', 'design.json': 'render', 'layout.json': 'render'}
    metadata['stage'] = _context.get().get('stage', 'write' if page is not None else stages[Path(path).name])
    metadata['reason'] = _context.get().get('reason', '系統保存教材內容與版面')
    record(out, 'artifact_created' if before is None else 'artifact_modified', before, value,
           artifact=Path(path).relative_to(out).as_posix(), page=page, **metadata)


def history_paths(root=DATA, job_id=None):
    root = Path(root)
    if job_id is not None:
        if not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise ValueError('無效工作ID')
        path = root / 'jobs' / job_id / 'changes.jsonl'
        return [path] if path.exists() else []
    return sorted((root / 'deck-changes').glob('*.jsonl'))
