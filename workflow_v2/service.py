"""Public application interface, independent of Streamlit and model backends."""
import json
from filelock import FileLock
from .store import Store,STAGES,atomic

def approve_outline(jid,plan,store=None):
    """Validate edited slide order, citations and pedagogy before resuming generation."""
    from .contracts import outline_schema,validate
    from .pedagogy import validate_teaching_cycle
    store=store or Store();row=store.get(jid)
    if row['status']!='awaiting_outline' or row['stage']!=2:raise ValueError('工作目前不在大綱確認階段')
    out=store.folder(jid)
    source=json.loads((out/'source.json').read_text(encoding='utf-8'))
    count=json.loads(row['request'])['slide_count']
    validate(outline_schema(count,{page['page'] for page in source['pages']}),plan)
    if not any('student_task' in item for item in plan['slides']):
        # An outline saved before the teaching-design fields existed is upgraded
        # in place (roles, tasks, misconception page) rather than rejected.
        from .pipeline import normalize_outline
        plan=normalize_outline(plan)
    validate_teaching_cycle(plan)
    from .change_log import change_context
    with change_context(actor='user',action='outline_approved',stage='plan',reason='使用者編輯並確認大綱'):
        atomic(out/'plan.json',plan)
    store.approve_outline(jid)
    store.event(jid,'plan','使用者確認大綱')

def result(jid,store=None):
    store=store or Store();r=store.get(jid);path=store.folder(jid)/'result.json'
    if r['status']=='done' and path.exists():return json.loads(path.read_text(encoding='utf-8'))
    return dict(job_id=jid,status=r['status'],stage=STAGES[min(r['stage'],len(STAGES)-1)],artifacts={},error=r['error'],model=json.loads(r['request'])['model'])

def regenerate(jid,index,instruction,store=None,field='slide'):
    """Fork an immutable job; preserve every other page and its review cache."""
    import shutil
    store=store or Store();r=store.get(jid)
    if r['status'] not in ('done','failed'):raise ValueError('請等待目前工作完成或停止後再重生單頁')
    old=store.folder(jid);plan=json.loads((old/'plan.json').read_text(encoding='utf-8'))
    if type(index) is not int or not 0<=index<len(plan['slides']):raise ValueError('無效頁碼')
    if field not in ('slide','heading','body','speaker_notes','media_hint','visual_asset'):
        raise ValueError('無效修改欄位')
    if field!='slide' and not (old/'slides'/f'{index+1:03}.json').exists():
        raise ValueError('此頁尚無原稿，無法只修改指定欄位')
    # A new immutable request records exactly what the user requested.
    new=store.submit(json.loads(r['request']),ready=False);folder=store.folder(new)
    try:
        for name in ('source.json','plan.json','analysis.json','qa-report.json','quality-warnings.json',
                     'template-selection.json','teaching-profile.json','teaching-prompt.md','source-warnings.json'):
            if (old/name).exists():shutil.copy2(old/name,folder/name)
        if (folder/'qa-report.json').exists():
            # the regenerated page starts with a clean QA history
            report=json.loads((folder/'qa-report.json').read_text(encoding='utf-8'))
            report.get('pages',{}).pop(str(index+1),None);atomic(folder/'qa-report.json',report)
        warnings_path=folder/'quality-warnings.json'
        if warnings_path.exists():
            warnings=json.loads(warnings_path.read_text(encoding='utf-8'))
            warnings.pop(str(index+1),None);atomic(warnings_path,warnings)
        for name in ('slides','reviews','source-summary','page-policies','source-ocr'):
            if (old/name).exists():
                # Reuse summaries, not the parent's raw inference history:
                # copying those replies charged the same tokens a second time.
                ignored=shutil.ignore_patterns('*-attempt-*.json','*-http-*.json') if name=='source-summary' else None
                shutil.copytree(old/name,folder/name,ignore=ignored)
        target=folder/'slides'/f'{index+1:03}.json'
        if target.exists():shutil.copy2(target,folder/'regenerate-original.json')
        target.unlink(missing_ok=True)
        atomic(folder/'regenerate.json',{'page':index,'instruction':instruction,'parent_job':jid,'field':field})
        # A legacy parent has no page policies. Record the immutable origin for
        # the other copied pages; the changed page always starts from scratch.
        from .pipeline import page_fingerprint
        request=json.loads(r['request'])
        for i,item in enumerate(plan['slides']):
            if i==index:continue
            policy=folder/'page-policies'/f'{i+1:03}.json'
            if not policy.exists() and (folder/'slides'/f'{i+1:03}.json').exists():
                atomic(policy,{'fingerprint':page_fingerprint(request,folder,i,item),'started':0,'parent_job':jid})
        (folder/'page-policies'/f'{index+1:03}.json').unlink(missing_ok=True)
        with store.db() as c:c.execute("UPDATE jobs SET stage=2,status='pending' WHERE id=?",(new,))
    except Exception:
        with store.db() as c:c.execute("UPDATE jobs SET status='failed',error='複製重生工作失敗' WHERE id=?",(new,))
        raise
    from .change_log import record
    record(folder,'page_revision_requested',after={'page':index+1,'field':field,'instruction':instruction},
           actor='user',parent_job=jid,page=index+1,field=field,reason=instruction)
    return new
