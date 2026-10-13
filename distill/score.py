"""依正式流程的解析、格式、教學與品質規則檢查訓練回覆。"""
import copy
import json

from .common import page_index, read_json, task_of

FAIL = {'passed': False, 'hard': 99, 'major': 99, 'minor': 99, 'fixed': 0}


def _verdict(passed, reason='', hard=0, major=0, minor=0, fixed=0, chars=0):
    return {'passed': passed, 'reason': reason[:300], 'hard': hard, 'major': major, 'minor': minor, 'fixed': fixed, 'chars': chars}


def rank(verdict):
    """Smaller is better: passing first, then fewer problems, then shorter (classroom slides reward brevity)."""
    return (not verdict['passed'], verdict['hard'], verdict['major'], verdict['fixed'], verdict['minor'], verdict.get('chars', 0))


class Context:
    """Everything the checks need about one harvested job, loaded once."""

    def __init__(self, job_folder, request):
        from pathlib import Path
        self.out = Path(job_folder)
        self.request = request
        self.plan = read_json(self.out / 'plan.json', {})
        self.source = read_json(self.out / 'source.json', {})
        self.pages = {p['page'] for p in (self.source.get('pages') or [])}
        self._concepts = None

    def concepts(self):
        if self._concepts is None:
            from workflow_v2.pipeline import analysis_concepts
            self._concepts = analysis_concepts(self.out)
        return self._concepts


def judge(name, content, schema, context, done_reason=''):
    """Verdict for one reply (`content` is the raw text the model wrote)."""
    from workflow_v2.contracts import validate
    from workflow_v2.model import parse_complete_json
    task = task_of(name)
    chars = len(content or '')
    if done_reason == 'length':
        return _verdict(False, '輸出被截斷', **{k: FAIL[k] for k in ('hard', 'major', 'minor')}, chars=chars)
    try:
        raw = json.loads(content)              # trainable text must already be complete JSON (no bracket repair)
    except ValueError:
        try:
            parse_complete_json(content)
            return _verdict(False, 'JSON 結尾不完整（需要補括號）', 1, 1, chars=chars)
        except ValueError as exc:
            return _verdict(False, 'JSON 無法解析：' + str(exc), 99, 99, chars=chars)
    try:
        if task == 'page':
            return _judge_page(name, raw, schema, context, chars)
        if task == 'plan':
            from workflow_v2.pipeline import normalize_outline, outline_ready
            value = normalize_outline(copy.deepcopy(raw))
            validate(schema, value)
            outline_ready(value, context.request, context.pages)
            return _verdict(True, chars=chars)
        if task == 'analysis':
            from workflow_v2.pipeline import analysis_ready
            validate(schema, raw)
            analysis_ready(raw)
            return _verdict(True, chars=chars)
    except (ValueError, KeyError, TypeError) as exc:
        return _verdict(False, str(exc), 1, 1, chars=chars)
    return _verdict(False, '這類任務沒有離線評分', 99, 99, chars=chars)


def _judge_page(name, raw, schema, context, chars):
    from workflow_v2 import qa as quality
    from workflow_v2.contracts import validate, validate_slide
    from workflow_v2.pipeline import cited_sources, normalize_slide
    index = page_index(name)
    item = (context.plan.get('slides') or [])[index]
    slide = normalize_slide(copy.deepcopy(raw), item)
    validate(schema, slide)
    validate_slide(slide, item['source_pages'])
    if slide['layout_id'] != item['layout_id']:
        return _verdict(False, '單頁版型與規劃不符', 1, 1, chars=chars)
    fixed = len(quality.autofix(slide))
    findings = quality.check_slide(slide, item, context.request, context.concepts(), sources=cited_sources(context.out, item))
    hard, soft = quality.hard(findings), quality.soft(findings)
    minor = [f for f in findings if f['severity'] != 'major']
    problems = [f['code'] for f in hard + soft]
    passed = not hard and not soft and not fixed
    reason = '、'.join(problems) or ('需要自動修正' if fixed else '')
    return _verdict(passed, reason, len(hard), len(hard) + len(soft), len(minor), fixed, chars)
