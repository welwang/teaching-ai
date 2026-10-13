"""Draws the blank page canvas (slide layouts, colours, fonts) in memory. There are no template files."""
import io,json,hashlib
from copy import deepcopy
from pptx import Presentation
from pptx.util import Inches,Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from .contracts import LAYOUTS
from .template_styles import theme,DESIGN_VERSION
from .template_design import layout_boxes,chrome

P='{http://schemas.openxmlformats.org/presentationml/2006/main}'

def native_panel(slide,box):
    x,y,w,h,fill,line=box
    shape=slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,*[Inches(v) for v in (x,y,w,h)])
    shape.fill.solid();shape.fill.fore_color.rgb=RGBColor.from_string(fill)
    if line:shape.line.color.rgb=RGBColor.from_string(line);shape.line.width=Pt(.8)
    else:shape.line.fill.background()
    inherited=shape._element.find(P+'style')
    if inherited is not None:shape._element.remove(inherited)
    return shape


def layout_map():
    """Which layout/placeholder serves which part of a page. Computed here, not read from a file."""
    return {name:{'layout_index':index,'heading':0,'main':1,'secondary':2} for index,name in enumerate(LAYOUTS)}


_MASTERS={}


def build_master(style=None):
    """Blank 16:9 deck whose slide layouts are drawn by code for this palette, as an in-memory file.

    Nothing is read from or written to disk: no template file of any kind, no cache folder. python-pptx's own
    empty-document skeleton is the only base, and every size, colour, font and shape is set below.
    """
    if not isinstance(style,dict):style=theme(None)
    key=str(DESIGN_VERSION)+':'+hashlib.sha256(json.dumps(style,sort_keys=True).encode()).hexdigest()[:12]
    if key in _MASTERS:return io.BytesIO(_MASTERS[key])
    p=Presentation();p.slide_width=Inches(13.333);p.slide_height=Inches(7.5)
    p.slide_master.background.fill.solid();p.slide_master.background.fill.fore_color.rgb=RGBColor.from_string(style['background'])
    sample=p.slides.add_slide(p.slide_layouts[6]);master=p.slide_master._element.find('.//'+P+'spTree')
    mode=style['style']
    identity=(0,0,.06,7.5,style['primary'],None) if mode=='diagram' else (0,0,13.333,.055 if mode=='practice' else .035,style['primary'],None)
    identities=[identity]
    if style.get('look')=='mission':
        identities=[(0,0,13.333,.03,style['accent'],None),(.93,6.93,11.47,.012,style['hairline'],None)]
    next_id=max(int(n.get('id')) for n in master.iter(P+'cNvPr'))+1
    for identity in identities:
        element=deepcopy(native_panel(sample,identity)._element)
        element.find('.//'+P+'cNvPr').set('id',str(next_id));next_id+=1;master.append(element)
    base=deepcopy(p.slide_layouts[3]._element.find(P+'cSld').find(P+'spTree'))
    mapping_value={}
    for index,name in enumerate(LAYOUTS):
        layout=p.slide_layouts[index];tree=layout._element.find(P+'cSld')
        old=tree.find(P+'spTree');new=deepcopy(base);tree.replace(old,new)
        layout.name=name
        next_id=max(int(n.get('id')) for n in new.iter(P+'cNvPr'))+1
        for box in chrome(name,style):
            source=native_panel(sample,box);element=deepcopy(source._element)
            element.find('.//'+P+'cNvPr').set('id',str(next_id));next_id+=1
            new.insert(2,element)
        mapping_value[name]={'layout_index':index,'heading':0,'main':1,'secondary':2}
    # Re-open the cloned layouts before consulting python-pptx's shape caches.
    sid=p.slides._sldIdLst[-1];p.part.drop_rel(sid.rId);p.slides._sldIdLst.remove(sid)
    partial=io.BytesIO();p.save(partial);partial.seek(0);p=Presentation(partial)
    for index,name in enumerate(LAYOUTS):
        layout=p.slide_layouts[index];boxes=layout_boxes(name,style)
        for ph in list(layout.placeholders):
            idx=ph.placeholder_format.idx
            if idx not in boxes:ph._element.getparent().remove(ph._element);continue
            ph.left,ph.top,ph.width,ph.height=[Inches(v) for v in boxes[idx]]
            tf=ph.text_frame;tf.word_wrap=True
            para=tf.paragraphs[0];para.font.name=style['font'];para.font.size=Pt(36 if idx==0 else 24 if style['grade']<=6 else 22)
            para.font.bold=idx==0;para.font.color.rgb=RGBColor.from_string(style['dark_ink'] if style.get('look')=='mission' and name in ('Cover','Section') else style['ink'])
            ph.name=name+(' title' if idx==0 else ' content' if idx==1 else ' visual / secondary')
    done=io.BytesIO();p.save(done);_MASTERS[key]=done.getvalue()
    return io.BytesIO(_MASTERS[key])
