"""修改既有投影片文字並重新匯出預覽；保留版面與動畫，失敗時還原備份。"""
import json
import shutil
import time
from pathlib import Path

from .runlog import log_event
from .store import Store, atomic

FOOTER_SHARE = .9     # text boxes below 90 % of the slide height are credits / page labels, not content


def _deck_path(out):
    return Path(out) / '教材.pptx'


def _walk(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes)


def _paragraphs(prs, page):
    """[(key, paragraph)] for every non-empty content paragraph on the page, in reading order."""
    slide = prs.slides[page - 1]
    found = []
    for shape in _walk(slide.shapes):
        if shape.top is not None and shape.top > prs.slide_height * FOOTER_SHARE:
            continue
        frames = []
        if shape.has_text_frame:
            frames.append(('text', shape.text_frame))
        if getattr(shape, 'has_table', False) and shape.has_table:
            for r, row in enumerate(shape.table.rows):
                for c, cell in enumerate(row.cells):
                    frames.append((f'cell-{r}-{c}', cell.text_frame))
        for cell, frame in frames:
            for p, paragraph in enumerate(frame.paragraphs):
                if paragraph.text.strip() and paragraph.runs:
                    found.append((f'{shape.shape_id}:{cell}:{p}', paragraph))
    return found


def page_count(out):
    from pptx import Presentation
    return len(Presentation(_deck_path(out)).slides)


def read_page(out, page):
    """{'texts': [{'key','text'}], 'notes': str} for one page (1-based)."""
    from pptx import Presentation
    prs = Presentation(_deck_path(out))
    if not 1 <= page <= len(prs.slides):
        raise ValueError('沒有這一頁')
    slide = prs.slides[page - 1]
    notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''
    return {'texts': [{'key': key, 'text': paragraph.text} for key, paragraph in _paragraphs(prs, page)], 'notes': notes}


def _set_text(paragraph, text):
    """Put the new wording in the first run (keeping its look) and empty the others."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def _replace_in(value, before, after):
    if isinstance(value, str):
        return value.replace(before, after) if before else value
    if isinstance(value, list):
        return [_replace_in(item, before, after) for item in value]
    if isinstance(value, dict):
        return {key: _replace_in(item, before, after) for key, item in value.items()}
    return value


def _notes_document(request, out, deck):
    """Rebuild 教師備課稿.docx from the deck (same layout as the publish step)."""
    from docx import Document
    from .text_safety import xml_text
    doc = Document()
    doc.add_heading(xml_text(request['unit'] + ' 教師備課稿'), 0)
    for number, slide in enumerate(deck['slides'], 1):
        doc.add_heading(xml_text(f"{number}. {slide['heading']}"), 1)
        doc.add_paragraph(xml_text(slide.get('speaker_notes', '')))
    credits = Path(out) / 'image-sources.json'
    if credits.exists():
        sources = json.loads(credits.read_text(encoding='utf-8'))
        if sources:
            doc.add_heading('圖片來源與授權', 1)
            for number, source in sorted(sources.items(), key=lambda x: int(x[0])):
                doc.add_paragraph(xml_text(f"第 {number} 頁｜{source['title']}｜{source['license']}｜{source['description_url']}｜{source['license_url']}"))
    doc.save(Path(out) / '教師備課稿.docx')


def save_page(job_id, page, texts, notes=None, store=None, export=None):
    """Apply {key: new text} (and new speaker notes) to one page. Returns {'changed', 'message'}.

    `export(request, out)` re-creates 教材.pdf and previews/ (pipeline.preview by default; replaceable in tests)."""
    from pptx import Presentation
    store = store or Store()
    row = store.get(job_id)
    if row['status'] != 'done':
        raise ValueError('只有已完成的教材可以直接編輯頁面')
    request = json.loads(row['request'])
    out = store.folder(job_id)
    deck_file = _deck_path(out)
    prs = Presentation(deck_file)
    if not 1 <= page <= len(prs.slides):
        raise ValueError('沒有這一頁')
    paragraphs = dict(_paragraphs(prs, page))
    changes = []
    for key, text in texts.items():
        text = ' '.join(str(text).splitlines()).strip()   # one paragraph is one line; keep full-width spaces as typed
        if key not in paragraphs:
            raise ValueError('這一頁的內容已經變動，請重新開啟再編輯')
        if not text:
            raise ValueError('文字不可以留空；不需要的段落請改成簡短說明')
        before = paragraphs[key].text
        if text != before.strip():
            _set_text(paragraphs[key], text)
            changes.append((before, text))
    slide = prs.slides[page - 1]
    old_notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''
    notes_changed = notes is not None and notes.strip() != old_notes.strip()
    if notes_changed:
        slide.notes_slide.notes_text_frame.text = notes.strip()
    if not changes and not notes_changed:
        return {'changed': False, 'message': '沒有任何修改'}
    backup = out / ('page-edit-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    keep = ['教材.pptx', '教材.pdf', '教師備課稿.docx', 'rendered-deck.json', 'final-optimized-deck.json', 'result.json']
    for name in keep:
        if (out / name).is_file():
            shutil.copy2(out / name, backup / name)
    if (out / 'previews').is_dir():
        shutil.copytree(out / 'previews', backup / 'previews')
    try:
        temporary = out / '教材.editing.pptx'
        prs.save(temporary)
        temporary.replace(deck_file)
        if export is None:
            from .pipeline import preview as export
        export(request, out)
        # keep the deck data, the teacher notes and the named downloads in step with the edited slides
        for name in ('final-optimized-deck.json', 'rendered-deck.json'):
            path = out / name
            if path.is_file():
                deck = json.loads(path.read_text(encoding='utf-8'))
                entry = deck['slides'][page - 1]
                for before, after in changes:
                    for field in ('heading', 'subheading', 'body', 'modules', 'hint', 'key_sentence', 'student_task', 'quiz', 'reading_context'):
                        if field in entry:
                            entry[field] = _replace_in(entry[field], before, after)
                if notes_changed:
                    entry['speaker_notes'] = notes.strip()
                atomic(path, deck)
        source = out / ('final-optimized-deck.json' if (out / 'final-optimized-deck.json').is_file() else 'rendered-deck.json')
        if source.is_file():
            _notes_document(request, out, json.loads(source.read_text(encoding='utf-8')))
        result_file = out / 'result.json'
        artifacts = json.loads(result_file.read_text(encoding='utf-8')).get('artifacts', {}) if result_file.is_file() else {}
        for kind, name in (('pptx', '教材.pptx'), ('pdf', '教材.pdf'), ('docx', '教師備課稿.docx'), ('json', source.name)):
            target = artifacts.get(kind)
            if target and (out / name).is_file() and Path(target).parent == out:
                shutil.copyfile(out / name, target)
    except Exception as exc:  # noqa: BLE001 - always put the previous deck back
        for name in keep:
            if (backup / name).is_file():
                shutil.copy2(backup / name, out / name)
        if (backup / 'previews').is_dir():
            shutil.rmtree(out / 'previews', ignore_errors=True)
            shutil.copytree(backup / 'previews', out / 'previews')
        log_event('page_edit_failed', job_id, root=store.root, page=page, error=str(exc)[:300])
        raise ValueError('這一頁沒有存成功，已還原原本的簡報：' + str(exc)[:160])
    log_event('page_edited', job_id, root=store.root, page=page, paragraphs=len(changes), notes=notes_changed)
    parts = ([f'{len(changes)} 段文字'] if changes else []) + (['講者備註'] if notes_changed else [])
    return {'changed': True, 'message': f'第 {page} 頁已更新（{"、".join(parts)}）；下載的簡報、PDF 與備課稿都是新版本。原本的檔案備份在 {backup.name}。'}
