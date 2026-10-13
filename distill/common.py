"""Shared paths and helpers for the distillation steps (no heavy imports here)."""
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # F:\教材ai
WORK = Path(os.getenv('TEACHING_DISTILL_DIR') or ROOT / 'data' / 'distill')
JOBS = WORK / 'jobs'            # a separate job store: harvest runs never mix with real decks
CAPTURE = WORK / 'capture'      # every model request and reply while harvesting
CANDIDATES = WORK / 'candidates'
DATASET = WORK / 'dataset'
RUNS = WORK / 'runs'            # adapters, merged weights, GGUF
REPORTS = WORK / 'reports'
TRAINABLE = ('page', 'plan', 'analysis')   # tasks with an offline judge; reviews and final edits have no ground truth


def task_of(name):
    """Record stem → task: page-12 / page-12-attempt… → page; plan-call → plan; analysis-call → analysis."""
    if re.match(r'page-\d+', name):
        return 'page'
    if name.startswith('plan-call'):
        return 'plan'
    if name.startswith('analysis'):
        return 'analysis'
    if name.startswith('review'):
        return 'review'
    if name.startswith('final-optimize'):
        return 'final'
    if name.startswith('worksheet'):
        return 'worksheet'
    if name.startswith('source-ocr'):
        return 'ocr'
    return 'summary'


def page_index(name):
    found = re.match(r'page-(\d+)', name)
    return int(found.group(1)) - 1 if found else None


def held_out(unit_key, every=10):
    """About one unit in ten is kept out of training and used only for the final comparison."""
    return int(hashlib.sha256(str(unit_key).encode('utf-8')).hexdigest(), 16) % every == 0


def prompt_key(messages):
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:20]


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


def append_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def read_jsonl(path):
    rows = []
    try:
        with Path(path).open(encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows
