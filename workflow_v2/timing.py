"""Where did the time go? Per-stage wall time and model time from a job's run.jsonl.

    python -m workflow_v2.timing <job folder> [...]
"""
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path

KINDS = ((r'^審核第 \d+～', '批次審核'), (r'^審核', '逐頁審核'), (r'^編寫', '編寫／修正頁面'), (r'整理主教材', '主教材摘要'),
         (r'規劃投影片大綱', '大綱'), (r'教材解析', '教材解析'), (r'最後內容優化', '最後內容優化'), (r'學習單', '學習單'))


def _time(text):
    return datetime.fromisoformat(text).timestamp()


def kind_of(label):
    for pattern, name in KINDS:
        if re.search(pattern, label or ''):
            return name
    return '其他'


def profile(folder):
    """{'wall','stages':{name:{'wall','model','idle','by_kind':{}}},'calls','retries','tokens'} for one job."""
    events = []
    for line in (Path(folder) / 'run.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    windows = {}
    for event in events:
        if event.get('event') == 'stage_started':
            windows.setdefault(event['stage'], [_time(event['time']), None])
        elif event.get('event') == 'stage_completed' and event['stage'] in windows:
            windows[event['stage']][1] = _time(event['time'])
    calls = []
    for event in events:
        if event.get('event') == 'model_call_finished' and event.get('duration_seconds') is not None:
            end = _time(event['time'])
            calls.append((end - event['duration_seconds'], end, kind_of(event.get('label')), event))
    stages = {}
    for name, (start, end) in windows.items():
        if end is None:
            continue
        inside = [c for c in calls if c[0] >= start - 1 and c[1] <= end + 1]
        by_kind = collections.defaultdict(float)
        for c in inside:
            by_kind[c[2]] += c[1] - c[0]
        busy = sum(by_kind.values())
        stages[name] = {'wall': round(end - start, 1), 'model': round(busy, 1), 'idle': round(max(0, end - start - busy), 1),
                        'by_kind': {k: round(v, 1) for k, v in sorted(by_kind.items(), key=lambda x: -x[1])}}
    rework = collections.Counter(e['event'] for e in events if e.get('event') in
                                 ('page_retry', 'qa_rejected', 'review_rejected', 'fallback_page_created'))
    started = [_time(e['time']) for e in events if e.get('time')]
    return {'wall': round(max(started) - min(started), 1) if started else 0, 'stages': stages, 'calls': len(calls),
            'rework': dict(rework),
            'prompt_tokens': sum(c[3].get('prompt_tokens') or 0 for c in calls),
            'output_tokens': sum(c[3].get('output_tokens') or 0 for c in calls)}


def fit_speed(folder):
    """(tokens per second decoding, tokens per second reading the prompt) by least squares over write calls."""
    rows = []
    for line in (Path(folder) / 'run.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('event') == 'model_call_finished' and (event.get('label') or '').startswith('編寫'):
            rows.append((event.get('prompt_tokens') or 0, event.get('output_tokens') or 0, event['duration_seconds']))
    if len(rows) < 5:
        return None
    # normal equations for duration = a*prompt + b*output + c
    n = len(rows)
    sx = [sum(r[i] for r in rows) for i in range(2)]
    sy = sum(r[2] for r in rows)
    sxx = [[sum(r[i] * r[j] for r in rows) for j in range(2)] for i in range(2)]
    sxy = [sum(r[i] * r[2] for r in rows) for i in range(2)]
    m = [[sxx[0][0], sxx[0][1], sx[0]], [sxx[1][0], sxx[1][1], sx[1]], [sx[0], sx[1], n]]
    v = [sxy[0], sxy[1], sy]
    for i in range(3):
        pivot = m[i][i]
        if abs(pivot) < 1e-9:
            return None
        for j in range(i + 1, 3):
            f = m[j][i] / pivot
            m[j] = [a - f * b for a, b in zip(m[j], m[i])]
            v[j] -= f * v[i]
    c = [0.0] * 3
    for i in (2, 1, 0):
        c[i] = (v[i] - sum(m[i][j] * c[j] for j in range(i + 1, 3))) / m[i][i]
    if c[0] <= 0 or c[1] <= 0:
        return None
    return round(1 / c[1], 1), round(1 / c[0])


def write_throughput(folder):
    """{'workers','tokens','wall','combined','per_call'} for the write stage, or None.

    combined = output tokens of all write calls / write-stage wall time: the number that decides whether
    writing two pages at once is worth it (compare a job made with 1 against one made with 2)."""
    events = []
    for line in (Path(folder) / 'run.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    wall = next((float(e['duration_seconds']) for e in events
                 if e.get('event') == 'stage_completed' and e.get('stage') == 'write' and e.get('duration_seconds')), 0)
    calls = [e for e in events if e.get('event') == 'model_call_finished' and e.get('stage') == 'write'
             and e.get('duration_seconds')]
    if not wall or not calls:
        return None
    tokens = sum(e.get('output_tokens') or 0 for e in calls)
    busy = sum(float(e['duration_seconds']) for e in calls)
    workers = max([int(e.get('workers') or 1) for e in events if e.get('event') == 'write_concurrency'] or [1])
    return {'workers': workers, 'tokens': tokens, 'wall': round(wall, 1),
            'combined': round(tokens / wall, 1), 'per_call': round(tokens / busy, 1) if busy else 0}


def report(folder):
    data = profile(folder)
    lines = [f"{Path(folder).name[:8]}：全程 {data['wall']:.0f} 秒，模型呼叫 {data['calls']} 次，重做事件 {data['rework'] or '無'}"]
    for name, row in data['stages'].items():
        kinds = '、'.join(f'{k} {v:.0f}s' for k, v in row['by_kind'].items())
        lines.append(f"  {name:8s} {row['wall']:6.1f}s（模型 {row['model']:.0f}s／其他 {row['idle']:.0f}s）{kinds}")
    speed = fit_speed(folder)
    if speed:
        lines.append(f'  估計速度：產出 {speed[0]} 字元單位／秒（decode tok/s），讀入提示 {speed[1]} tok/s')
    write = write_throughput(folder)
    if write:
        lines.append(f"  編寫合計產出：{write['combined']} tok/s（同時 {write['workers']} 頁，每頁 {write['per_call']} tok/s，"
                     f"{write['tokens']} tok／{write['wall']:.0f}s）——比較同時 1 頁與 2 頁的這個數字，大者較快")
    return '\n'.join(lines)


if __name__ == '__main__':
    for path in sys.argv[1:]:
        print(report(path))
