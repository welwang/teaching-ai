"""用已保存的內容重新排版並匯出；失敗時還原備份。
用法：python -m workflow_v2.restyle [工作編號]。"""
import json
import shutil
import sys
import time
from pathlib import Path

from .runlog import log_event
from .store import Store, atomic
from .template_styles import style_for

KEEP_FILES = ('教材.pptx', '教材.pdf', 'rendered-deck.json', 'layout.json', 'design.json', 'image-sources.json',
              'visual-assets.json', 'qa-report.json', 'deck-validation.json')


def design_mark(request):
    """What the current code would draw for this request: {'look','rev','band'}."""
    style = style_for(request.get('grade'), request.get('subject'))
    return {'look': style.get('look', 'story'), 'rev': style.get('rev', 0), 'band': style['band']}


def is_current(request, out):
    """True when the saved deck was drawn with the current design (decks made before design.json are not)."""
    try:
        saved = json.loads((Path(out) / 'design.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return saved == design_mark(request)


def can_restyle(row, out):
    out = Path(out)
    return (row.get('status') == 'done' and (out / 'plan.json').is_file() and (out / 'slides').is_dir()
            and any((out / 'slides').glob('*.json')) and (out / '教材.pptx').is_file())


def candidates(store=None):
    """Finished junior-high decks that still carry the old look: [(job id, unit)]."""
    store = store or Store()
    found = []
    for row in store.list():
        try:
            request = json.loads(row['request'])
        except (TypeError, ValueError):
            continue
        out = store.folder(row['id'])
        if style_for(request.get('grade'), request.get('subject')).get('look') == 'mission' \
                and can_restyle(row, out) and not is_current(request, out):
            found.append((row['id'], request.get('unit', '')))
    return found


def restyle(jid, store=None):
    """Re-draw one finished deck. Returns {'pages', 'backup', 'message'}; raises ValueError with a plain Chinese reason."""
    from . import pipeline
    store = store or Store()
    try:
        row = store.get(jid)
    except KeyError:
        raise ValueError('找不到這份教材')
    out = store.folder(jid)
    if not can_restyle(row, out):
        raise ValueError('只有已完成、且保留了各頁內容的教材可以套用新版面；其他教材請重新製作')
    request = json.loads(row['request'])
    backup = out / ('restyle-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    for name in KEEP_FILES:
        if (out / name).is_file():
            shutil.copy2(out / name, backup / name)
    if (out / 'previews').is_dir():
        shutil.copytree(out / 'previews', backup / 'previews')
    log_event('restyle_started', jid, root=store.root, message='開始套用新版面（不重寫內容）')
    try:
        pipeline.rendering(request, out)
        pipeline.preview_stage(request, out)
        atomic(out / 'design.json', design_mark(request))
    except Exception as exc:  # noqa: BLE001 - always put the old deck back
        for name in KEEP_FILES:
            if (backup / name).is_file():
                shutil.copy2(backup / name, out / name)
        if (backup / 'previews').is_dir():
            shutil.rmtree(out / 'previews', ignore_errors=True)
            shutil.copytree(backup / 'previews', out / 'previews')
        log_event('restyle_failed', jid, root=store.root, message='套用新版面沒有完成，已還原原本的簡報', error=str(exc)[:300])
        raise ValueError('套用新版面沒有完成，已還原原本的簡報：' + str(exc)[:120])
    pages = len(json.loads((out / 'rendered-deck.json').read_text(encoding='utf-8'))['slides'])
    log_event('restyle_finished', jid, root=store.root, message=f'已套用新版面，共 {pages} 頁')
    from .change_log import record
    from hashlib import sha256
    def mark(folder):
        return {name:sha256((folder/name).read_bytes()).hexdigest() for name in KEEP_FILES if (folder/name).exists()}
    record(out,'presentation_restyled',before=mark(backup),after=mark(out),actor='user',
           stage='render',reason='使用者套用新版面',backup=str(backup),pages=pages)
    return {'pages': pages, 'backup': str(backup),
            'message': f'已套用新版面，共 {pages} 頁；原本的簡報備份在 {backup.name}'}


if __name__ == '__main__':
    store = Store()
    if len(sys.argv) > 1:
        print(restyle(sys.argv[1], store)['message'])
    else:
        found = candidates(store)
        print('可以套用新版面的國中教材：' + (str(len(found)) + ' 份' if found else '沒有'))
        for jid, unit in found:
            print(' ', jid, unit)
