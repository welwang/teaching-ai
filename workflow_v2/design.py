"""Teaching-design vocabulary, page roles and the staged-reveal expansion (no I/O)."""
import copy,re
VISUAL_STYLE='flat vector illustration, educational, teal and warm orange palette, cream background, no text or numbers'

PAGE_ROLES=['情境頁','概念頁','比較頁','步驟頁','練習頁','總結頁']
FUNCTIONS=['Hook','Concept','Example','Guided Practice','Practice','Review']
STEP_TYPES=['認識','判斷','計算','應用']
STAGE_KINDS=['question','hint','steps','answer']
PHASES=['hook','concept','misconception','example','recall','recap']
FUNCTION_PHASE={'Hook':'hook','Concept':'concept','Example':'example',
                'Guided Practice':'recall','Practice':'recall','Review':'recap'}
PHASE_FUNCTION={'hook':'Hook','concept':'Concept','misconception':'Guided Practice',
                'example':'Example','recall':'Practice','recap':'Review'}
PHASE_STAGE={'hook':'認識','concept':'認識','misconception':'判斷','example':'計算','recall':'應用','recap':'應用'}
ROLE_LAYOUTS={'情境頁':('Question','Text_Visual','Section'),'概念頁':('Text_Visual','Three_Cards','Section'),
              '比較頁':('Two_Column',),'步驟頁':('Steps',),'練習頁':('Question',),'總結頁':('Summary',)}
ROLE_SHORT={'情境頁':'情境','概念頁':'概念','比較頁':'比較','步驟頁':'步驟','練習頁':'練習','總結頁':'總結'}
LEGACY_ROUTE={'title_hero':'Cover','two_column_comparison':'Two_Column','bullet_with_image':'Text_Visual',
              'code_walkthrough':'Steps','quiz_qa':'Question','summary_checklist':'Summary'}
# When a layout would repeat three times in a row, this is the substitute.
LAYOUT_ALTERNATIVES={'Text_Visual':('Three_Cards','Two_Column'),'Three_Cards':('Text_Visual','Two_Column'),
                     'Two_Column':('Text_Visual','Three_Cards'),'Steps':('Text_Visual',),
                     'Question':('Steps','Text_Visual'),'Section':('Text_Visual',),'Summary':(),'Cover':()}
LAYOUT_ROLE={'Three_Cards':'概念頁','Text_Visual':'概念頁','Two_Column':'比較頁','Steps':'步驟頁',
             'Question':'練習頁','Summary':'總結頁','Section':'概念頁','Cover':'情境頁'}
LAYOUT_PHASE={'Three_Cards':'concept','Text_Visual':'concept','Two_Column':'concept','Steps':'example'}

def route(layout):return LEGACY_ROUTE.get(layout,layout)

def default_role(layout,phase):
    kind=route(layout)
    if kind=='Cover' or phase=='hook':return '情境頁'
    if phase=='misconception' or kind=='Two_Column':return '比較頁'
    if kind=='Steps' or phase=='example':return '步驟頁'
    if kind=='Question' or phase=='recall':return '練習頁'
    if kind=='Summary' or phase=='recap':return '總結頁'
    return '概念頁'

def item_role(item):return item.get('page_role') or default_role(item.get('layout_id',''),item.get('phase',''))

def split_answer(answer):
    """(steps, final): everything before the last sentence is a step; the last is the answer."""
    text=(answer or '').strip()
    pieces=[p.strip() for p in re.split(r'\n+',text) if p.strip()]
    if len(pieces)==1:
        pieces=[p.strip() for p in re.split(r'(?<=[。；;！!])',pieces[0]) if p.strip()]
    if not pieces:return [],''
    return pieces[:-1],pieces[-1]

def _note(stage,slide,think,hint,final):
    if stage=='question':
        return f'【題目・思考時間】停 {think} 秒，請學生在作答區自己想、自己寫；先不要公布提示或答案。'
    if stage=='hint':
        return '【提示】請學生用提示再試一次，找兩位同學說想法。提示：'+hint
    if stage=='steps':
        return '【解法步驟】逐步帶學生檢查每個數字是從題目或上一步哪裡來的。'
    return '【解答】請學生先說出自己的答案再核對。答案：'+final

def _leaks(slide,final):
    """True when the diagram already shows a number that only the answer contains."""
    from .visuals import model_numbers
    vm=slide.get('visual_model')
    if not vm:return False
    seen=lambda t:{m.replace(',','') for m in re.findall(r'\d+(?:\.\d+)?',t or '')}
    hidden=seen(final)-seen((slide.get('body') or {}).get('question',''))-seen(slide.get('subheading',''))
    shown={str(int(v)) if v==int(v) else str(float(v)) for v in model_numbers(vm)}
    return bool(hidden&shown)

def _staged_page(slide,stage,number,total,index,hint,steps,final,think,marker):
    body=slide.get('body') or {}
    page=copy.deepcopy(slide)
    page.setdefault('visual_asset',{'is_required':False,'reasoning':'以文字與圖解呈現','asset_type':'none','image_prompt':'','style_tags':VISUAL_STYLE})
    page['layout_id']='Question'
    page['stage']=stage;page['staged_from']=index
    page['stage_step']=number;page['stage_total']=total
    page['body']=copy.deepcopy(body);page['body']['bullets']=[];page['body']['columns']=[]
    page['body']['answer']=''
    page['modules']=[];page['hint']='';page['key_sentence']=''
    if stage=='hint':page['hint']=hint
    elif stage=='steps':page['body']['answer']='\n'.join(steps)
    elif stage=='answer':
        page['body']['answer']=final
        page['key_sentence']=slide.get('key_sentence','')
    if stage=='question':page['think_seconds']=think
    else:page.pop('think_seconds',None)
    if stage in ('question','hint') and page.get('visual_model'):
        vm=page['visual_model']
        if vm.get('type')=='bar_model':
            # per-part values are worked-step results: keep them off the question/hint pages
            known=set(re.findall(r'\d+(?:\.\d+)?',(body.get('question') or '')+(slide.get('subheading') or '')))
            for bar in vm.get('bars',[]):
                for key in ('unit_value','total'):
                    if key in bar and str(bar[key]) not in known:bar.pop(key)
        if _leaks(slide,final):page.pop('visual_model')
    page['speaker_notes']=marker
    return page

def expand_staged(deck,mode='paired'):
    """Show one complete question page followed by its complete answer page.

    A Summary that carries an exit-ticket question becomes the concept-map page
    followed by question -> answer pages. Staged pages record staged_from /
    stage_step / stage_total so the rendered page count stays traceable. The
    worksheet and answer documents are built from the unexpanded reviewed deck.
    """
    result=copy.deepcopy(deck);pages=[]
    for index,slide in enumerate(deck['slides']):
        kind=route(slide['layout_id']);body=slide.get('body') or {}
        question=(body.get('question') or '').strip();answer=(body.get('answer') or '').strip()
        if (slide.get('stage') or not question or not answer or kind not in ('Question','Summary')
                or slide['layout_id'] in LEGACY_ROUTE):
            pages.append(copy.deepcopy(slide));continue
        steps,final=split_answer(answer)
        if mode=='paired':steps=[];final=answer
        hint=(slide.get('hint') or '').strip() if mode=='stepwise' else ''
        think=slide.get('think_seconds') or (10 if slide.get('page_role')=='情境頁' else 20)
        original=slide.get('speaker_notes','')
        if kind=='Summary':
            # An exit ticket can contain several questions. There are no steps
            # pages here, so the answer page must retain every answer line.
            final=answer
            summary=copy.deepcopy(slide)
            summary['body']['question']='';summary['body']['answer']=''
            summary['speaker_notes']=original+'\n（出口題見下一頁。）'
            pages.append(summary)
            kinds=['question','answer']
            base=copy.deepcopy(slide);base['heading']='出口題';base['subheading']='';base['page_role']='練習頁'
            base['visual_model']=None;base.pop('visual_model')
            base['speaker_notes']=original
        else:
            kinds=['question']+(['hint'] if hint else [])+(['steps'] if steps else [])+['answer']
            base=slide
        for number,stage in enumerate(kinds,1):
            marker=_note(stage,slide,think,hint,final)
            if stage=='question':marker+='\n'+original
            page=_staged_page(base,stage,number,len(kinds),index,hint,steps,final,think,marker)
            if mode=='paired' and stage=='answer' and base.get('quiz') and base.get('reading_context'):
                # The reading stays complete on the preceding question page;
                # the answer page keeps every numbered task without replaying
                # the entire passage and creating another question-page loop.
                page['body']['question']='\n'.join(f"({q['id']}) {q['question']}" for q in base['quiz']['questions'])
                page['speaker_notes']+='\n作答情境（見前一題目頁）：\n'+base['reading_context']
            page['stage_seq']=kinds
            if kind=='Summary':page['key_sentence']=''
            pages.append(page)
    result['slides']=pages
    return result

STAGE_NAMES={'question':'題目','hint':'提示','steps':'解法','answer':'解答'}
