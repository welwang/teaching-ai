"""匯出後檢查整份簡報，將內容與圖片來源問題寫入報告。"""
import re

from .age_bands import band_for, density_findings, projected_text
from . import originality

MAX_PAGES = 50
OPEN_LICENCES = ('cc by', 'cc by-sa', 'cc0', 'public domain')
CREATOR_REQUIRED = ('cc by', 'cc by-sa')
PLACEHOLDER = re.compile(r'(以下省略|見教師備註|見備註|TODO|待補|lorem ipsum)', re.I)
CODES = {
    'too_many_pages': '頁數超過 50 頁上限',
    'empty_heading': '標題是空的',
    'empty_slide': '這頁沒有可顯示的學生內容',
    'placeholder': '出現未完成的殘留字',
    'too_long': '正文過長',
    'heading_long': '標題過長',
    'no_notes': '缺少教師備註',
    'notes_no_timing': '備註沒有標示講解或停頓秒數',
    'duplicate_heading': '與上一頁標題重複',
    'cover_not_first': '第一頁不是封面',
    'summary_not_last': '最後一頁不是總結',
    'layout_run': '連續多頁使用相同版型',
    'image_no_credit': '圖片沒有來源與授權紀錄',
    'attribution_incomplete': '圖片的作者或授權資訊不完整',
    'malformed': '投影片資料格式異常',
    'verbatim_copy': '與主教材原文幾乎相同（請用自己的話改寫）',
    'close_paraphrase': '與主教材原文很接近，建議再改寫',
}


def _finding(page, code, severity, detail=''):
    message = CODES.get(code, code) + (('：' + detail) if detail else '')
    return {'page': page, 'code': code, 'severity': severity, 'message': message}


def _licence_family(name):
    name = (name or '').lower().strip()
    if name.startswith('cc by-sa'):
        return 'cc by-sa'
    if name.startswith('cc by'):
        return 'cc by'
    if name.startswith('cc0'):
        return 'cc0'
    if 'public domain' in name:
        return 'public domain'
    return ''


def check_attribution(number, source):
    """Findings for one picture's credit record (empty list when complete)."""
    if not source:
        return [_finding(number, 'image_no_credit', 'major')]
    if source.get('generated'):
        return []
    found = []
    family = _licence_family(source.get('license'))
    if not family:
        found.append(_finding(number, 'attribution_incomplete', 'major', '授權不是可重用的開放授權'))
    elif family in CREATOR_REQUIRED and not ((source.get('artist') or '').strip() or (source.get('attribution') or '').strip()):
        found.append(_finding(number, 'attribution_incomplete', 'major', '缺少作者（CC BY 必須標示）'))
    if not (source.get('description_url') or '').strip():
        found.append(_finding(number, 'attribution_incomplete', 'minor', '缺少原始頁面網址'))
    return found


def check_copy(number, slide, reference, memo):
    """Originality findings for one slide against the pages it cites ({page: text})."""
    pages = tuple(p for p in (slide.get('source_pages') or []) if reference.get(p))
    if not pages:
        return []
    if pages not in memo:
        memo[pages] = originality.Reference([reference[p] for p in pages])
    found = []
    for hit in originality.check_slide_copy(slide, memo[pages]):
        copied = hit['verdict'] == 'copied'
        detail = '%s 連續相同約 %d 字，相同比例 %d%%' % (hit['field'], hit['longest'], round(hit['share'] * 100))
        found.append(_finding(number, 'verbatim_copy' if copied else 'close_paraphrase', 'major' if copied else 'minor', detail))
    return found


def check_deck(deck, request, sources=None, media=None, reference=None):
    """Return {'pages','major','minor','findings'} for a rendered deck dict.

    ``reference`` ({source page number: text}) switches on the originality check.
    """
    slides = list((deck or {}).get('slides') or [])
    grade = request.get('grade', 6)
    findings = []
    memo = {}
    if len(slides) > MAX_PAGES:
        findings.append(_finding(0, 'too_many_pages', 'major', f'{len(slides)} 頁'))
    sources = sources or {}
    previous_heading = ''
    run = 1
    previous_layout = None
    for number, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            findings.append(_finding(number, 'malformed', 'major'))
            continue
        layout = slide.get('layout_id')
        heading = ''.join(str(slide.get('heading') or '').split())
        text = projected_text(slide)
        if not heading:
            findings.append(_finding(number, 'empty_heading', 'major'))
        if not text and layout not in ('Cover', 'Section', 'title_hero') and not slide.get('visual_model'):
            findings.append(_finding(number, 'empty_slide', 'major'))
        if PLACEHOLDER.search(' '.join(str(slide.get('heading') or '').split() + [text])):
            findings.append(_finding(number, 'placeholder', 'major'))
        for code, detail in density_findings(slide, grade):
            findings.append(_finding(number, code, 'minor', detail))
        if reference:
            findings.extend(check_copy(number, slide, reference, memo))
        notes = str(slide.get('speaker_notes') or '').strip()
        if not notes:
            findings.append(_finding(number, 'no_notes', 'minor'))
        elif '未經 AI 審核' not in notes and not re.search(r'\d+\s*秒|停\s*\d+|\d+\s*分', notes):
            findings.append(_finding(number, 'notes_no_timing', 'minor'))
        if heading and heading == previous_heading:
            findings.append(_finding(number, 'duplicate_heading', 'minor'))
        previous_heading = heading
        run = run + 1 if layout == previous_layout and layout not in ('Question', 'Steps', 'quiz_qa') else 1
        previous_layout = layout
        if run == 4:
            findings.append(_finding(number, 'layout_run', 'minor'))
    if slides:
        first, last = slides[0], slides[-1]
        if isinstance(first, dict) and first.get('layout_id') not in ('Cover', 'title_hero'):
            findings.append(_finding(1, 'cover_not_first', 'minor'))
        if isinstance(last, dict) and last.get('layout_id') not in ('Summary', 'summary_checklist') and len(slides) >= 8:
            findings.append(_finding(len(slides), 'summary_not_last', 'minor'))
    for number in sorted(int(k) for k in (media or {})):
        findings.extend(check_attribution(number, sources.get(str(number))))
    major = sum(1 for f in findings if f['severity'] == 'major')
    return {'schema_version': 1, 'pages': len(slides), 'band': band_for(grade)['label'],
            'major': major, 'minor': len(findings) - major, 'findings': findings,
            'pages_with_major': sorted({f['page'] for f in findings if f['severity'] == 'major' and f['page']})}