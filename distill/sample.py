"""重新生成未通過檢查的回覆，保存候選版本與檢查結果。"""
import argparse
import json
import time
from pathlib import Path

from .common import CANDIDATES, CAPTURE, JOBS, TRAINABLE, prompt_key, read_json, task_of, write_json
from .score import Context, judge, rank


def requests_to_judge(capture=CAPTURE):
    """One entry per distinct request (the same prompt can be recorded twice when a page is retried)."""
    found = {}
    for path in sorted(Path(capture).glob('*/*.json')):
        row = read_json(path)
        if not row or task_of(row.get('name', '')) not in TRAINABLE:
            continue
        key = prompt_key(row['messages'])
        if key not in found:
            found[key] = row
        elif row.get('accepted') and not found[key].get('accepted'):
            found[key] = row
    return found


def ask(row, temperature, seed, post=None):
    """One more reply to exactly the recorded request, through the same local model service."""
    import requests
    from workflow_v2.model import endpoint, gpu_slot
    from workflow_v2.model_policy import configured_model
    options = dict(row.get('options') or {})
    options.update(temperature=temperature, seed=seed)
    body = {'model': row.get('model') or configured_model(), 'stream': False, 'think': False, 'format': row['schema'],
            'keep_alive': '30m', 'messages': row['messages'], 'options': options}
    post = post or requests.post
    with gpu_slot():
        response = post(endpoint() + '/api/chat', json=body, timeout=(10, 600))
    response.raise_for_status()
    data = response.json()
    return data.get('message', {}).get('content', ''), data.get('done_reason', '')


def pick(key, row, context, tries, temperature=0.7, asker=ask, log=print):
    """Judge the recorded reply, then ask again until something passes. Returns the saved record."""
    target = CANDIDATES / f'{key}.json'
    saved = read_json(target)
    if saved and (saved.get('best') is not None or len(saved['candidates']) >= tries + 1):
        return saved
    record = saved or {'key': key, 'name': row['name'], 'task': task_of(row['name']), 'job_folder': row['job_folder'],
                       'messages': row['messages'], 'schema': row['schema'], 'candidates': []}
    if not record['candidates']:
        verdict = judge(row['name'], row.get('content', ''), row['schema'], context, row.get('done_reason', ''))
        record['candidates'].append({'source': 'original', 'content': row.get('content', ''), 'verdict': verdict})
    while True:
        best = min(record['candidates'], key=lambda c: rank(c['verdict']))
        clean = best['verdict']['passed'] and best['verdict']['minor'] == 0
        if clean or len(record['candidates']) > tries:
            break
        seed = 1000 + len(record['candidates'])
        try:
            content, reason = asker(row, temperature, seed)
            verdict = judge(row['name'], content, row['schema'], context, reason)
        except Exception as exc:  # noqa: BLE001 - a failed call is just a failed try
            content, verdict = '', {'passed': False, 'reason': '呼叫失敗：' + str(exc)[:200], 'hard': 99, 'major': 99, 'minor': 99, 'fixed': 0, 'chars': 0}
        record['candidates'].append({'source': f'sample-{seed}', 'content': content, 'verdict': verdict})
        write_json(target, record)
    best = min(record['candidates'], key=lambda c: rank(c['verdict']))
    record['best'] = record['candidates'].index(best) if best['verdict']['passed'] else None
    write_json(target, record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description='挑選：每個請求找出一個通過全部品質檢查的版本')
    parser.add_argument('--tries', type=int, default=4, help='原本的回覆沒通過時，最多再請模型重寫幾次（預設 4）')
    parser.add_argument('--temperature', type=float, default=0.7)
    parser.add_argument('--limit', type=int, default=0, help='這次最多處理幾個請求（0 = 全部）')
    args = parser.parse_args(argv)
    from workflow_v2.engine import ensure_server
    from workflow_v2.store import Store
    store = Store(JOBS)
    found = requests_to_judge()
    print(f'共 {len(found)} 個不同的請求。')
    if not found:
        raise SystemExit('還沒有紀錄，請先執行 1-蒐集.cmd')
    ensure_server()
    contexts, done, passed, extra, started = {}, 0, 0, 0, time.time()
    for key, row in found.items():
        if args.limit and done >= args.limit:
            break
        job = Path(row['job_folder']).name
        if job not in contexts:
            try:
                contexts[job] = Context(row['job_folder'], json.loads(store.get(job)['request']))
            except (KeyError, ValueError):
                continue
        before = len((read_json(CANDIDATES / f'{key}.json') or {}).get('candidates', []))
        record = pick(key, row, contexts[job], args.tries, args.temperature)
        done += 1
        passed += record.get('best') is not None
        extra += len(record['candidates']) - max(1, before)
        if done % 10 == 0:
            print(f'  {done} 個請求：{passed} 個找到合格版本，這次多問了 {extra} 次，{round((time.time() - started) / 60)} 分鐘')
    print(f'完成：{done} 個請求中 {passed} 個有合格版本（{round(passed * 100 / max(1, done))}%）。下一步：python -m distill.build')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
