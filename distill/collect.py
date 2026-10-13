"""執行教材規劃與編寫並保存模型請求；資料位於 data/distill/jobs。"""
import argparse
import hashlib
import os
import time
import traceback

from .common import CAPTURE, JOBS, WORK, held_out, read_json, write_json

STAGES = ('source', 'plan', 'write')
from .units import DIFFICULTIES
SLIDE_COUNTS = (10, 12, 15, 20)
PROGRESS = WORK / 'collect-progress.json'


def variant(unit_key):
    """Each unit gets one fixed difficulty and length, spread evenly over the choices."""
    number = int(hashlib.sha256(unit_key.encode('utf-8')).hexdigest(), 16)
    return DIFFICULTIES[number % len(DIFFICULTIES)], SLIDE_COUNTS[(number // 7) % len(SLIDE_COUNTS)]


def plan_units(units, limit, done, grades=None, subjects=None):
    """Training units in a stable order, skipping held-out and finished ones."""
    from .units import unit_id
    chosen = []
    for unit in sorted(units, key=lambda u: hashlib.sha256(unit_id(u).encode()).hexdigest()):
        key = unit_id(unit)
        if held_out(key) or done.get(key, {}).get('finished'):
            continue
        if grades and int(unit['grade']) not in grades:
            continue
        if subjects and unit['subject'] not in subjects:
            continue
        chosen.append(unit)
        if len(chosen) >= limit:
            break
    return chosen


def run_unit(unit, store, progress, log=print):
    from workflow_v2.model_policy import configured_model
    from workflow_v2.pipeline import HANDLERS
    from .units import build_request, unit_id
    key = unit_id(unit)
    entry = progress.setdefault(key, {'title': unit['title']})
    difficulty, count = variant(key)
    request = build_request(unit, difficulty, count, configured_model())
    if not entry.get('job'):
        entry['job'] = store.submit(request)
        write_json(PROGRESS, progress)
    out = store.folder(entry['job'])
    for stage in STAGES:
        if stage in entry.get('stages', []):
            continue
        started = time.time()
        HANDLERS[stage](request, out)
        entry.setdefault('stages', []).append(stage)
        entry.setdefault('seconds', {})[stage] = round(time.time() - started)
        write_json(PROGRESS, progress)
        log(f'  {stage} 完成（{entry["seconds"][stage]} 秒）')
    entry['finished'] = True
    write_json(PROGRESS, progress)


def main(argv=None):
    parser = argparse.ArgumentParser(description='蒐集：用教材庫單元跑到逐頁撰寫，記錄每一次模型請求')
    parser.add_argument('--limit', type=int, default=30, help='這次最多跑幾個單元（預設 30）')
    parser.add_argument('--grades', type=int, nargs='*', help='只跑這些年級，例如 --grades 5 6')
    parser.add_argument('--subjects', nargs='*', help='只跑這些科目，例如 --subjects 數學 英語')
    parser.add_argument('--dry-run', action='store_true', help='只列出會跑哪些單元')
    args = parser.parse_args(argv)
    from workflow_v2.library import units as library_units
    progress = read_json(PROGRESS, {}) or {}
    chosen = plan_units(library_units(), args.limit, progress, set(args.grades or []), set(args.subjects or []))
    print(f'教材庫可用的訓練單元這次排了 {len(chosen)} 個（已完成 {sum(1 for v in progress.values() if v.get("finished"))} 個）。')
    for unit in chosen:
        print(f'  {unit["grade"]} 年級 {unit["subject"]} {unit["semester"]}　{unit["title"]}')
    if args.dry_run or not chosen:
        return 0
    from workflow_v2.engine import ensure_server
    from workflow_v2.store import Store
    os.environ['TEACHING_DISTILL_CAPTURE'] = str(CAPTURE)
    ensure_server()
    store = Store(JOBS)
    failed = 0
    for number, unit in enumerate(chosen, 1):
        print(f'[{number}/{len(chosen)}] {unit["title"]}')
        try:
            run_unit(unit, store, progress)
        except KeyboardInterrupt:
            print('已停止；下次執行會從這個單元接著做。')
            return 130
        except Exception as exc:  # noqa: BLE001 - one bad unit must not stop a night's run
            failed += 1
            from .units import unit_id
            progress.setdefault(unit_id(unit), {})['error'] = str(exc)[:300]
            write_json(PROGRESS, progress)
            print('  沒有完成，略過：' + str(exc)[:160])
            with (WORK / 'collect-errors.log').open('a', encoding='utf-8') as handle:
                handle.write(traceback.format_exc() + '\n')
    print(f'完成。這次 {len(chosen) - failed} 個成功、{failed} 個略過。紀錄在 {CAPTURE}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
