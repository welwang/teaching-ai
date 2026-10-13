"""用保留教材比較新舊模型的品質與速度。"""
import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

from .common import REPORTS, WORK, held_out, read_json, read_jsonl, write_json

EVAL = WORK / 'eval'
STAGES = ('source', 'plan', 'write')


def held_out_units(units, limit):
    from .units import unit_id
    chosen = [u for u in units if held_out(unit_id(u))]
    chosen.sort(key=lambda u: hashlib.sha256(unit_id(u).encode()).hexdigest())
    return chosen[:limit]


def job_metrics(out, seconds):
    """Numbers for one finished job folder."""
    out = Path(out)
    plan = read_json(out / 'plan.json', {}) or {}
    pages = len(plan.get('slides') or [])
    report = (read_json(out / 'qa-report.json', {}) or {}).get('pages', {})
    finals = [entry.get('final') for entry in report.values()]
    events = read_jsonl(out / 'run.jsonl')
    count = lambda name: sum(1 for e in events if e.get('event') == name)
    return {'pages': pages, 'first_try': sum(1 for f in finals if f == 'passed') if finals else 0,
            'rewrites': count('page_retry'), 'qa_rejections': count('qa_rejected'), 'fallbacks': count('fallback_page_created'),
            'kept_for_teacher': count('draft_kept_for_check'), 'json_rejections': count('model_response_rejected'),
            'seconds': seconds}


def total(rows):
    keys = ('pages', 'first_try', 'rewrites', 'qa_rejections', 'fallbacks', 'kept_for_teacher', 'json_rejections', 'seconds')
    value = {key: sum(r[key] for r in rows) for key in keys}
    pages = max(1, value['pages'])
    value.update(first_try_rate=round(value['first_try'] / pages, 3), rewrites_per_page=round(value['rewrites'] / pages, 3),
                 fallback_rate=round(value['fallbacks'] / pages, 3), seconds_per_page=round(value['seconds'] / pages, 1),
                 jobs=len(rows))
    return value


def verdict(old, new):
    """Plain recommendation: adopt only if pages pass more often, fallbacks do not grow, and it is not much slower."""
    better = new['first_try_rate'] > old['first_try_rate'] + 0.03
    safe = new['fallback_rate'] <= old['fallback_rate'] and new['json_rejections'] <= old['json_rejections'] * 1.2 + 1
    fast = new['seconds_per_page'] <= old['seconds_per_page'] * 1.15
    if better and safe and fast:
        return 'adopt', '建議採用：新模型一次通過的頁面比較多，待補頁沒有增加，速度也沒有明顯變慢。'
    reasons = ([] if better else ['一次通過率沒有明顯提升']) + ([] if safe else ['待補頁或 JSON 錯誤變多']) + ([] if fast else ['每頁慢了 15% 以上'])
    return 'keep', '先不要換：' + '、'.join(reasons) + '。'


def run_model(model, units, log=print):
    from workflow_v2.model_policy import configured_model
    from workflow_v2.pipeline import HANDLERS
    from .units import build_request, unit_id
    from workflow_v2.store import Store
    from .collect import variant
    tag = re.sub(r'[^A-Za-z0-9]+', '-', model).strip('-')
    store = Store(EVAL / tag)
    state_path = EVAL / tag / 'progress.json'
    state = read_json(state_path, {}) or {}
    rows = []
    for unit in units:
        key = unit_id(unit)
        entry = state.setdefault(key, {})
        if not entry.get('metrics'):
            difficulty, count = variant(key)
            request = build_request(unit, difficulty, count, configured_model())
            request.update(model=model, page_model=model)      # the model under test, for every stage
            entry['job'] = entry.get('job') or store.submit(request)
            out = store.folder(entry['job'])
            started = time.time()
            try:
                for stage in STAGES:
                    HANDLERS[stage](request, out)
            except Exception as exc:  # noqa: BLE001 - a failed unit counts against the model
                entry['error'] = str(exc)[:300]
            entry['metrics'] = job_metrics(out, round(time.time() - started))
            entry['metrics']['failed'] = bool(entry.get('error'))
            write_json(state_path, state)
            log(f'  {model}　{unit["title"]}：{entry["metrics"]["first_try"]}/{entry["metrics"]["pages"]} 頁一次通過')
        rows.append(entry['metrics'])
    return rows


def report_markdown(old_name, old, new_name, new, advice):
    lines = ['# 自我蒸餾：新舊模型比較', '', f'保留單元 {old["jobs"]} 個（訓練時沒看過），兩個模型跑同樣的單元、同樣的頁數與難度。', '',
             f'| | 舊：{old_name} | 新：{new_name} |', '|---|---|---|']
    for label, key, fmt in (('一次就通過品質檢查的頁面', 'first_try_rate', '{:.0%}'), ('每頁平均重寫次數', 'rewrites_per_page', '{:.2f}'),
                            ('改用待補提示頁的比例', 'fallback_rate', '{:.1%}'), ('保留待教師確認的頁數', 'kept_for_teacher', '{}'),
                            ('JSON 格式錯誤次數', 'json_rejections', '{}'), ('每頁秒數（規劃＋撰寫）', 'seconds_per_page', '{:.0f}')):
        lines.append(f'| {label} | {fmt.format(old[key])} | {fmt.format(new[key])} |')
    lines += ['', '**' + advice + '**', '', '要採用時，在 config.yaml 加上一行 `distilled_model: ' + new_name + '`，再重新開啟教材AI；'
              '刪掉那一行就恢復原本的模型。含圖片的工作（掃描頁辨識、最後檢查截圖）一律仍用原本的模型。']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='比較：保留單元上的新舊模型')
    parser.add_argument('new', help='新模型在 Ollama 裡的名稱，例如 qwen3.8:27b-teach-run-20261008-2200')
    parser.add_argument('--old', default=None, help='舊模型（預設 config.yaml 的 preferred_model）')
    parser.add_argument('--limit', type=int, default=8, help='比較幾個保留單元（預設 8）')
    args = parser.parse_args(argv)
    os.environ.pop('TEACHING_DISTILL_CAPTURE', None)       # comparison runs never feed the training data
    from workflow_v2.engine import ensure_server
    from workflow_v2.library import units as library_units
    from workflow_v2.model_policy import base_model
    old_name = args.old or base_model()
    units = held_out_units(library_units(), args.limit)
    if not units:
        raise SystemExit('教材庫裡沒有保留單元可以比較')
    ensure_server()
    print(f'比較 {len(units)} 個保留單元：{old_name} 對 {args.new}')
    old, new = total(run_model(old_name, units)), total(run_model(args.new, units))
    choice, advice = verdict(old, new)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M')
    write_json(REPORTS / f'compare-{stamp}.json', {'old': old_name, 'new': args.new, 'old_totals': old, 'new_totals': new, 'verdict': choice})
    text = report_markdown(old_name, old, args.new, new, advice)
    (REPORTS / f'compare-{stamp}.md').write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
