"""統一投影片的字型、圖片裁切、頁碼與裝飾，不修改內容。"""
import copy
import re
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

from .design import default_role
from .template_styles import blend, contrast, FONT
from .text_safety import format_teaching_text
from .textfit import font_size, estimated_lines
from .visual_draw import rect, write

X0 = .93
W = 11.47
SLIDE_W = 13.333
SLIDE_H = 7.5

ROLE_ICON = {'情境頁': MSO_SHAPE.SUN, '概念頁': MSO_SHAPE.STAR_5_POINT, '比較頁': MSO_SHAPE.LEFT_RIGHT_ARROW,
             '步驟頁': MSO_SHAPE.CHEVRON, '練習頁': MSO_SHAPE.LIGHTNING_BOLT, '總結頁': MSO_SHAPE.WAVE}
CAPTION_INK = '4A5360'


def title_pt(style, heading):
    """Heading size follows the age band; longer headings step down by 8pt."""
    return style['title_max'] if len(heading) <= 12 else max(30, style['title_max'] - 8)


def cover_pt(style, heading):
    return style['title_max'] + 14 if len(heading) <= 12 else max(34, style['title_max'] - 2)


def role_of(item):
    return item.get('page_role') or default_role(item.get('layout_id', ''), item.get('phase', ''))


def cover_colors(style):
    """(title, intro, label) colours for cover and section pages; light on the near-black mission pages."""
    if style.get('look') == 'mission':
        return style['dark_ink'], style['dark_muted'], style['dark_accent']
    return style['primary'], style['ink'], style['primary']


def decorate(slide, item, style, kind, number, total, title=None):
    """Accent bar, role icon and page number. Every element sits in a reserved strip.
    The mission look (junior high) has no bar and no icon: thin lines and a plain page number only."""
    mission = style.get('look') == 'mission'
    if title is not None and not mission:
        left = title.left / 914400
        top = title.top / 914400
        bottom = top + title.height / 914400
        if kind in ('Cover', 'Section'):
            bar = (left + .07, max(.62, top - .16), 1.0, .07)
        else:
            bar = (left + .07, bottom - .03, 1.1, .045)
        rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, *bar, fill=style['accent'], radius=.5)
    icon = ROLE_ICON.get(role_of(item))
    if icon is not None and not mission:
        rect(slide, icon, SLIDE_W - X0 - .42, .17, .42, .42, fill=style['accent'])
    page_number(slide, number, total, style, kind in ('Cover', 'Section'))
    if kind == 'Cover':
        brand_mark(slide)


def brand_mark(slide):
    """Small logo at the cover's bottom-left, only when config.yaml slide_logo is 'cover' (default off)."""
    from . import brand
    path = brand.logo_path(192) if brand.slide_logo_mode() == 'cover' else None
    if not path:
        return None
    picture = slide.shapes.add_picture(str(path), Inches(X0), Inches(7.0), Inches(.36), Inches(.36))
    picture.name = '標誌'
    picture._element.nvPicPr.cNvPr.set('descr', '教材 AI 標誌')
    return picture


def page_number(slide, number, total, style, dark=False):
    if style.get('look') == 'mission':
        box = slide.shapes.add_textbox(Inches(11.2), Inches(7.0), Inches(1.2), Inches(.34))
        box.name = '頁碼'
        tf = box.text_frame
        tf.margin_top = tf.margin_bottom = Inches(.02)
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.RIGHT
        run = para.add_run()
        run.text = f'{number} / {total}'
        run.font.name = FONT
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor.from_string(style['dark_muted'] if dark else style['muted'])
        return box
    pill = rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 11.6, 7.02, .82, .32, fill=style['pale'], radius=.5)
    pill.name = '頁碼'
    write(pill, f'{number} / {total}', 12, style['primary'], True, floor=11, pad=.03)
    return pill


def credit_line(slide, text, style):
    """Picture credit: dark, 9-11pt, one line when possible, never outside the safe area."""
    text = format_teaching_text(re.sub(r'<[^>]+>', '', text))
    width = 10.0
    size = 9
    for candidate in (11, 10, 9):
        if estimated_lines(text, width - .2, candidate) == 1:
            size = candidate
            break
    lines = estimated_lines(text, width - .2, size)
    height = min(.42, .06 + lines * size * 1.3 / 72)
    box = slide.shapes.add_textbox(Inches(X0), Inches(min(7.04, SLIDE_H - .06 - height)), Inches(width), Inches(height))
    box.name = '圖片來源'
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = Inches(.02)
    para = tf.paragraphs[0]
    run = para.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(CAPTION_INK)
    return box


def place_picture(slide, path, box, style):
    """Fill the box with a centred crop when the shapes are alike, otherwise show the whole picture framed."""
    from PIL import Image
    x, y, w, h = box
    with Image.open(path) as image:
        iw, ih = image.size
    ratio_image = iw / ih
    ratio_box = w / h
    line = style['hairline'] if style.get('look') == 'mission' else blend(style['primary'], 'FFFFFF', .6)
    if abs(ratio_image / ratio_box - 1) <= .45:
        pic = slide.shapes.add_picture(str(path), x, y, w, h)
        if ratio_image > ratio_box:
            keep = ratio_box / ratio_image
            pic.crop_left = pic.crop_right = (1 - keep) / 2
        else:
            keep = ratio_image / ratio_box
            pic.crop_top = (1 - keep) * .35       # people and objects sit in the upper part of a photo
            pic.crop_bottom = (1 - keep) * .65
        frame = (x, y, w, h)
    else:
        panel = rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x / 914400, y / 914400, w / 914400, h / 914400,
                     fill=style['pale'], radius=.04)
        panel.name = '圖片底板'
        pad = int(.1 * 914400)
        scale = min((w - 2 * pad) / iw, (h - 2 * pad) / ih)
        pw, ph = int(iw * scale), int(ih * scale)
        pic = slide.shapes.add_picture(str(path), x + (w - pw) // 2, y + (h - ph) // 2, pw, ph)
        frame = (x, y, w, h)
    pic.name = '教學圖片'
    pic.auto_shape_type = MSO_SHAPE.ROUNDED_RECTANGLE
    geometry = pic._element.spPr.find(qn('a:prstGeom'))
    if geometry is not None:
        avlst = geometry.find(qn('a:avLst'))
        if avlst is None:
            avlst = geometry.makeelement(qn('a:avLst'), {})
            geometry.append(avlst)
        for old in list(avlst):
            avlst.remove(old)
        guide = avlst.makeelement(qn('a:gd'), {'name': 'adj', 'fmla': 'val 3500'})
        avlst.append(guide)
    pic.line.color.rgb = RGBColor.from_string(line)
    pic.line.width = Pt(.75 if style.get('look') == 'mission' else 1.5)
    return frame


def is_key_point(item, main, secondary, picture):
    """One short statement and nothing else: show it as a large quotation-style card."""
    if picture or secondary or item.get('visual_model'):
        return False
    return 4 <= len(main) <= 40 and '\n' not in main.strip()


def key_point(slide, placeholders, text, style):
    for idx in (1, 2):
        shape = placeholders.get(idx)
        if shape is not None and shape._element.getparent() is not None:
            shape._element.getparent().remove(shape._element)
    if style.get('look') == 'mission':
        panel = rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, X0, 2.05, W, 3.6, fill='FFFFFF', line=style['hairline'],
                     line_w=1, radius=.03)
        panel.name = '重點卡片'
        rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, X0, 2.05, .07, 3.6, fill=style['accent'], radius=.5)
        text = format_teaching_text(text)
        box = slide.shapes.add_textbox(Inches(X0 + .6), Inches(2.25), Inches(W - 1.2), Inches(3.2))
        size = font_size(text, W - 1.2, 3.2, 48, 32)
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.LEFT
        para.line_spacing = 1.15
        run = para.add_run()
        run.text = text.replace('**', '')
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.bold = True
        run.font.color.rgb = RGBColor.from_string(style['primary'])
        return size
    panel = rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, X0, 2.05, W, 3.6, fill='FFFFFF',
                 line=blend(style['primary'], 'FFFFFF', .7), line_w=1.5, radius=.05)
    panel.name = '重點卡片'
    rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, X0, 2.05, .2, 3.6, fill=style['accent'], radius=.5)
    mark = slide.shapes.add_textbox(Inches(X0 + .55), Inches(2.05), Inches(1.2), Inches(1.2))
    mark.name = '引號'
    para = mark.text_frame.paragraphs[0]
    run = para.add_run()
    run.text = '\u201c'
    run.font.name = FONT
    run.font.size = Pt(88)
    run.font.bold = True
    run.font.color.rgb = RGBColor.from_string(style['accent'])
    text = format_teaching_text(text)
    box = slide.shapes.add_textbox(Inches(X0 + .9), Inches(2.9), Inches(W - 1.8), Inches(2.4))
    size = font_size(text, W - 1.8, 2.4, 44, 30)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.LEFT
    para.line_spacing = 1.15
    run = para.add_run()
    run.text = text.replace('**', '')
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = True
    run.font.color.rgb = RGBColor.from_string(style['primary'])
    return size


RPR_ORDER = ['ln', 'noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill', 'grpFill', 'effectLst', 'effectDag',
             'highlight', 'uLnTx', 'uLn', 'uFillTx', 'uFill', 'latin', 'ea', 'cs', 'sym', 'hlinkClick',
             'hlinkMouseOver', 'rtl', 'extLst']


def _insert_ordered(rpr, child):
    name = child.tag.split('}')[1]
    rank = RPR_ORDER.index(name) if name in RPR_ORDER else len(RPR_ORDER)
    for position, existing in enumerate(list(rpr)):
        other = existing.tag.split('}')[1]
        if (RPR_ORDER.index(other) if other in RPR_ORDER else len(RPR_ORDER)) > rank:
            rpr.insert(position, child)
            return
    rpr.append(child)


def normalize_runs(slide):
    """Copy paragraph-level defaults onto each run and give CJK text its own font.

    python-pptx writes size/colour/bold into the paragraph defaults only; PowerPoint ignores them
    for existing runs, so the same file would look different from the LibreOffice preview.
    """
    changed = 0
    for para in slide._element.iter(qn('a:p')):
        ppr = para.find(qn('a:pPr'))
        default = ppr.find(qn('a:defRPr')) if ppr is not None else None
        for run in para.findall(qn('a:r')):
            rpr = run.find(qn('a:rPr'))
            if rpr is None:
                rpr = run.makeelement(qn('a:rPr'), {})
                run.insert(0, rpr)
            if default is not None:
                for key, value in default.attrib.items():
                    if key not in rpr.attrib:
                        rpr.set(key, value)
                for child in default:
                    if rpr.find(child.tag) is None:
                        _insert_ordered(rpr, copy.deepcopy(child))
            rpr.set('lang', 'zh-TW') if 'lang' not in rpr.attrib else None
            latin = rpr.find(qn('a:latin'))
            if latin is not None and rpr.find(qn('a:ea')) is None:
                _insert_ordered(rpr, rpr.makeelement(qn('a:ea'), {'typeface': latin.get('typeface')}))
            changed += 1
    return changed


def drop_empty_placeholders(slide):
    for shape in list(slide.placeholders):
        if shape.has_text_frame and not shape.text_frame.text.strip():
            shape._element.getparent().remove(shape._element)


def finish(slide):
    drop_empty_placeholders(slide)
    normalize_runs(slide)


def palette_report(style):
    """Contrast of every text/background pair the design uses (for tests and the report)."""
    pairs = {'ink-on-paper': (style['ink'], style['background']), 'title-on-paper': (style['primary'], style['background']),
             'white-on-primary': ('FFFFFF', style['primary']), 'white-on-accent': ('FFFFFF', style['accent']),
             'primary-on-pale': (style['primary'], style['pale']), 'accent-on-paper': (style['accent'], style['background'])}
    return {name: round(contrast(a, b), 2) for name, (a, b) in pairs.items()}
