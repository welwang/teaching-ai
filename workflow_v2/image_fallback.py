"""Grounded diagram backups; missing photographs are explicitly recorded."""
import copy,json,re
from pathlib import Path
from . import qa
from .runlog import log_event
from .store import atomic
from .visuals import sanitize,model_numbers,model_text
from .source_reader import TEACHER_BLOCK,EDITOR_LINE

ENTITY_ALIASES={'ball':('球',),'box':('盒',),'cat':('貓',),'bird':('鳥',),
    'hippo':('hippopotamus','河馬'),'panda':('熊貓',),'desk':('桌',),'tree':('樹',)}

def grounded_entities(model,text):
    """A backup must depict the same entities/categories, not generic clip art."""
    if model['type']=='spatial_scene':terms=[model['object_label'],*model['references']]
    elif model['type']=='venn_diagram':
        terms=[model[side]['title'] for side in ('left','right')]+model.get('intersection',[])
        terms+=[item for side in ('left','right') for item in model[side]['items']]
    else:return True
    text=text.casefold()
    def present(term):
        options=(term,*ENTITY_ALIASES.get(term.casefold(),()))
        return any((bool(re.search(r'(?<![a-z])'+re.escape(t.casefold())+r'(?![a-z])',text))
                    if t.isascii() else t.casefold() in text) for t in options)
    return all(present(term) for term in terms)

def apply_missing_visuals(deck,out,media):
    out=Path(out);manifest=out/'visual-assets.json'
    try:records=json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError,ValueError):records={}
    for number,page in enumerate(deck['slides'],1):
        visual=page.get('visual_asset') or {}
        if number in media:continue
        previous=records.get(str(number),{})
        if page.get('visual_status')=='text_only':
            if previous.get('status')=='diagram_fallback':
                records[str(number)]={**previous,'status':'unavailable','reason':'圖解在可讀字級下無法容納，已保留分類文字，請教師補圖'}
            continue
        if not visual.get('is_required'):continue
        candidate,reason=sanitize(page.get('fallback_visual_model'),page['layout_id'])
        if candidate:
            trial=copy.deepcopy(page);trial['visual_model']=candidate
            text=qa.problem_text(page)+'\n'+page.get('speaker_notes','')
            # A fallback cannot inject new quantities just to make a pretty diagram.
            known={abs(n) for n in qa.numbers(text)}
            if any(abs(n) not in known for n in model_numbers(candidate)):
                reason='備援圖解包含本頁沒有支持的數據';candidate=None
            elif not grounded_entities(candidate,page.get('heading','')+'\n'+text):
                reason='備援圖解使用了本頁沒有支持的對象或分類';candidate=None
            elif TEACHER_BLOCK.search(model_text(candidate)) or EDITOR_LINE.search(model_text(candidate)):
                reason='備援圖解包含教師側欄文字';candidate=None
            elif qa.hard(qa.check_consistency(trial)):
                reason='備援圖解與本頁教學內容不一致';candidate=None
        if candidate:
            page['visual_model']=candidate;page['visual_status']='diagram_fallback'
            visual.update(is_required=False,asset_type='none',image_prompt='')
            page['speaker_notes']+='\n圖片未取得；已改用模型預先提供、與本頁資料一致的可編輯圖解。'
            records[str(number)]={**previous,'status':'diagram_fallback','model_type':candidate['type'],
                'teaching_purpose':visual.get('reasoning',''),'fallback_reason':previous.get('reason','')}
            log_event('image_diagram_fallback',out.name,stage='render',page=number,model_type=candidate['type'])
        else:
            # The text layout naturally uses the full width when no picture is
            # embedded. Do not insert unrelated stock art or claim completion.
            page['visual_status']='text_only'
            page['speaker_notes']+='\n指定的教學插圖尚未取得，請教師在使用前補圖或確認文字可獨立講解。'
            records[str(number)]={**previous,'status':'unavailable',
                'reason':previous.get('reason') or reason or '沒有可用的圖片來源或正確圖解',
                'teaching_purpose':visual.get('reasoning','')}
            log_event('image_text_fallback',out.name,stage='render',page=number,reason=records[str(number)]['reason'])
    if records:atomic(manifest,records)
    return deck
