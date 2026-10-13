"""選出離線檢查發現問題的頁面供最後優化；報告缺失或頁數不符時檢查全份。"""
import json
import re
from pathlib import Path

# Findings the final pass can really fix by shortening or tidying text.
TRIM_CODES = {'long_sentence', 'too_long', 'wall_of_text', 'bad_break', 'truncated', 'residue', 'title_gap'}

# Cheap text lint on the finished slides: defects an offline rule cannot name but a reader notices.
LINT = (
    (re.compile(r'[，、；：]{2,}|。{2,}|？{2,}|！{2,}|[，、；：][。？！]'), '標點重複或排列不自然'),
    (re.compile(r'(?<![終由至關對屬位在])於[，。？！；、]|把[，。？！；、]'), '句子在中途結束'),
    (re.compile(r'([\u4e00-\u9fff]{3,}?)[？。，、；\s]*也就是\1'), '同一句話重複'),
    (re.compile(r'([\u4e00-\u9fffA-Za-z0-9]{5,}?)\1'), '文字連續重複'),
    (re.compile(r'\*\*|^#{1,4}\s|`{1,3}|\{\{|\}\}|TODO|待補|請補充|佔位'), '留有未清除的標記或佔位字'),
)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def lint(text):
    """Plain-Chinese reasons the text looks unfinished (empty when it looks fine)."""
    found = []
    for pattern, reason in LINT:
        if pattern.search(text or '') and reason not in found:
            found.append(reason)
    return found


def select(out, pages):
    """{page number: [reasons]} for pages worth a model pass, or None when every page must be checked."""
    out = Path(out)
    report = _read(out / 'qa-report.json')
    if not isinstance(report, dict) or not isinstance(report.get('pages'), dict) or len(report['pages']) != len(pages):
        return None                                   # cannot map the checks onto the slides: be thorough
    flags = {}

    def add(number, why):
        try:
            number = int(number)
        except (TypeError, ValueError):
            return
        if why not in flags.setdefault(number, []):
            flags[number].append(why)
    for key, page in report['pages'].items():
        if not isinstance(page, dict):
            continue
        if page.get('final') in ('warning', 'fallback'):
            add(key, '這頁有品質提醒或改用保底')
        for item in page.get('findings') or []:
            if not isinstance(item, dict) or item.get('code') == 'fixed':
                continue
            if item.get('severity') == 'major' or item.get('code') in TRIM_CODES:
                add(key, str(item.get('message') or item.get('code'))[:80])
    for name in ('teacher-checks.json', 'quality-warnings.json'):
        for key in (_read(out / name) or {}):
            add(key, '這頁需要老師確認')
    for item in (_read(out / 'deck-validation.json') or {}).get('findings') or []:
        if isinstance(item, dict):
            add(item.get('page'), str(item.get('message') or item.get('code'))[:80])
    for number in (_read(out / 'visual-qa.json') or {}).get('remaining_pages') or []:
        add(number, '版面檢查沒能完全修好')
    for page in pages:
        for text in page.get('text') or []:
            for reason in lint(text):
                add(page['page'], reason)
    return {number: why for number, why in flags.items() if 1 <= number <= len(pages)}
