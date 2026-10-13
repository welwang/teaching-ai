"""由通過檢查的回覆建立訓練集，依工作分割驗證集。"""
import argparse
import hashlib
from collections import Counter
from pathlib import Path

from .common import CANDIDATES, DATASET, read_json, write_json


def is_validation(job, share=20):
    return int(hashlib.sha256(job.encode('utf-8')).hexdigest(), 16) % share == 0


def examples(folder=CANDIDATES):
    for path in sorted(Path(folder).glob('*.json')):
        record = read_json(path)
        if not record or record.get('best') is None:
            continue
        best = record['candidates'][record['best']]
        if not best['verdict']['passed'] or not best['content'].strip():
            continue
        yield {'messages': list(record['messages']) + [{'role': 'assistant', 'content': best['content']}],
               'task': record['task'], 'job': Path(record['job_folder']).name, 'source': best['source']}


def summary(records):
    tasks = Counter(r['task'] for r in records)
    rescued = Counter(r['task'] for r in records if r['source'] != 'original')
    return {task: {'examples': n, 'from_retries': rescued[task]} for task, n in sorted(tasks.items())}


def main(argv=None):
    argparse.ArgumentParser(description='建立訓練資料集').parse_args(argv)
    judged = [read_json(p) for p in Path(CANDIDATES).glob('*.json')]
    judged = [r for r in judged if r]
    rows = list(examples())
    train = [r for r in rows if not is_validation(r['job'])]
    val = [r for r in rows if is_validation(r['job'])]
    DATASET.mkdir(parents=True, exist_ok=True)
    for name, part in (('train.jsonl', train), ('val.jsonl', val)):
        import json
        with (DATASET / name).open('w', encoding='utf-8') as handle:
            for row in part:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    first_try = sum(1 for r in judged if r['candidates'] and r['candidates'][0]['verdict']['passed'])
    stats = {'judged_requests': len(judged), 'with_winner': len(rows),
             'original_reply_already_passed': first_try,
             'original_pass_rate': round(first_try / max(1, len(judged)), 3),
             'train': len(train), 'val': len(val), 'jobs': len({r['job'] for r in rows}),
             'by_task': summary(rows)}
    write_json(DATASET / 'stats.json', stats)
    print(f"評過 {stats['judged_requests']} 個請求，原本一次就合格 {stats['original_pass_rate'] * 100:.0f}%；"
          f"可用來訓練 {stats['with_winner']} 筆（訓練 {len(train)}、驗證 {len(val)}，來自 {stats['jobs']} 份教材）。")
    for task, value in stats['by_task'].items():
        print(f"  {task}：{value['examples']} 筆，其中 {value['from_retries']} 筆是重寫後才合格")
    if len(train) < 200:
        print('提醒：訓練資料少於 200 筆，效果會有限；建議先再蒐集更多單元。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
