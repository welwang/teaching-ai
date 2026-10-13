"""Grade/subject routing, source boundaries and actual generation integration."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_v2 import curriculum_prompts as prompts, pipeline, worksheet
from workflow_v2.pedagogy import system_prompt, slide_learning_guidance
from workflow_v2.store import atomic
from tests.test_workflow_v2 import REQUEST, slide


class CurriculumPromptsTest(unittest.TestCase):
    def test_task_override_reaches_generation_and_snapshot_without_changing_defaults(self):
        default = prompts.full_prompt(REQUEST)
        original_library = prompts.LIBRARY.read_bytes()
        custom = '先讓學生用積木示範，再請學生口述自己的推理；每個練習附一個提示。'
        request = dict(REQUEST, teaching_prompt_override=custom)
        for purpose in prompts.PURPOSES:
            self.assertIn(custom, prompts.guidance(request, purpose))
        self.assertIn(custom, system_prompt(request))
        self.assertIn(custom, pipeline.review_system(request))
        self.assertNotEqual(prompts.policy_fingerprint(REQUEST), prompts.policy_fingerprint(request))
        self.assertNotEqual(prompts.policy_fingerprint(request), prompts.policy_fingerprint(dict(request, teaching_prompt_override='改用小組討論')))
        with tempfile.TemporaryDirectory() as folder:
            source = {'chunks': [{'page': 1, 'text': '因數與倍數'}]}
            item = {'phase': 'example', 'stage': '計算', 'difficulty': '低難度', 'source_pages': [1]}
            self.assertIn(custom, pipeline.page_prompt(request, {'objectives': ['理解因數']}, item, source, Path(folder)))
            prompts.record_profile(request, Path(folder))
            self.assertEqual((Path(folder) / 'teaching-prompt.md').read_text(encoding='utf-8'), custom)
            meta = json.loads((Path(folder) / 'teaching-profile.json').read_text(encoding='utf-8'))
            self.assertTrue(meta['customized_for_task'])
        self.assertEqual(prompts.full_prompt(REQUEST), default)
        self.assertEqual(prompts.LIBRARY.read_bytes(), original_library)
        self.assertEqual(prompts.guidance(dict(REQUEST, teaching_prompt_override='  ')), prompts.guidance(REQUEST))

    def test_all_eighteen_are_detailed_distinct_and_have_attributed_sources(self):
        data = prompts.library()
        self.assertEqual(len(data['profiles']), 18)
        self.assertEqual(len({p['id'] for p in data['profiles']}), 18)
        for p in data['profiles']:
            with self.subTest(profile=p['id']):
                text = prompts.full_prompt(p)
                self.assertGreater(len(text), 5000)
                self.assertGreater(sum(len(p[k]) for k in prompts.PROFILE_FIELDS), 400)
                for heading in ('先備知識檢查與補教', '大綱規劃', '逐頁編寫', '配套學習單',
                                '內容審核', '研究來源', '低難度策略', '中難度策略', '高難度策略'):
                    self.assertTrue(heading in text, f"{p['id']} 缺少 {heading}")
                self.assertIn('主教材', text)
                self.assertIn('可接受回答', text)
                self.assertIn('不是官方固定教法', text)
                self.assertGreaterEqual(len(prompts.selected(p)['sources']), 2)
        self.assertEqual(len({p['modelling'] for p in data['profiles']}), 18)
        self.assertEqual(len({p['assessment'] for p in data['profiles']}), 18)

    def test_runtime_routes_only_selected_profile_and_relevant_phase(self):
        req = dict(REQUEST, grade=4, subject='國語')
        text = prompts.guidance(req, 'write', 'example', '低難度')
        self.assertIn('國小四年級・國語', text)
        self.assertIn(prompts.selected(req)['profile']['modelling'], text)
        self.assertIn(prompts.selected(req)['subject']['phases']['example'], text)
        self.assertNotIn(prompts.selected(req)['subject']['phases']['recap'], text)
        self.assertNotIn('國中三年級', text)
        self.assertNotIn('高難度策略', text)
        self.assertNotIn('https://', text)

    def test_references_respect_their_research_scope(self):
        self.assertNotIn('ies_reading', {s['id'] for s in prompts.selected(dict(grade=4, subject='國語'))['sources']})
        self.assertIn('ies_reading', {s['id'] for s in prompts.selected(dict(grade=5, subject='國語'))['sources']})
        self.assertNotIn('ies_english', {s['id'] for s in prompts.selected(dict(grade=9, subject='英語'))['sources']})

    def test_english_is_not_forced_to_translate_every_student_sentence(self):
        req = dict(REQUEST, grade=5, subject='英語')
        self.assertIn('保留正確英文', system_prompt(req))
        self.assertNotIn('僅使用繁體中文', system_prompt(req))
        text = slide_learning_guidance(req, {'phase':'example', 'stage':'計算', 'difficulty':'低難度'})
        self.assertIn('英語練語言理解與使用', text)
        self.assertNotIn('示範或練習算法', text)
        self.assertIn('本頁教學用途', text)

    def test_language_progression_keeps_data_enum_but_teaches_language(self):
        for subject in ('國語', '英語'):
            text = prompts.progression_guidance(dict(grade=7, subject=subject))
            self.assertIn('認識→判斷→計算→應用', text)
            self.assertIn('不做算術', text)
        math = prompts.progression_guidance(dict(grade=4, subject='數學'))
        self.assertIn('不強迫加入無關算術', math)

    def test_age_specific_guidance_is_used_in_actual_page_prompt(self):
        source = {'chunks':[{'page':1,'text':'Who is she? She is my sister.'}]}
        item = {'phase':'example','stage':'計算','difficulty':'低難度','source_pages':[1]}
        req = dict(REQUEST, grade=4, subject='英語')
        with tempfile.TemporaryDirectory() as temp:
            text = pipeline.page_prompt(req, {'objectives':['理解對話']}, item, source, Path(temp))
        self.assertIn(prompts.selected(req)['profile']['task'], text)
        self.assertIn('Who is she?', text)
        self.assertIn('英文例句', text)
        self.assertIn('必要的短摘句（30字內，用「」標示）或你改寫的短文與問題一起放在body.question', text)
        self.assertNotIn('每步數字都要來自題目', text)

    def test_no_subjective_age_or_word_budget_rejections(self):
        text = pipeline.review_system(dict(REQUEST, grade=9, subject='國語'))
        self.assertIn('不要因未達建議字數', text)
        self.assertIn('開放題', text)
        self.assertNotIn('教師示範方法：', text)

    def test_profile_snapshot_is_real_markdown_and_changes_cache_identity(self):
        req = dict(REQUEST, grade=4, subject='數學')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            prompts.record_profile(req, out)
            self.assertTrue((out/'teaching-prompt.md').read_text(encoding='utf-8').startswith('# 國小四年級'))
            meta = json.loads((out/'teaching-profile.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['profile_id'], 'g4-math')
            self.assertEqual(meta['fingerprint'], prompts.policy_fingerprint(req))
        self.assertNotEqual(prompts.policy_fingerprint(req), prompts.policy_fingerprint(dict(req, grade=9)))

    def test_exported_documents_match_library_and_are_utf8_markdown(self):
        folder = prompts.LIBRARY.parent/'teaching-prompts'
        for p in prompts.library()['profiles']:
            self.assertEqual((folder/(p['id']+'.md')).read_text(encoding='utf-8'), prompts.full_prompt(p))
        self.assertTrue((folder/'README.md').read_text(encoding='utf-8').startswith('# 18'))

    def test_worksheet_cache_requires_matching_age_policy_and_evidence(self):
        req = dict(REQUEST, grade=5, subject='英語', difficulty='低難度')
        counts = worksheet._requirements(req)
        value = {'instructions':'Read and answer.', 'questions':[
            {'difficulty':'低難度','question':f'Complete example {n}: I ___ happy.',
             'answer':'am','explanation':'主詞 I 使用 am。','source_pages':[1]}
            for n in range(counts['低難度'])]}
        stems={'instructions':value['instructions'],'questions':[
            {k:v for k,v in q.items() if k not in ('answer','explanation')} for q in value['questions']]}
        answers=[{'answers':[{'id':i+1,'answer':q['answer'],'explanation':q['explanation']}
            for i,q in enumerate(value['questions']) if start<=i<start+3]} for start in range(0,6,3)]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            atomic(out/'source.json',{'pages':[{'page':1,'text':'I am happy.'}]})
            atomic(out/'plan.json',{'slides':[{'topic':'greetings','difficulty':'共用','phase':'example','source_pages':[1]}]})
            atomic(out/'reviewed-deck.json',{'slides':[slide()]})
            with patch.object(worksheet, 'call', side_effect=[stems,*answers, {'passed':True,'issues':[]}]) as call:
                self.assertEqual(worksheet.generate(req,out),value)
            self.assertIn(prompts.selected(req)['profile']['task'], call.call_args_list[0].args[1])
            self.assertNotIn('生成目標', call.call_args_list[-1].kwargs['system'])
            with patch.object(worksheet, 'call', side_effect=AssertionError('same cache must be reused')):
                self.assertEqual(worksheet.generate(req,out),value)
            with patch.object(worksheet, 'call', side_effect=[stems,*answers, {'passed':True,'issues':[]}]) as call:
                worksheet.generate(dict(req,grade=6),out)
                self.assertEqual(call.call_count,4)


if __name__ == '__main__':
    unittest.main()
