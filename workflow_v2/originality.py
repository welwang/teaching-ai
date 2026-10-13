"""以字元 n-gram 檢查教材重複內容；短引用依 QUOTE_MAX、QUOTE_TOTAL 限制。"""
import re
import unicodedata

QUOTE_MAX = 40          # one short quotation
QUOTE_TOTAL = 80        # all quotations on one slide
CJK_MATCH = 12          # shortest overlap that counts as copying (Chinese)
LATIN_MATCH = 30        # same, for English text (about six words)
# A field is "copied" when its longest copied run reaches RUN_* or the copied share reaches SHARE.
RUN_CJK = 30
RUN_LATIN = 70
SHARE = 0.5
SHARE_MIN_CHARS = 24
SHARE_MIN_LATIN = 60     # an English example sentence or two may repeat the book; a paragraph may not
# Below these it is only "close paraphrase" (reported, never blocks).
NEAR_RUN_CJK = 20
NEAR_RUN_LATIN = 45
NEAR_SHARE = 0.35

_QUOTE = re.compile(r'「([^」]*)」|『([^』]*)』|“([^”]*)”|"([^"]{1,%d})"' % QUOTE_MAX)
_KEEP = re.compile(r'[^0-9a-z\u3400-\u9fff]+')
_CJK = re.compile(r'[\u3400-\u9fff]')


def normalize(text):
    """Lower-case NFKC text with everything but letters, digits and CJK removed."""
    return _KEEP.sub('', unicodedata.normalize('NFKC', str(text or '')).lower())


def _is_cjk(text):
    return len(_CJK.findall(text)) >= max(4, len(text) * 0.3)


def strip_quotes(text):
    """Return (text without short quotations, characters allowed as quotation).

    Quotations longer than QUOTE_MAX, or beyond QUOTE_TOTAL for the slide, stay in the text and are measured.
    """
    allowed = 0

    def drop(match):
        nonlocal allowed
        inner = next((g for g in match.groups() if g is not None), '')
        size = len(normalize(inner))
        if size <= QUOTE_MAX and allowed + size <= QUOTE_TOTAL:
            allowed += size
            return ' '
        return inner

    return _QUOTE.sub(drop, str(text or '')), allowed


class Reference:
    """Pre-computed n-gram sets of the reference passages (build once per page, reuse for every field)."""

    def __init__(self, passages):
        self.texts = [normalize(p) for p in passages if p and str(p).strip()]
        self._grams = {}

    def grams(self, size):
        if size not in self._grams:
            found = set()
            for text in self.texts:
                for i in range(len(text) - size + 1):
                    found.add(text[i:i + size])
            self._grams[size] = found
        return self._grams[size]

    def __bool__(self):
        return any(self.texts)


def measure_text(text, reference):
    """{'chars','covered','longest','share'} of ``text`` against a Reference (quotations must be stripped first)."""
    norm = normalize(text)
    if not norm or not reference:
        return {'chars': len(norm), 'covered': 0, 'longest': 0, 'share': 0.0}
    size = CJK_MATCH if _is_cjk(norm) else LATIN_MATCH
    grams = reference.grams(size)
    mask = [False] * len(norm)
    for i in range(len(norm) - size + 1):
        if norm[i:i + size] in grams:
            for j in range(i, i + size):
                mask[j] = True
    longest = run = 0
    for flag in mask:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    covered = sum(mask)
    return {'chars': len(norm), 'covered': covered, 'longest': longest, 'share': round(covered / len(norm), 3)}


def judge(stats, cjk=True):
    """'copied' | 'near' | '' for one measured field."""
    run_limit = RUN_CJK if cjk else RUN_LATIN
    near_run = NEAR_RUN_CJK if cjk else NEAR_RUN_LATIN
    floor = SHARE_MIN_CHARS if cjk else SHARE_MIN_LATIN
    if stats['longest'] >= run_limit or (stats['share'] >= SHARE and stats['covered'] >= floor):
        return 'copied'
    if stats['longest'] >= near_run or (stats['share'] >= NEAR_SHARE and stats['covered'] >= floor // 2 + 4):
        return 'near'
    return ''


def slide_fields(slide):
    """(field, text) pairs a slide shows or carries: what students see plus the teacher notes."""
    from .qa import visible_fields
    fields = [(k, v) for k, v in visible_fields(slide) if k != 'heading']
    notes = str((slide or {}).get('speaker_notes') or '')
    if notes.strip():
        fields.append(('speaker_notes', notes))
    return fields


def check_slide_copy(slide, passages):
    """Findings-like dicts [{'field','verdict','longest','share','chars','sample'}] for fields that copy the source.

    ``passages`` are the texts of the cited source pages. Empty list = original enough (or nothing to compare).
    """
    reference = passages if isinstance(passages, Reference) else Reference(passages)
    if not reference:
        return []
    out = []
    budget = QUOTE_TOTAL
    for field, text in slide_fields(slide):
        stripped, used = strip_quotes(text)
        if used > budget:
            stripped = text
        else:
            budget -= used
        stats = measure_text(stripped, reference)
        verdict = judge(stats, _is_cjk(normalize(stripped)))
        if verdict:
            out.append(dict(stats, field=field, verdict=verdict, sample=' '.join(str(text).split())[:24]))
    return out


def slide_score(slide, passages):
    """One number per slide for reports: (longest copied run, copied share over all fields)."""
    reference = passages if isinstance(passages, Reference) else Reference(passages)
    if not reference:
        return 0, 0.0
    longest = covered = chars = 0
    for field, text in slide_fields(slide):
        if field == 'speaker_notes':
            continue
        stripped, _ = strip_quotes(text)
        stats = measure_text(stripped, reference)
        longest = max(longest, stats['longest'])
        covered += stats['covered']
        chars += stats['chars']
    return longest, round(covered / chars, 3) if chars else 0.0


def rewrite_advice(findings):
    """Chinese repair instruction for the writer."""
    fields = '、'.join(sorted({f['field'] for f in findings})[:4])
    longest = max((f['longest'] for f in findings), default=0)
    return ('本頁（' + fields + '）與主教材原文幾乎相同（最長連續相同約 ' + str(longest) + ' 字）。主教材只是參考：'
            '請先理解重點，再用你自己的話重新表達，改用新的情境、人物、數字或提問，並設計成適合該年級的活動；'
            '不可沿用教材句子。只有必要的定義或詩句可短引用（用「」標示、30字內）。')

WRITER_RULE = (
    '【原創表達原則】主教材只是參考資料，不是要貼進投影片的文字。先理解教材要教的概念、例題結構與重點，再用你自己的話為該年級學生重新設計：'
    '換成新的情境、人物或數字，加入提問、例子或小活動，把長句拆成短句。禁止逐字複製教材句子，也不要只換幾個字就貼上；'
    '任何連續約25字以上與教材相同的文字，系統會自動退回重寫。'
    '只有必要的定義、公式名稱、詩句或課文短句可以直接引用，必須用「」括起來、每處30字內，並在speaker_notes寫出出處頁碼；其餘都用自己的話。'
    '例題與練習題要改寫成原創題（概念與難度相同，但情境與數字不同），不可照抄課本題目與解答文字。')

def audit_job(folder):
    """Read-only overlap report for a finished job folder: {'pages','copied','near','share','rows'}."""
    import json
    from pathlib import Path
    folder = Path(folder)
    source = json.loads((folder / 'source.json').read_text(encoding='utf-8'))
    texts = {p['page']: p.get('text', '') for p in source.get('pages', [])}
    rows = []
    chars = covered = 0
    for number, path in enumerate(sorted((folder / 'slides').glob('*.json')), 1):
        slide = json.loads(path.read_text(encoding='utf-8'))
        reference = Reference([texts.get(p, '') for p in slide.get('source_pages', [])])
        hits = check_slide_copy(slide, reference)
        for field, text in slide_fields(slide):
            if field != 'speaker_notes':
                stats = measure_text(strip_quotes(text)[0], reference)
                chars += stats['chars']
                covered += stats['covered']
        longest, share = slide_score(slide, reference)
        verdict = 'copied' if any(h['verdict'] == 'copied' for h in hits) else 'near' if hits else ''
        rows.append({'page': number, 'heading': slide.get('heading', ''), 'longest': longest, 'share': share, 'verdict': verdict})
    return {'pages': len(rows), 'copied': sum(r['verdict'] == 'copied' for r in rows),
            'near': sum(r['verdict'] == 'near' for r in rows), 'share': round(covered / chars, 3) if chars else 0.0, 'rows': rows}


if __name__ == '__main__':
    import sys
    from pathlib import Path
    from .store import DATA
    for arg in sys.argv[1:]:
        folder = Path(arg)
        if not folder.is_dir():
            found = [p for sub in ('jobs', 'trash') for p in (Path(DATA) / sub).glob(arg + '*')]
            folder = found[0] if found else folder
        report = audit_job(folder)
        print(folder.name, '頁數', report['pages'], '照抄', report['copied'], '接近', report['near'], '相同比例', report['share'])
        for row in report['rows']:
            if row['verdict']:
                print('  第%d頁 %s 最長連續相同%d字 比例%s %s' % (row['page'], row['heading'], row['longest'], row['share'], row['verdict']))
