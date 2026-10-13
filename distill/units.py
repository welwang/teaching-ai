"""Library units → the same request the panel's 開始製作簡報 button makes (only what distillation needs)."""
import hashlib

DIFFICULTIES = ('全部', '低難度', '中難度', '高難度')


def unit_id(unit):
    """Stable id of a library unit (document, unit code, file)."""
    raw = f"{unit.get('document_id', '')}|{unit.get('unit_code', '')}|{unit.get('path', '')}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def build_request(unit, difficulty, slide_count, model):
    if difficulty not in DIFFICULTIES:
        raise ValueError('難度只能是：' + '、'.join(DIFFICULTIES))
    if type(slide_count) is not int or not 8 <= slide_count <= 50:
        raise ValueError('頁數要是 8～50 的整數')
    grade = int(unit['grade'])
    return dict(schema_version=1, grade=grade, semester=unit['semester'], subject=unit['subject'], unit=unit['title'],
                publisher=unit.get('publisher') or '', difficulty=difficulty, slide_count=slide_count, source_path=unit['path'],
                model=model, page_model=model, locale='zh-TW', audience='國小學童' if grade <= 6 else '國中學生',
                review_outline=False, online_cc0_images=False, ai_illustrations=False, include_worksheet=False)
