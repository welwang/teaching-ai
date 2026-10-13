"""Bounded projection content; overflow never creates extra slides."""
import copy,json,re
from .design import route
from .textfit import font_size,Overflow
from .text_safety import format_teaching_text
from .visuals import model_caption

def visible_limit(request):
    return 80 if request.get('grade',6)<=6 else 110

def remember(page,label,original):
    page['speaker_notes']=page.get('speaker_notes','')+'\n【'+label+'】\n'+original

def prepare_deck(deck,request):
    """Move supplementary bullet items to notes as complete units, not slices.

    Task evidence, conditions, equations and numbered answers remain together.
    Larger indivisible tasks go through reflow, then an explicit teacher warning.
    """
    value=copy.deepcopy(deck);limit=visible_limit(request)
    for page in value['slides']:
        body=page['body'];parts=body.get('bullets') or []
        if route(page['layout_id']) not in ('Text_Visual','Summary','Cover') or not parts:continue
        selected=[];extra=[];used=0
        for text in parts:
            size=len(re.sub(r'\s','',text))
            if len(selected)<4 and used+size<=limit:selected.append(text);used+=size
            else:extra.append(text)
        # No sentence fragments: an oversized first idea still reaches reflow.
        if not selected:selected=[parts[0]];extra=parts[1:]
        if extra:
            body['bullets']=selected
            remember(page,'補充內容移至備註；原投影內容完整保留',json.dumps(parts,ensure_ascii=False))
    return value

def reflow_single_page(deck,index):
    """One full-width fallback, preserving the complete original in notes."""
    from .renderer import slide_text,plain_page
    value=copy.deepcopy(deck);page=value['slides'][index];original=copy.deepcopy(page)
    main,answer=slide_text(page)
    caption=model_caption(page.get('visual_model'))
    parts=[format_teaching_text(p) for p in (main,answer,caption) if p]
    content='\n\n'.join(parts)
    complete=True
    try:font_size(content,11.45,4.6,28,20)
    except Overflow:
        # A huge indivisible reading/task cannot become a tiny unreadable slide.
        # Keep complete sentences for orientation and flag the teacher action.
        units=re.split(r'(?<=[。！？!?])\s*|\n+',main)
        shown=[]
        for unit in units:
            if not unit.strip():continue
            try:font_size('\n'.join(shown+[unit]),11.45,3.4,28,20)
            except Overflow:break
            shown.append(unit)
        content=('\n'.join(shown)+'\n\n' if shown else '')+'本頁完整題目與詳解已保留於教師備註，請教師重新排版後使用。'
        complete=False
    page=plain_page(page);page['layout_id']='bullet_with_image';page['subheading']=''
    page['body']={'bullets':[content],'columns':[],'question':'','answer':'',
                  'code_snippet':{'language':'','code':''}}
    page['modules']=[];page['media_hint']={'search_keyword':'','image_description':''}
    if 'visual_asset' in page:page['visual_asset'].update(is_required=False,asset_type='none',image_prompt='')
    page['speaker_notes']=original.get('speaker_notes','')+'\n【單頁重新排版；未新增投影片】\n'+json.dumps(original,ensure_ascii=False)
    if not complete:page['speaker_notes']+='\n未經 AI 審核；本頁含超出投影容量的必要內容，需教師重新排版。'
    value['slides'][index]=page
    return value,complete
