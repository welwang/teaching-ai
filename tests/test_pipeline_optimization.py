"""Bounded generation, complete batch verdicts and independent revisions."""
import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from workflow_v2 import pipeline,service
from workflow_v2.store import Store,atomic
from tests.test_design_system import sample_deck
from tests.test_system_audit import REQUEST


def setup_pages(out,count=3):
    slides=sample_deck()['slides'][:count]
    atomic(out/'plan.json',{'objectives':['認識角'],'slides':[
        {'layout_id':s['layout_id'],'topic':s['heading'],'source_pages':[1],'phase':'concept'} for s in slides]})
    atomic(out/'source.json',{'sha256':'source-v1','pages':[{'page':1,'text':'角有一個頂點。'}],
                            'chunks':[{'page':1,'text':'角有一個頂點。'}]})
    for i,s in enumerate(slides,1):atomic(out/'slides'/f'{i:03}.json',s)
    return slides


class PipelineOptimizationTest(unittest.TestCase):
    def test_three_pages_share_one_review_and_resume_uses_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);setup_pages(out)
            verdict={'results':[dict(page_number=n,passed=True,issues=[]) for n in (1,2,3)]}
            with patch.object(pipeline,'call',return_value=verdict) as call, \
                 patch.object(pipeline,'deck',return_value={'slides':[]}), \
                 patch.object(pipeline.quality,'check_slide',return_value=[]):
                pipeline.review(REQUEST,out);pipeline.review(REQUEST,out)
            call.assert_called_once()
            self.assertEqual(call.call_args.args[1].count('角有一個頂點。'),1)
            self.assertEqual(len(list((out/'reviews').glob('*.json'))),3)
            self.assertEqual(pipeline.read(out/'review-progress.json')['completed_pages'],3)

    def test_missing_or_duplicate_batch_pages_never_mark_others_reviewed(self):
        for results in ([dict(page_number=1,passed=True,issues=[])]*3,
                        [dict(page_number=1,passed=True,issues=[])]):
            with self.subTest(results=results),tempfile.TemporaryDirectory() as folder:
                out=Path(folder);setup_pages(out)
                with patch.object(pipeline,'call',return_value={'results':results}), \
                     patch.object(pipeline.quality,'check_slide',return_value=[]):
                    errors=pipeline.prefetch_reviews(REQUEST,out,pipeline.read(out/'plan.json'),
                                                   pipeline.read(out/'source.json'),range(3))
                self.assertEqual(errors,{})
                self.assertEqual(list((out/'reviews').glob('*.json')),[])

    def test_unavailable_batch_service_does_not_retry_every_page(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);setup_pages(out)
            with patch.object(pipeline,'call',side_effect=RuntimeError('HTTP 503')) as call, \
                 patch.object(pipeline,'fallback_page') as fallback, \
                 patch.object(pipeline,'deck',return_value={'slides':[]}), \
                 patch.object(pipeline.quality,'check_slide',return_value=[]):
                pipeline.review(REQUEST,out)
            call.assert_called_once();self.assertEqual(fallback.call_count,3)

    def test_batch_reject_repairs_only_that_page_then_reviews_it(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);slides=setup_pages(out)
            revised=slides[1].copy();revised['heading']='修改後'
            verdict={'results':[dict(page_number=n,passed=n!=2,issues=['答案錯誤'] if n==2 else []) for n in (1,2,3)]}
            with patch.object(pipeline,'call',side_effect=[verdict,{'passed':True,'issues':[]}]) as call, \
                 patch.object(pipeline,'author_page',return_value=revised) as author, \
                 patch.object(pipeline,'deck',return_value={'slides':[]}), \
                 patch.object(pipeline.quality,'check_slide',return_value=[]):
                pipeline.review(REQUEST,out)
            self.assertEqual(call.call_count,2);author.assert_called_once()
            self.assertEqual(author.call_args.args[2],1)
            self.assertEqual(call.call_args.args[4].name,'review-2.json')

    def test_oversize_batch_splits_without_cutting_source(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);setup_pages(out)
            with patch.object(pipeline,'source_context',return_value=[{'text':'來源'*20000}]), \
                 patch.object(pipeline,'call') as call, \
                 patch.object(pipeline.quality,'check_slide',return_value=[]):
                pipeline.prefetch_reviews(REQUEST,out,pipeline.read(out/'plan.json'),
                                          pipeline.read(out/'source.json'),range(3))
            call.assert_not_called()

    def test_review_cache_changes_with_age_and_model_policy(self):
        out=Path('job');s=sample_deck()['slides'][0];src={'sha256':'source'}
        one=pipeline.review_cache(REQUEST,out,s,src)
        self.assertNotEqual(one,pipeline.review_cache(dict(REQUEST,grade=9),out,s,src))
        self.assertNotEqual(one,pipeline.review_cache(dict(REQUEST,model='other'),out,s,src))

    def test_batch_review_uses_page_roles_without_author_demands(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);slides=setup_pages(out)
            slides[0]['layout_id']='Cover';atomic(out/'slides/001.json',slides[0])
            slides[2]['layout_id']='Summary';atomic(out/'slides/003.json',slides[2])
            verdict={'results':[dict(page_number=n,passed=True,issues=[]) for n in (1,2,3)]}
            with patch.object(pipeline,'call',return_value=verdict) as call, \
                 patch.object(pipeline.quality,'check_slide',return_value=[]):
                pipeline.prefetch_reviews(REQUEST,out,pipeline.read(out/'plan.json'),
                                          pipeline.read(out/'source.json'),range(3))
            prompt=call.call_args.args[1];system=call.call_args.kwargs['system']
            self.assertIn('不要求題目、價格、運算',prompt)
            self.assertIn('只抽查其中一個概念',prompt)
            self.assertIn('嚴禁用別頁',prompt)
            self.assertNotIn('每一頁都從',system)
            self.assertNotIn('每頁正文',system)

    def test_dense_draft_is_repaired_once_before_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);setup_pages(out);(out/'slides/001.json').unlink()
            with patch.object(pipeline,'author_page',side_effect=ValueError('算式錯誤')) as author:
                pipeline.write_one(REQUEST,out,0,pipeline.read(out/'plan.json')['slides'][0])
            self.assertEqual(author.call_count,2)
            self.assertTrue(author.call_args.kwargs['final'])
            self.assertTrue((out/'quality-warnings.json').exists())

    def test_failed_draft_is_included_in_targeted_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);slides=setup_pages(out,1);(out/'slides/001.json').unlink()
            with patch.object(pipeline,'page_prompt',return_value='只讀本頁來源'), \
                 patch.object(pipeline,'call',return_value=slides[0]) as call, \
                 patch.object(pipeline,'qa_gate',side_effect=[ValueError('具體修正理由'),slides[0]]):
                pipeline.write_one(REQUEST,out,0,pipeline.read(out/'plan.json')['slides'][0])
            self.assertEqual(call.call_count,2)
            prompt=call.call_args.args[1]
            self.assertIn('具體修正理由',prompt);self.assertIn('角度探險',prompt)
            self.assertEqual(call.call_args.kwargs['attempts'],2)

    def test_analysis_brief_preserves_whole_json_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            atomic(out/'analysis.json',{'objectives':['學會比較'],'core_concepts':[
                {'name':'角','meaning':'描述'*1000},{'name':'直角','meaning':'九十度'}],
                'worked_examples':[{'problem':'長題'*1000,'solution':'完整答案'}]})
            brief=pipeline.analysis_brief(out,limit=150,phase='example')
            value=json.loads(brief);self.assertLessEqual(len(brief),150)
            self.assertEqual(value['core_concepts'][0]['meaning'],'九十度')

    def test_revision_keeps_original_after_parent_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);parent=store.submit(REQUEST);original=setup_pages(store.folder(parent),1)[0]
            with store.db() as c:c.execute("UPDATE jobs SET status='done' WHERE id=?",(parent,))
            child=service.regenerate(parent,0,'改標題',store,field='heading');store.remove_job(parent)
            revised=original.copy();revised.update(heading='新標題',body={'不應改變':'內容'})
            result=pipeline.apply_regenerate_scope(store.folder(child),0,revised)
            self.assertEqual(result['heading'],'新標題');self.assertEqual(result['body'],original['body'])

    def test_corrupt_queued_request_does_not_block_next_presentation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);bad=store.submit(REQUEST);good=store.submit(REQUEST)
            with store.db() as c:c.execute('UPDATE jobs SET request=? WHERE id=?',('{broken',bad))
            self.assertEqual(store.claim()['id'],good)
            self.assertEqual(store.get(bad)['status'],'failed')

    def test_generic_math_prompts_do_not_force_an_unrelated_ratio_lesson(self):
        from workflow_v2.pedagogy import system_prompt
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);setup_pages(out,1)
            plan=pipeline.read(out/'plan.json');src=pipeline.read(out/'source.json')
            text=system_prompt(dict(REQUEST,unit='三步驟運算'))+pipeline.page_prompt(REQUEST,plan,plan['slides'][0],src,out)
            self.assertNotIn('比和比值要一起算',text)
            self.assertNotIn('32元可以換1美元',text);self.assertNotIn('64 元換幾美元',text)
            self.assertIn('以當頁主教材為準',text)

    def test_old_outline_reply_is_not_reused_after_prompt_policy_change(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);atomic(out/'plan-call-attempt-0-old.json',{'message':{'content':'old'}})
            with patch.object(pipeline,'normalize_outline') as normalize:
                self.assertFalse(pipeline.recover_outline(REQUEST,out,{1},since=time.time()+1))
            normalize.assert_not_called()

    def test_revision_reuses_summary_without_copying_token_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);parent=store.submit(REQUEST);out=store.folder(parent);setup_pages(out,1)
            atomic(out/'source-summary/batch-hash.json',{'summary':'角有一個頂點'})
            atomic(out/'source-summary/batch-hash-attempt-0-abcdef123456.json',{'prompt_eval_count':10,'eval_count':5})
            with store.db() as c:c.execute("UPDATE jobs SET status='done' WHERE id=?",(parent,))
            child=service.regenerate(parent,0,'改標題',store)
            self.assertTrue((store.folder(child)/'source-summary/batch-hash.json').exists())
            self.assertEqual(list((store.folder(child)/'source-summary').glob('*-attempt-*.json')),[])

    def test_legacy_copied_reply_is_only_charged_once_in_session(self):
        from workflow_v2.monitoring import session_usage
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);one=store.submit(REQUEST);two=store.submit(REQUEST)
            for jid in (one,two):
                atomic(store.folder(jid)/'source-summary/batch-hash-attempt-0-abcdef123456.json',{'prompt_eval_count':10,'eval_count':5})
            self.assertEqual(session_usage(store,since=0)['total_tokens'],15)


if __name__=='__main__':unittest.main()
