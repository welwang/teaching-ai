"""Originality: slides re-express the reference material instead of copying it."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_page_recovery import BODY, slide, make_job
from workflow_v2 import originality as og, pipeline, qa as quality, worksheet
from workflow_v2.deck_check import check_deck
from workflow_v2.store import atomic

SOURCE = ('兩個三角形如果形狀相同只是大小不同，就稱為相似三角形。相似三角形中位置相對的邊叫做對應邊，'
          '位置相對的角叫做對應角，對應邊的長度比相等，對應角的大小也相等。')
COPY = '相似三角形中位置相對的邊叫做對應邊，位置相對的角叫做對應角，對應邊的長度比相等'
OWN = '把一張照片放大列印，人像變大了，臉型卻沒有變。想一想：哪些東西變了？哪些東西沒有變？'
REQUEST = {'grade': 8, 'subject': '數學', 'unit': '相似形', 'model': 'm', 'difficulty': '全部'}


def page(bullets, notes='1. 開場：請學生觀察，停20秒思考。', **more):
    return slide(heading='相似的三角形', subheading='', body=dict(BODY, bullets=bullets), speaker_notes=notes, **more)


class MeasureTest(unittest.TestCase):
    def test_punctuation_and_spacing_do_not_hide_copying(self):
        self.assertEqual(og.normalize('相似 三角形，  ABC！'), og.normalize('相似三角形abc'))
        spaced = '相似三角形中 位置相對的邊 叫做對應邊 ， 位置相對的角叫做 對應角'
        self.assertEqual(og.check_slide_copy(page([spaced]), [SOURCE])[0]['verdict'], 'copied')

    def test_copied_passage_is_flagged_and_own_words_pass(self):
        self.assertEqual([h['verdict'] for h in og.check_slide_copy(page([COPY]), [SOURCE])], ['copied'])
        self.assertEqual(og.check_slide_copy(page([OWN]), [SOURCE]), [])
        longest, share = og.slide_score(page([COPY]), [SOURCE])
        self.assertGreaterEqual(longest, 30)
        self.assertGreater(share, 0.5)

    def test_changing_a_few_words_is_still_caught(self):
        tweaked = '相似三角形中位置相對的邊叫做對應邊，位置相對的角則叫做對應角，對應邊的長度比相等，所以很重要'
        self.assertTrue(og.check_slide_copy(page([tweaked]), [SOURCE]))

    def test_short_shared_terms_and_definitions_are_fine(self):
        self.assertEqual(og.check_slide_copy(page(['相似三角形：形狀相同、大小不同。', '對應邊的長度比相等。']), [SOURCE]), [])

    def test_short_quotation_is_allowed_but_long_or_many_are_not(self):
        quoted = '課本說：「位置相對的邊叫做對應邊，位置相對的角叫做對應角」，你同意嗎？'
        self.assertEqual(og.check_slide_copy(page([quoted]), [SOURCE]), [])
        long_quote = '課本說：「' + COPY + '，對應角的大小也相等」。'
        self.assertTrue(og.check_slide_copy(page([long_quote]), [SOURCE]))

    def test_notes_may_not_hold_the_textbook_either(self):
        hits = og.check_slide_copy(page([OWN], notes='教材原文：' + SOURCE + ' 停20秒。'), [SOURCE])
        self.assertEqual([h['field'] for h in hits], ['speaker_notes'])

    def test_english_needs_a_much_longer_overlap(self):
        text = 'Tom and his sister walk to the old library every Saturday morning before lunch because they love reading together there'
        short = {'body': dict(BODY, bullets=['Tom and his sister walk to the old library every Saturday.'])}
        self.assertNotIn('copied', [h['verdict'] for h in og.check_slide_copy(short, [text])])
        self.assertTrue(og.check_slide_copy({'body': dict(BODY, bullets=[text])}, [text]))


class GateTest(unittest.TestCase):
    def test_qa_rejects_a_copied_page_as_a_hard_failure_with_rewrite_advice(self):
        findings = quality.check_slide(page([COPY]), None, REQUEST, None, sources=[SOURCE])
        copied = [f for f in findings if f['code'] == 'verbatim_copy']
        self.assertEqual(len(copied), 1)
        self.assertIn(copied[0], quality.hard(findings))
        self.assertIn('用你自己的話', quality.feedback(findings))
        self.assertEqual([f for f in quality.check_slide(page([OWN]), None, REQUEST, None, sources=[SOURCE]) if f['code'] == 'verbatim_copy'], [])
        self.assertEqual([f for f in quality.check_slide(page([COPY]), None, REQUEST, None) if f['code'] == 'verbatim_copy'], [])

    def test_write_gate_sends_the_page_back_and_accepts_the_rewrite(self):
        with tempfile.TemporaryDirectory() as folder:
            out = make_job(folder, page([COPY]))
            atomic(out / 'source.json', {'sha256': 'x', 'pages': [{'page': 1, 'text': SOURCE}]})
            item = json.loads((out / 'plan.json').read_text(encoding='utf-8'))['slides'][0]
            with self.assertRaises(ValueError) as caught:
                pipeline.qa_gate(REQUEST, out, 0, item, page([COPY]), final=True)
            self.assertIn('自己的話', str(caught.exception))
            kept = pipeline.qa_gate(REQUEST, out, 0, item, page([OWN]), final=True)
            self.assertEqual(kept['body']['bullets'], [OWN])

    def test_cited_sources_reads_only_the_cited_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            atomic(out / 'source.json', {'pages': [{'page': 1, 'text': 'A'}, {'page': 2, 'text': 'B'}, {'page': 3, 'text': 'C'}]})
            self.assertEqual(pipeline.cited_sources(out, {'source_pages': [1, 3]}), ['A', 'C'])
            self.assertEqual(pipeline.cited_sources(Path(folder) / 'none', {'source_pages': [1]}), [])

    def test_a_rejected_copy_is_rewritten_on_the_next_attempt_and_never_reaches_the_deck(self):
        with tempfile.TemporaryDirectory() as folder:
            out = make_job(folder, page([COPY]))
            atomic(out / 'source.json', {'sha256': 'x', 'pages': [{'page': 1, 'text': SOURCE}]})
            item = json.loads((out / 'plan.json').read_text(encoding='utf-8'))['slides'][0]
            seen = []

            def fake_author(request, out_, index, feedback='', **kw):
                seen.append(feedback)
                return pipeline.qa_gate(request, out_, index, item, page([COPY] if len(seen) == 1 else [OWN]), final=True)

            with patch.object(pipeline, 'author_page', side_effect=fake_author), patch.object(pipeline, 'recover_page', return_value=False):
                pipeline.write_one(REQUEST, out, 0, item)
            self.assertEqual(len(seen), 2)
            self.assertIn('自己的話', seen[1])


class AuditTest(unittest.TestCase):
    def test_audit_job_reports_pages_and_share_without_touching_the_job(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            atomic(out / 'source.json', {'pages': [{'page': 1, 'text': SOURCE}]})
            (out / 'slides').mkdir()
            atomic(out / 'slides' / '001.json', page([OWN], source_pages=[1]))
            atomic(out / 'slides' / '002.json', page([COPY], source_pages=[1]))
            before = sorted(p.name for p in out.rglob('*'))
            report = og.audit_job(out)
            self.assertEqual((report['pages'], report['copied']), (2, 1))
            self.assertEqual([r['verdict'] for r in report['rows']], ['', 'copied'])
            self.assertGreater(report['share'], 0.2)
            self.assertEqual(before, sorted(p.name for p in out.rglob('*')))


class PromptTest(unittest.TestCase):
    def test_page_prompt_tells_the_model_to_reexpress_not_copy(self):
        source = {'chunks': [{'page': 1, 'text': SOURCE}]}
        item = {'phase': 'concept', 'stage': '認識', 'difficulty': '低難度', 'source_pages': [1]}
        with tempfile.TemporaryDirectory() as temp:
            text = pipeline.page_prompt(REQUEST, {'objectives': ['x']}, item, source, Path(temp))
        for phrase in ('主教材只是參考資料', '用你自己的話', '禁止逐字複製', '「」括起來、每處30字內', '原創題'):
            self.assertIn(phrase, text)
        self.assertNotIn('可保留閱讀所需短摘句', text)
        self.assertIn('不可照抄', text)

    def test_worksheet_prompt_and_check(self):
        self.assertIn('用你自己的話', og.WRITER_RULE)
        value = {'instructions': 'x', 'questions': [{'difficulty': '低難度', 'question': COPY, 'source_pages': [1],
                                                        'answer': 'a', 'explanation': 'b'}]}
        evidence = {'source_excerpts': [{'page': 1, 'text': SOURCE}]}
        with patch.object(worksheet, 'validate'):
            with self.assertRaises(ValueError) as caught:
                worksheet._check(value, {}, {'低難度': 1}, evidence)
            self.assertIn('原創題', str(caught.exception))
            value['questions'][0]['question'] = OWN
            self.assertIs(worksheet._check(value, {}, {'低難度': 1}, evidence), value)


class FallbackAndDeckTest(unittest.TestCase):
    def test_fallback_page_has_no_textbook_text_anywhere(self):
        long_source = '。'.join('第%d段教材說明：相似三角形的對應邊成比例而且對應角相等所以可以用比例求出未知邊長' % i for i in range(30))
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            atomic(out / 'plan.json', {'slides': [{'topic': '相似三角形', 'student_task': '說出哪些邊對應', 'source_pages': [1]}]})
            atomic(out / 'source.json', {'pages': [{'page': 1, 'text': long_source}]})
            result = pipeline.fallback_page(REQUEST, out, 0, '審核未通過')
            self.assertEqual(og.check_slide_copy(result, [long_source]), [])
            self.assertLess(len(json.dumps(result, ensure_ascii=False)), 600)
            self.assertEqual(result['body']['bullets'][0], '說出哪些邊對應')

    def test_deck_check_reports_copying_with_page_and_numbers(self):
        deck = {'slides': [page([OWN], source_pages=[1]), page([COPY], source_pages=[1])]}
        report = check_deck(deck, REQUEST, reference={1: SOURCE})
        found = [f for f in report['findings'] if f['code'] == 'verbatim_copy']
        self.assertEqual([f['page'] for f in found], [2])
        self.assertEqual(found[0]['severity'], 'major')
        self.assertIn('連續相同約', found[0]['message'])
        self.assertEqual([f for f in check_deck(deck, REQUEST)['findings'] if f['code'] == 'verbatim_copy'], [])

    def test_an_old_style_source_dump_page_is_caught(self):
        dump = page([SOURCE], notes='未經 AI 審核；投影片顯示主教材原文摘錄。\n主教材原文全文：\n' + SOURCE, source_pages=[1])
        report = check_deck({'slides': [dump]}, REQUEST, reference={1: SOURCE})
        self.assertIn('verbatim_copy', [f['code'] for f in report['findings']])


if __name__ == '__main__':
    unittest.main()