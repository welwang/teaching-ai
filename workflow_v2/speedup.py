"""Time savers shared by the pipeline: cross-job caches and a bounded parallel map.

Everything here is content-keyed and safe to delete; a miss simply means the slow path runs.
"""
import contextvars
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import store

MAX_FILES = 400


def root_of(job_folder):
    """The data folder that owns a job folder (data/workflow-v2/jobs/<id> -> data/workflow-v2).

    A folder that is not a real job folder (tests, scratch work) gets no shared cache at all.
    """
    folder = Path(job_folder)
    return folder.parent.parent if folder.parent.name == 'jobs' else None


def _folder(root, kind):
    return Path(root) / 'cache' / kind


def _path(root, kind, key):
    raw = json.dumps(key, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    return _folder(root, kind) / (hashlib.sha256(raw).hexdigest()[:40] + '.json')


def get(root, kind, key, ttl=None, now=None):
    """The cached value for key, or None when missing, damaged or older than ttl seconds."""
    if root is None:
        return None
    path = _path(root, kind, key)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        if ttl is not None and (time.time() if now is None else now) - record['saved'] > ttl:
            return None
        return record['value']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def put(root, kind, key, value):
    if root is None:
        return
    path = _path(root, kind, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        store.atomic(path, {'saved': time.time(), 'value': value})
        prune(root, kind)
    except OSError:
        pass  # a cache that cannot be written only costs time later


def prune(root, kind, limit=MAX_FILES):
    files = sorted(_folder(root, kind).glob('*.json'), key=lambda p: p.stat().st_mtime)
    for old in files[:max(0, len(files) - limit)]:
        try:
            old.unlink()
        except OSError:
            pass


def parallel(function, items, workers=3):
    """Run function(item) for every item with at most `workers` threads; results keep the input order.

    Each task runs in a copy of the caller's context so per-request deadlines still apply.
    An exception inside one task is returned as that item's result instead of aborting the rest.
    """
    items = list(items)
    if not items:
        return []

    def guarded(item):
        try:
            return function(item)
        except Exception as exc:  # noqa: BLE001 - reported to the caller as the result
            return exc
    if len(items) == 1 or workers <= 1:
        return [guarded(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, guarded, item) for item in items]
        return [future.result() for future in futures]
