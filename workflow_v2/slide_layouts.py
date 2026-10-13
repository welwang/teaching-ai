"""以原生圖形繪製教學頁面；文字無法容納時回報 Overflow。"""
import re
from pptx.util import Inches,Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN,MSO_ANCHOR
from .textfit import Overflow,estimated_lines,font_size
from .visual_draw import rect,write,label,blend,draw_model,FONT
from .design import route,STAGE_NAMES
from .text_safety import format_teaching_text

X0=.93;W=11.47;TOP=1.55;BOTTOM=6.85
NUM=re.compile(r'\d+(?:[.,]\d+)?(?:\s*[:：]\s*\d+(?:[.,]\d+)?)*(?:\s*/\s*\d+)?')

def hilite(style):return blend(style['accent'],'000000',.28)

def write_rich(shape,text,max_size,min_size,color,accent,bold=False,align=PP_ALIGN.LEFT,anchor=MSO_ANCHOR.TOP,pad=.12):
    """Text with numbers and ratios in bold accent colour; auto-fits or raises Overflow."""
    text=format_teaching_text(text).replace('**','')
    size=font_size(text,shape.width/914400-2*(pad-.07),shape.height/914400,max_size,min_size)
    tf=shape.text_frame;tf.clear();tf.word_wrap=True;tf.vertical_anchor=anchor
    tf.margin_left=tf.margin_right=Inches(pad);tf.margin_top=tf.margin_bottom=Inches(.05)
    for i,line in enumerate(text.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph();p.alignment=align
        p.space_after=Pt(6);p.line_spacing=1.12
        pos=0
        for m in NUM.finditer(line):
            for chunk,special in ((line[pos:m.start()],False),(m[0],True)):
                if not chunk:continue
                r=p.add_run();r.text=chunk;r.font.name=FONT;r.font.size=Pt(size)
                r.font.bold=bold or special;r.font.color.rgb=RGBColor.from_string(accent if special else color)
            pos=m.end()
        if pos<len(line) or not line:
            r=p.add_run();r.text=line[pos:];r.font.name=FONT;r.font.size=Pt(size)
            r.font.bold=bold;r.font.color.rgb=RGBColor.from_string(color)
    return size

def textbox(slide,x,y,w,h):
    return slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))

def panel(slide,x,y,w,h,fill,line=None,radius=.06,line_w=1.5,dash=False):
    return rect(slide,MSO_SHAPE.ROUNDED_RECTANGLE,x,y,w,h,fill=fill,line=line,line_w=line_w,radius=radius,dash=dash)

def chip(slide,x,y,w,h,text,fill,color='FFFFFF',size=18):
    shape=rect(slide,MSO_SHAPE.ROUNDED_RECTANGLE,x,y,w,h,fill=fill,radius=.5)
    return write(shape,text,size,color,True,floor=12,pad=.04)

def wrapped_height(text,width,size,line_gap=1.4,pad=.3,low=.7,high=2.4):
    lines=estimated_lines(format_teaching_text(text),max(.1,width-.25),size)
    return max(low,min(high,lines*size*line_gap/72+pad))

def stage_chips(slide,item,style,y=6.9):
    seq=item.get('stage_seq') or []
    if not seq:return
    x=X0;current=item.get('stage')
    for name in seq:
        label_text=STAGE_NAMES.get(name,name);active=(name==current)
        wchip=1.05 if len(label_text)<=2 else 1.3
        shape=rect(slide,MSO_SHAPE.ROUNDED_RECTANGLE,x,y,wchip,.34,
                   fill=style['primary'] if active else blend(style['pale'],'FFFFFF',.3),
                   line=None if active else blend(style['primary'],'FFFFFF',.55),line_w=1,radius=.5)
        write(shape,label_text,16,'FFFFFF' if active else blend(style['primary'],'FFFFFF',.15),active,floor=12,pad=.03)
        x+=wchip+.12

def answer_area(slide,x,y,w,h,style,label_text='作答區'):
    box=rect(slide,MSO_SHAPE.ROUNDED_RECTANGLE,x,y,w,h,fill='FFFFFF',line=style['primary'],line_w=2.5,dash=True,radius=.04)
    tag=chip(slide,x+.15,y+.12,1.55,.44,label_text,style['primary'],size=20)
    hint=label(slide,x+.15,y+h-.5,w-.3,.4,'在這裡寫下你的想法或算式',16,'8A8A8A',False,PP_ALIGN.LEFT,floor=12)
    return [tag]

def key_banner(slide,text,style,y=5.7,h=.9):
    box=panel(slide,X0,y,W,h,blend(style['primary'],'FFFFFF',.90),style['primary'],
              radius=.015 if style['style'] in ('diagram','focus') else .07,line_w=1.2)
    tag=rect(slide,MSO_SHAPE.ROUNDED_RECTANGLE,X0,y,.16,h,fill=style['accent'],radius=.3)
    size=font_size(format_teaching_text(text),W-.46,h,32,24)
    return write(box,text,size,style['primary'],True,PP_ALIGN.CENTER,floor=24,pad=.3)

def model_region(vm,box,slide,style):
    """Draw a visual model; returns the font sizes used (empty when there is none)."""
    return draw_model(slide,vm,box,style) if vm else []

def title_room(ph,narrow=False):
    ph.width=Inches(8.4 if narrow else 11.47)

def strip(slide,text,x,y,w,style,max_size=32,min_size=24,high=1.6,rich=True,bold=False,color=None):
    """A question/definition strip whose height follows its text."""
    size=font_size(format_teaching_text(text),w,high,max_size,min_size)
    h=wrapped_height(format_teaching_text(text),w,size,pad=.32,low=.85,high=high)
    box=textbox(slide,x,y,w,h)
    used=write_rich(box,text,max_size,min_size,color or style['ink'],hilite(style),bold)
    return used,h

def compose_question(slide,item,style,ph):
    """Question pages: question / think / hint / steps / answer stages (or Q&A beside a diagram)."""
    body=item['body'];stage=item.get('stage');vm=item.get('visual_model')
    sizes=[];question=body.get('question','');answer=body.get('answer','')
    for idx in (1,2):
        if idx in ph:ph[idx]._element.getparent().remove(ph[idx]._element)
    title_room(ph[0])
    compact=stage in ('hint','steps','answer')
    multi=bool(item.get('quiz'))
    question_high=(4.55 if stage=='question' and not vm else 2.4) if multi else (1.5 if compact else 2.1)
    if style['style']=='practice':
        panel(slide,X0,TOP-.05,W,question_high+.1,style['pale'],None,radius=.04)
    used,qh=strip(slide,question,X0,TOP,W,style,30 if compact or multi else 40,24,high=question_high,bold=not compact and not multi)
    sizes.append(used)
    y0=TOP+qh+.12;h=BOTTOM-y0
    if h<2.2 and not (multi and stage=='question' and not vm):
        raise Overflow('題目過長，無法保留作答與圖解空間')
    if stage=='question':
        secs=item.get('think_seconds')
        chip(slide,9.5,6.87,2.05,.4,'想一想'+(f' {secs}秒' if secs else ''),style['accent'],size=18)
    left_w=6.9 if vm else W
    if vm and style['style']=='diagram':left_w=7.15
    elif vm and style['style']=='practice':left_w=6.45
    right_x=X0+left_w+.25 if vm else X0
    right_w=W-left_w-.25 if vm else W
    if vm:sizes+=model_region(vm,(X0,y0,left_w,h),slide,style)
    if stage=='question' or (stage is None and not answer):
        if item.get('answer_area',True) and h>=1.25:answer_area(slide,right_x,y0,right_w,h,style)
    elif stage=='hint':
        panel(slide,right_x,y0,right_w,h,blend(style['accent'],'FFFFFF',.82),style['accent'],radius=.05,line_w=3)
        chip(slide,right_x+.15,y0+.12,1.25,.44,'提示',style['accent'],size=20)
        inner=textbox(slide,right_x+.1,y0+.62,right_w-.2,h-.72)
        sizes.append(write_rich(inner,item.get('hint') or '',36,24,style['ink'],hilite(style)))
    elif stage=='steps':
        steps=[t for t in answer.split('\n') if t.strip()]
        numbered='\n'.join(t if re.match(r'^\s*(?:\d+[.)、]|第)',t) else f'{i}. {t}' for i,t in enumerate(steps,1))
        panel(slide,right_x,y0,right_w,h,'FFFFFF',blend(style['primary'],'FFFFFF',.55),radius=.03)
        chip(slide,right_x+.15,y0+.12,1.25,.44,'解法',style['primary'],size=20)
        inner=textbox(slide,right_x+.1,y0+.62,right_w-.2,h-.72)
        sizes.append(write_rich(inner,numbered,32,24,style['ink'],hilite(style)))
    else:
        answer_start=len(slide.shapes)
        key=item.get('key_sentence','')
        gap=.15
        kh=.9 if key and h>=3.6 else 0
        ah=h-(kh+gap if kh else 0)
        panel(slide,right_x,y0,right_w,ah,blend(style['primary'],'FFFFFF',.86),style['primary'],radius=.05,line_w=3)
        chip(slide,right_x+.15,y0+.12,1.05 if stage else 1.4,.44,'答' if stage else '解法',style['primary'],size=20)
        inner=textbox(slide,right_x+.1,y0+.62,right_w-.2,ah-.72)
        big=48 if chars_of(answer)<=14 else 36
        sizes.append(write_rich(inner,answer,big,24,style['primary'],hilite(style),True,PP_ALIGN.CENTER,MSO_ANCHOR.MIDDLE))
        if kh:sizes.append(key_banner(slide,key,style,y0+ah+gap,kh))
        if stage is None and answer:
            from .animations import appear_answers
            appear_answers(slide,list(slide.shapes)[answer_start:])
    if stage:stage_chips(slide,item,style)
    return [s for s in sizes if s]

def chars_of(text):return len(re.sub(r'\s','',text or ''))

def steps_fit(modules,width,row_h):
    try:
        for m in modules:font_size(format_teaching_text(f"{m['keyword']}：{m['description']}"),width-1.05,row_h-.06,28,24)
        return True
    except Overflow:return False

def compose_steps(slide,item,style,ph):
    """Worked example: the complete problem on top, two or three steps below."""
    body=item['body'];vm=item.get('visual_model');sizes=[]
    for idx in (1,2):
        if idx in ph:ph[idx]._element.getparent().remove(ph[idx]._element)
    modules=item.get('modules') or []
    question=body.get('question','')
    text_w=W-1.35
    size=font_size(format_teaching_text(question),text_w,1.4,30,24)
    qh=wrapped_height(format_teaching_text(question),text_w,size,pad=.3,low=.85,high=1.4)
    panel(slide,X0,TOP-.03,W,qh+.06,blend(style['pale'],'FFFFFF',.35),style['primary'],radius=.08,line_w=1.5)
    chip(slide,X0+.12,TOP+(qh-.5)/2,1.1,.5,'題目',style['primary'],size=22)
    sizes.append(write_rich(textbox(slide,X0+1.35,TOP,text_w,qh),question,30,24,style['ink'],hilite(style),False,PP_ALIGN.LEFT,MSO_ANCHOR.MIDDLE))
    y0=TOP+qh+.25;h=BOTTOM-y0
    key=item.get('key_sentence','')
    if key:h-=1.0
    if h<2.3:raise Overflow('例題題目過長，無法保留三個步驟的空間')
    if not 2<=len(modules)<=6:raise Overflow('例題需要二至六個完整教學步驟')
    gap=.12;rh=(h-(len(modules)-1)*gap)/len(modules)
    cw=W
    if vm:
        cw=7.3
        if not steps_fit(modules,cw,rh):vm=None;cw=W   # the diagram yields to readable, traceable steps
    if not steps_fit(modules,cw,rh):raise Overflow('例題步驟文字過長，無法以 24pt 以上顯示')
    if vm:sizes+=model_region(vm,(X0+cw+.25,y0,W-cw-.25,h),slide,style)
    if not vm and style['style']=='practice':
        width=(W-(len(modules)-1)*.24)/len(modules)
        try:
            for m in modules:font_size(format_teaching_text(m['description']),width-.4,h-1.25,28,24)
        except Overflow:pass  # Long solutions keep their traceable vertical order.
        else:
            for i,m in enumerate(modules):
                x=X0+i*(width+.24)
                panel(slide,x,y0,width,h,style['pale'],None,radius=.04)
                chip(slide,x+.18,y0+.17,.65,.53,str(i+1+item.get('step_offset',0)),style['primary'],size=26)
                sizes.append(write_rich(textbox(slide,x+.93,y0+.17,width-1.11,.65),m['keyword'],26,24,style['primary'],hilite(style),True))
                sizes.append(write_rich(textbox(slide,x+.2,y0+1.03,width-.4,h-1.25),m['description'],28,24,style['ink'],hilite(style)))
            if key:sizes.append(key_banner(slide,key,style,BOTTOM-.88,.88))
            return sizes
    for i,m in enumerate(modules):
        ry=y0+i*(rh+gap)
        panel(slide,X0,ry,cw,rh,style['background'] if style['style']=='focus' else 'FFFFFF',
              blend(style['primary'],'FFFFFF',.65),radius=.01 if style['style'] in ('focus','diagram') else .05)
        badge=rect(slide,MSO_SHAPE.RECTANGLE if style['style']=='diagram' else MSO_SHAPE.OVAL,
                   X0+.15,ry+(rh-.6)/2,.6,.6,fill=style['primary'])
        write(badge,str(i+1+item.get('step_offset',0)),26,'FFFFFF',True,floor=20,pad=.02)
        box=textbox(slide,X0+.95,ry+.03,cw-1.05,rh-.06)
        sizes.append(write_rich(box,f"{m['keyword']}：{m['description']}",28,24,style['ink'],hilite(style),False,PP_ALIGN.LEFT,MSO_ANCHOR.MIDDLE))
    if key:sizes.append(key_banner(slide,key,style,BOTTOM-.88,.88))
    return sizes

def compose_diagram(slide,item,style,ph,kind,picture=False):
    """Concept / compare / summary pages: one line of text, a large diagram, an optional key sentence."""
    body=item['body'];vm=item.get('visual_model');sizes=[]
    for idx in (1,2):
        if idx in ph:ph[idx]._element.getparent().remove(ph[idx]._element)
    key=item.get('key_sentence','')
    if not key and kind=='Text_Visual' and item.get('modules'):
        key=item['modules'][0]['keyword']+'：'+item['modules'][0]['description']
    if kind=='Summary' and not key and body.get('bullets'):key=body['bullets'][0]
    if kind=='Two_Column':lead=item.get('subheading','')
    elif kind=='Summary':lead=''
    else:lead='\n'.join(body.get('bullets') or []) or item.get('subheading','')
    y=TOP
    if lead:
        used,lh=strip(slide,lead,X0,y,W,style,30,24,high=1.5)
        sizes.append(used);y+=lh+.1
    bottom=BOTTOM
    if key:bottom-=1.0
    if bottom-y<2.6:raise Overflow('文字過長，無法保留圖解空間')
    if vm:sizes+=model_region(vm,(X0,y,W,bottom-y),slide,style)
    if key:sizes.append(key_banner(slide,key,style,BOTTOM-.88,.88))
    ticket=body.get('question','') if kind=='Summary' else ''
    return sizes

ROLE_TAG={'情境頁':'情境','概念頁':'概念','比較頁':'比較','步驟頁':'步驟','練習頁':'練習','總結頁':'總結'}

def apply_role(slide,item,style):
    """Give each page role its own background tint and a small role chip."""
    role=item.get('page_role')
    if role not in ROLE_TAG:return
    p,a,bg=style['primary'],style['accent'],style['background']
    # Role badges must not erase the selected template's canvas identity.
    fill=slide.background.fill;fill.solid();fill.fore_color.rgb=RGBColor.from_string(bg)
    color={'情境頁':blend(a,'000000',.3),'練習頁':blend(a,'000000',.3)}.get(role,p)
    chip(slide,X0,.24,1.0,.34,ROLE_TAG[role],color,size=16)

def uses_special(item,kind,picture):
    body=item.get('body') or {}
    vm=item.get('visual_model')
    if kind=='Question':return bool(item.get('stage') or vm)
    if kind=='Steps':return bool(body.get('question','').strip())
    if kind=='Summary' and body.get('question'):return True
    if kind in ('Text_Visual','Two_Column','Summary'):return bool(vm) and not picture
    return False
