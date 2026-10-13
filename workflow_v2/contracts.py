"""Versioned JSON contracts. Model grammar does not truncate natural language."""
import copy
from jsonschema import Draft202012Validator
from .visuals import VISUAL_MODEL

LAYOUTS=['Cover','Section','Text_Visual','Two_Column','Three_Cards','Steps','Question','Summary']
LEGACY_LAYOUTS=['title_hero','two_column_comparison','bullet_with_image','code_walkthrough','quiz_qa','summary_checklist']
PAGE_ROLES=['情境頁','概念頁','比較頁','步驟頁','練習頁','總結頁']
FUNCTIONS=['Hook','Concept','Example','Guided Practice','Practice','Review']
STEP_TYPES=['認識','判斷','計算','應用']
STAGE_KINDS=['question','hint','steps','answer']
PHASES=['hook','concept','misconception','example','recall','recap']
VISUAL_STYLE='flat vector illustration, educational, teal and warm orange palette, cream background, no text or numbers'
TEXT={'type':'string'}
TEXTS={'type':'array','items':TEXT}
def obj(properties,required=None):
    return {'type':'object','properties':properties,'required':required or list(properties),'additionalProperties':False}

REQUEST=obj({'schema_version':{'const':1},'grade':{'type':'integer','minimum':4,'maximum':9},
    'semester':{'enum':['上學期','下學期']},'subject':{'enum':['國語','數學','英語']},'unit':{'type':'string','minLength':1},
    'publisher':TEXT,'difficulty':{'enum':['低難度','中難度','高難度','全部']},
    'slide_count':{'type':'integer','minimum':8,'maximum':50},'source_path':TEXT,
    'model':{'type':'string','minLength':1},'page_model':{'type':'string','minLength':1},'locale':{'const':'zh-TW'},
    'audience':{'enum':['國小學童','國中學生','大學專題','企業內訓']},
    'review_outline':{'type':'boolean'},'online_cc0_images':{'type':'boolean'},'ai_illustrations':{'type':'boolean'},
    'teaching_prompt_override':TEXT,
    'template_style':{'enum':['自動','故事探索','圖解分析','互動練習','重點聚焦']},
    'include_worksheet':{'type':'boolean'}},
    required=['schema_version','grade','semester','subject','unit','publisher','difficulty',
        'slide_count','source_path','model','locale'])
OUTLINE_ITEM_REQUIRED=['layout_id','topic','phase','difficulty','source_pages']
OUTLINE_ITEM=obj({'layout_id':{'enum':LAYOUTS+LEGACY_LAYOUTS},'topic':TEXT,
    'phase':{'enum':PHASES},
    'difficulty':{'enum':['共用','低難度','中難度','高難度']},'source_pages':{'type':'array','minItems':1,'items':{'type':'integer'}},
    'function':{'enum':FUNCTIONS},'page_role':{'enum':PAGE_ROLES},'stage':{'enum':STEP_TYPES},
    'student_task':{'type':'string','maxLength':40},'misconception':{'type':'boolean'}},
    required=OUTLINE_ITEM_REQUIRED)
OUTLINE=obj({'objectives':{'type':'array','minItems':1,'maxItems':6,'items':TEXT},
    'slides':{'type':'array','items':OUTLINE_ITEM}})
ANALYSIS=obj({'objectives':{'type':'array','minItems':1,'maxItems':6,'items':{'type':'string','minLength':1,'maxLength':60}},
    'core_concepts':{'type':'array','minItems':1,'maxItems':8,'items':obj({'name':{'type':'string','minLength':1,'maxLength':20},
        'meaning':{'type':'string','maxLength':80}})},
    'worked_examples':{'type':'array','maxItems':6,'items':obj({'problem':{'type':'string','minLength':1,'maxLength':200},
        'solution':{'type':'string','maxLength':240},'source_pages':{'type':'array','items':{'type':'integer'}}},
        required=['problem','solution'])},
    'practice_questions':{'type':'array','maxItems':8,'items':obj({'question':{'type':'string','minLength':1,'maxLength':200},
        'answer':{'type':'string','maxLength':120},'source_pages':{'type':'array','items':{'type':'integer'}}},
        required=['question','answer'])},
    'misconceptions':{'type':'array','maxItems':5,'items':obj({'wrong':{'type':'string','minLength':1,'maxLength':100},
        'why_wrong':{'type':'string','maxLength':100},'correct':{'type':'string','maxLength':100}})},
    'life_scenarios':{'type':'array','maxItems':5,'items':obj({'scene':{'type':'string','minLength':1,'maxLength':80},
        'quick_question':{'type':'string','maxLength':60}})}})
MODULE=obj({'keyword':{'type':'string','minLength':1,'maxLength':5},
    'description':{'type':'string','minLength':1,'maxLength':90},
    'visual_hint':{'type':'string','maxLength':160}},required=['keyword','description'])
VISUAL_ASSET=obj({'is_required':{'type':'boolean'},
    'reasoning':{'type':'string','maxLength':100},
    'asset_type':{'enum':['illustration','none']},
    'image_prompt':{'type':'string','maxLength':300},
    'style_tags':{'const':VISUAL_STYLE}})
BODY=obj({'bullets':TEXTS,'columns':{'type':'array','items':obj({'header':TEXT,'points':TEXTS})},
    'question':TEXT,'answer':TEXT,'code_snippet':obj({'language':TEXT,'code':TEXT})})
QUIZ=obj({'questions':{'type':'array','minItems':1,'maxItems':6,'items':obj({
    'id':{'type':'integer','minimum':1,'maximum':6},'question':{'type':'string','minLength':1}})},
    'answers':{'type':'array','minItems':1,'maxItems':6,'items':obj({
    'id':{'type':'integer','minimum':1,'maximum':6},'answer':{'type':'string','minLength':1}})}})
SLIDE=obj({'layout_id':{'enum':LAYOUTS+LEGACY_LAYOUTS},'heading':TEXT,'subheading':TEXT,'body':BODY,
    'quiz':QUIZ,'reading_context':{'type':'string','maxLength':3000},
    'modules':{'type':'array','maxItems':6,'items':MODULE},
    'visual_asset':VISUAL_ASSET,
    'media_hint':obj({'search_keyword':TEXT,'image_description':TEXT}),
    'speaker_notes':TEXT,'source_pages':{'type':'array','minItems':1,'items':{'type':'integer'}},
    'page_role':{'enum':PAGE_ROLES},'student_task':{'type':'string','maxLength':40},
    'hint':{'type':'string','maxLength':60},'key_sentence':{'type':'string','maxLength':45},
    'think_seconds':{'type':'integer','minimum':0,'maximum':120},'visual_model':VISUAL_MODEL,
    'fallback_visual_model':VISUAL_MODEL,'visual_status':{'enum':['diagram_fallback','text_only']},
    'stage':{'enum':STAGE_KINDS},'misconception':{'type':'boolean'},'answer_area':{'type':'boolean'},
    'step_offset':{'type':'integer','minimum':0},
    'continuation':obj({'part':{'type':'integer','minimum':1},'total':{'type':'integer','minimum':1}}),
    'staged_from':{'type':'integer','minimum':0},'stage_step':{'type':'integer','minimum':1},
    'stage_total':{'type':'integer','minimum':1},'stage_seq':{'type':'array','items':{'enum':STAGE_KINDS}}},
    required=['layout_id','heading','subheading','body','media_hint','speaker_notes','source_pages'])
# Diagrams are optional. Normalization removes {"type":"none"}; requiring
# visual_model here would reject valid text/cover pages after normalization.
STRICT_SLIDE_REQUIRED=['student_task']
SLIDE['allOf']=[]
for _layout in LAYOUTS:
    _modules={'minItems':3,'maxItems':3} if _layout=='Three_Cards' else {'minItems':2,'maxItems':6} if _layout=='Steps' else (
        {'minItems':1,'maxItems':1} if _layout in ('Section','Text_Visual') else {'maxItems':0})
    _body={}
    if _layout in ('Cover','Section','Three_Cards','Steps','Two_Column','Question'):_body['bullets']={'maxItems':0}
    if _layout=='Two_Column':_body['columns']={'minItems':2,'maxItems':2}
    if _layout=='Question':
        _body.update(question={'minLength':1},columns={'maxItems':0})
    if _layout in ('Text_Visual','Summary'):_body['bullets']={'minItems':1}
    SLIDE['allOf'].append({'if':{'properties':{'layout_id':{'const':_layout}}},'then':{
        'required':['modules','visual_asset'],'properties':{'heading':{'maxLength':60},
        'subheading':{'maxLength':60},'modules':_modules,'body':{'properties':_body}}}})
DECK=obj({'schema_version':{'const':1},'deck_meta':obj({'title':TEXT,'subject':TEXT,'target_audience':TEXT,
    'primary_color':{'type':'string','pattern':'^#[0-9A-Fa-f]{6}$'},
    'template_id':TEXT,'grade':{'type':'integer','minimum':1,'maximum':9}},required=['title','subject','target_audience','primary_color']),
    'slides':{'type':'array','minItems':8,'items':SLIDE}})
REVIEW=obj({'passed':{'type':'boolean'},'issues':TEXTS})
WORKSHEET_ITEM=obj({'difficulty':{'enum':['低難度','中難度','高難度']},
    'question':{'type':'string','minLength':5,'maxLength':350},
    'answer':{'type':'string','minLength':1,'maxLength':180},
    'explanation':{'type':'string','minLength':5,'maxLength':400},
    'source_pages':{'type':'array','minItems':1,'maxItems':3,'uniqueItems':True,
                    'items':{'type':'integer','minimum':1}}})
WORKSHEET=obj({'instructions':{'type':'string','minLength':5,'maxLength':220},
    'questions':{'type':'array','minItems':6,'maxItems':9,'items':WORKSHEET_ITEM}})
RESULT=obj({'job_id':TEXT,'status':{'enum':['pending','running','rendering','reviewing','repairing','awaiting_outline','paused','pausing','removing','done','failed']},
    'stage':TEXT,'artifacts':{'type':'object','additionalProperties':TEXT},'error':TEXT,'model':TEXT,
    'quality':{'enum':['ai_reviewed_draft','unverified_draft','visual_incomplete']},
    'final_optimization_status':{'enum':['completed','partial','unavailable','skipped']},
    'qa_summary':{'type':'object'},'qa_warning_pages':{'type':'array','items':{'type':'integer','minimum':1}},
    'fallback_pages':{'type':'array','items':{'type':'integer','minimum':1}},
    'missing_image_pages':{'type':'array','items':{'type':'integer','minimum':1}},
    'worksheet_status':{'enum':['not_requested','done','failed']},'worksheet_error':TEXT,
    'deck_validation':{'type':'object'}},
    required=['job_id','status','stage','artifacts','error','model'])

def validate(schema,value):
    errors=sorted(Draft202012Validator(schema).iter_errors(value),key=lambda e:str(list(e.path)))
    if errors:raise ValueError('; '.join('/'.join(map(str,e.path))+': '+e.message for e in errors[:5]))
    return value

def outline_schema(count,pages,new_only=False):
    schema=copy.deepcopy(OUTLINE)
    schema['properties']['slides'].update(minItems=count,maxItems=count)
    item=schema['properties']['slides']['items']['properties']
    if new_only:item['layout_id']={'enum':LAYOUTS}
    item['source_pages']['items']['enum']=sorted(pages)
    item['source_pages']['maxItems']=3
    item['source_pages']['uniqueItems']=True
    item['topic']={'type':'string','maxLength':70}
    if new_only:
        # Newly generated outlines must carry the teaching-design fields.
        schema['properties']['slides']['items']['required']=OUTLINE_ITEM_REQUIRED+[
            'function','page_role','stage','student_task','misconception']
    return schema

def slide_schema(pages,layout_id=None,strict=False,grade=None):
    schema=copy.deepcopy(SLIDE)
    if strict:schema['required']=schema['required']+STRICT_SLIDE_REQUIRED
    schema['properties']['source_pages']['items']['enum']=sorted(pages)
    if layout_id:
        if layout_id not in LAYOUTS+LEGACY_LAYOUTS:raise ValueError('未知投影片版型')
        schema['properties']['layout_id']={'const':layout_id}
        if strict:schema['properties']['student_task']={'type':'string','minLength':1,'maxLength':40}
        body=schema['properties']['body']['properties']
        # TEXTS is reused in the common schema; detach bullets before adding
        # layout-specific limits so column points stay unrestricted.
        body['bullets']=copy.deepcopy(body['bullets'])
        if layout_id in LAYOUTS:
            schema['properties']['heading']={'type':'string','minLength':1,'maxLength':60}
            schema['properties']['subheading']={'type':'string','maxLength':60}
            schema['required'].append('modules')
            schema['required'].append('visual_asset')
            if layout_id in ('Three_Cards','Steps'):
                schema['properties']['modules'].update(minItems=2 if layout_id=='Steps' else 3,
                    maxItems=6 if layout_id=='Steps' else 3)
                body['bullets']['maxItems']=0
            elif layout_id in ('Text_Visual','Two_Column','Section'):
                schema['properties']['modules']['minItems']=0 if layout_id=='Two_Column' else 1
                schema['properties']['modules']['maxItems']=0 if layout_id=='Two_Column' else 1
            elif layout_id in ('Cover','Question','Summary'):
                schema['properties']['modules']['maxItems']=0
            if layout_id in ('Cover','Section'):body['bullets']['maxItems']=0
            if layout_id=='Steps' and strict:body['question']={'type':'string','minLength':1}
        if layout_id in ('quiz_qa','Question'):
            body['question']={'type':'string','minLength':1}
            body['answer']={'type':'string','minLength':1}

            body['columns']['maxItems']=0
            if layout_id=='Question':body['bullets']['maxItems']=0
        elif layout_id in ('two_column_comparison','Two_Column'):
            body['columns'].update(minItems=2,maxItems=2)
            if layout_id=='Two_Column':body['bullets']['maxItems']=0
        elif layout_id=='code_walkthrough':
            body['code_snippet']['properties']['code']={'type':'string','minLength':1}
        elif layout_id in ('bullet_with_image','summary_checklist','Text_Visual','Summary'):
            body['bullets']['minItems']=1
    if grade is not None:
        cap=80 if grade<=6 else 110
        body=schema['properties']['body']['properties']
        body['bullets']=copy.deepcopy(body['bullets'])
        body['bullets']['maxItems']=min(body['bullets'].get('maxItems',4),4)
        body['bullets']['items']={'type':'string','maxLength':cap}
        module=schema['properties']['modules']['items']['properties']
        module['description']['maxLength']=min(module['description']['maxLength'],50 if grade<=6 else 70)
        # Do not cut reading evidence or task conditions to meet a character
        # count. The renderer handles indivisible tasks without adding pages.
    return schema

def validate_slide(slide,pages):
    validate(slide_schema(pages),slide)
    if slide.get('quiz'):
        quiz=slide['quiz'];qids=[q['id'] for q in quiz['questions']];aids=[a['id'] for a in quiz['answers']]
        if len(set(qids))!=len(qids) or len(set(aids))!=len(aids) or set(qids)!=set(aids):
            raise ValueError('測驗題號重複或題目與答案缺漏，必須按id一一對應')
    if not slide['heading'].strip() or not slide['speaker_notes'].strip():raise ValueError('標題與講者備註不得空白')
    body=slide['body'];layout=slide['layout_id']
    if layout in LAYOUTS:validate(slide_schema(pages,layout),slide)
    visual=slide.get('visual_asset')
    if visual:
        required=visual['is_required']
        if required and layout not in ('Cover','Text_Visual','Section','Three_Cards'):
            raise ValueError('此版型沒有安全的插圖區，請將視覺決策改為不需插圖')
        if required and (visual['asset_type']!='illustration' or not visual['image_prompt'].strip()):
            raise ValueError('需要插圖時須提供具體英文畫面描述')
        if not required and (visual['asset_type']!='none' or visual['image_prompt'].strip()):
            raise ValueError('不需插圖時不得產生圖片任務')
        if any(char.isdigit() for char in visual['image_prompt']) or not visual['image_prompt'].isascii():
            raise ValueError('插圖描述只能使用英文且不得包含數字')
    if layout in ('two_column_comparison','Two_Column') and len(body['columns'])!=2:raise ValueError('比較頁需要兩欄')
    if layout in ('quiz_qa','Question') and (not body['question'].strip() or (not body['answer'].strip() and not slide.get('stage'))):raise ValueError('測驗需完整題目與解答')
    if layout=='code_walkthrough' and not body['code_snippet']['code'].strip():raise ValueError('步驟頁缺少演算內容')
    if layout in ('bullet_with_image','summary_checklist','Text_Visual','Summary') and not body['bullets']:raise ValueError('內容頁缺少重點')
    if any(text.rstrip().endswith(('=','×','÷','+','所以，','因此，')) for text in body['bullets']+[body['answer']]):
        raise ValueError('算式或結論未完成，請寫完，不要裁切')
    return slide
