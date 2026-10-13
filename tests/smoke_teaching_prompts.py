"""Manual local-only smoke test; does not submit or resume production jobs."""
import hashlib
import json
import time
import requests
from workflow_v2.curriculum_prompts import record_profile
from workflow_v2.contracts import slide_schema, validate_slide
from workflow_v2.engine import ensure_server, listener, _owned
from workflow_v2.model import call, unload_model, endpoint
from workflow_v2.model_policy import configured_model
from workflow_v2.pedagogy import system_prompt
from workflow_v2.pipeline import page_prompt, normalize_slide
from workflow_v2.store import ROOT, atomic


def main():
    before = listener()
    ensure_server()
    requests.get(endpoint()+'/api/tags',timeout=3).raise_for_status()
    results = []
    started = time.monotonic()
    cases = [
        (4,'數學','平均分裝','Steps','example',
         '24枝鉛筆平均裝成6袋，每袋有幾枝？24÷6=4，每袋4枝。',
         '指出總數、袋數，說明每袋的數量'),
        (5,'國語','從動作找人物線索','Steps','example',
         '小雨看見新同學站在門口，便拉開身旁的椅子，笑著說：「這裡還有位置！」新同學點點頭，走了過來。',
         '圈出小雨的動作，說出人物特點與依據'),
        (9,'英語','閱讀中的因果','Question','recall',
         'Mia missed the bus because she left home late. Her brother drove her to school, so she arrived before the first class.',
         '回答錯過公車的原因，指出原文線索')]
    try:
        for grade,subject,unit,layout,phase,text,task in cases:
            req=dict(grade=grade,subject=subject,unit=unit,difficulty='中難度',
                     model=configured_model(),semester='上學期',publisher='測試語料')
            out=ROOT/'logs'/'teaching-prompts-validation'/f'g{grade}-{subject}'
            src={'sha256':hashlib.sha256(text.encode()).hexdigest(),
                 'pages':[{'page':1,'text':text}],'chunks':[{'page':1,'text':text}]}
            atomic(out/'source.json',src)
            record_profile(req,out)
            item=dict(layout_id=layout,phase=phase,stage='計算',difficulty='中難度',
                      source_pages=[1],student_task=task,function='Example' if phase=='example' else 'Practice',
                      page_role='步驟頁' if phase=='example' else '練習頁',topic=unit,misconception=False)
            plan={'objectives':[task],'slides':[item]}
            prompt=page_prompt(req,plan,item,src,out)
            value=call(req['model'],prompt,slide_schema({1},layout,strict=True),3000,
                       out/'call.json',system=system_prompt(req),attempts=1,transform=normalize_slide)
            validate_slide(value,{1})
            if subject=='英語' and not any(c.isascii() and c.isalpha() for c in value['body']['answer']):
                raise AssertionError('English answer was entirely translated')
            if subject=='英語' and 'Mia missed the bus because she left home late.' not in value['body']['question']:
                raise AssertionError('Reading question omitted the passage students need')
            atomic(out/'slide.json',value)
            results.append({'grade':grade,'subject':subject,'layout':layout,'heading':value['heading'],
                            'schema_passed':True,'prompt_chars':len(prompt), 'system_chars':len(system_prompt(req))})
            print(json.dumps(results[-1],ensure_ascii=False),flush=True)
        atomic(ROOT/'logs'/'teaching-prompts-validation'/'summary.json',
               {'model':configured_model(),'cases':results,'seconds':round(time.monotonic()-started,2),
                'scope':'Three local schema/language smoke cases; not a full curriculum quality audit.'})
    finally:
        if before is None:
            unload_model(configured_model())
            owned=listener()
            if _owned(owned):
                children=owned.children(recursive=True)
                owned.terminate();owned.wait(timeout=15)
                for child in children:
                    try:child.terminate();child.wait(timeout=15)
                    except Exception:pass


if __name__=='__main__':
    main()
