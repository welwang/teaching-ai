"""Regression tests for the generation errors found in the 2026-10-04 log review (see CHANGELOG)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pymupdf

from workflow_v2 import qa, runlog
from workflow_v2.source_reader import recover_pdf_page

REQUEST = {'model': 'test-model'}


def question_page(question, final='5'):
    return {'layout_id': 'Question', 'heading': '想一想', 'subheading': '', 'hint': '', 'key_sentence': '',
            'body': {'question': question, 'answer': '答：' + final, 'bullets': [], 'columns': []}, 'modules': []}


class TraceableNumbersTest(unittest.TestCase):
    """Cause: 77 'untraceable' rejections; many were legal decimal-point moves and long-division digits."""

    def test_moving_the_decimal_point_is_traceable(self):
        steps = ['把 0.3 和 0.5 同時乘以 10，變成 3 ÷ 5', '3 ÷ 5：3 不夠除，商個位記 0，補 0 變 30，30 ÷ 5 = 6，所以商是 0.6']
        self.assertEqual(qa.check_traceable('0.3 ÷ 0.5 = ?', steps), [])
        self.assertEqual(qa.check_traceable('4.5 ÷ 1.25 = ?', ['4.5 和 1.25 同時乘以 100，變成 450 ÷ 125', '450 ÷ 125 = 3.6']), [])

    def test_an_invented_number_is_still_caught(self):
        found = qa.check_traceable('0.3 ÷ 0.5 = ?', ['3 ÷ 5 = 0.6', '再乘以 17 得到 10.2'])
        self.assertEqual([f['code'] for f in found], ['untraceable'])
        self.assertIn('17', found[0]['message'])
        self.assertTrue(qa.check_traceable('紅筆：藍筆＝2：3，有幾枝藍筆？', ['12÷2=6', '3×6=18']))


class AnswerLineTest(unittest.TestCase):
    """Cause: 35 'exposed_answer' rejections; an empty answer line '答：' at the end of a question is not a leaked answer."""

    def codes(self, question):
        return [f['code'] for f in qa.check_exposure(question_page(question))]

    def test_empty_answer_lines_are_fine(self):
        for line in ('答：', '答：＿＿＿', '答：______ 個', '答： ', '解答：…', '答：□'):
            self.assertEqual(self.codes('6 ÷ 0.5 = ?\n\n提示：同時乘以 10。\n\n' + line), [], line)

    def test_a_filled_in_answer_is_still_a_leak(self):
        for line in ('答：12', '答案是 12', '解答：12 個', '答為 12'):
            self.assertIn('exposed_answer', self.codes('6 ÷ 0.5 = ?\n\n' + line), line)


class SourcePageTest(unittest.TestCase):
    """Cause: 9 failures of the 'source' stage on the same page; the reader's harmless remarks stopped the whole job."""

    def recover(self, value):
        with tempfile.TemporaryDirectory() as t, pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((50, 50), 'x')
            out = Path(t)
            model = Mock(return_value=value)
            text = recover_pdf_page(page, 31, REQUEST, out, 'hash', model)
            saved = json.loads((out / 'source-ocr' / '031.json').read_text(encoding='utf-8'))
        return text, saved

    def test_a_complete_page_with_remarks_is_accepted_and_the_remarks_are_kept(self):
        text, saved = self.recover({'text': '3x² - 5x + 7', 'complete': True, 'issues': ['手寫算式中的變數 x 字形較小，已依上下文轉錄']})
        self.assertEqual(text, '3x² - 5x + 7')
        self.assertEqual(saved['notes'], ['手寫算式中的變數 x 字形較小，已依上下文轉錄'])
        self.assertFalse(saved['blank'])

    def test_a_blank_page_is_recorded_as_blank_not_a_failure(self):
        text, saved = self.recover({'text': ' ', 'complete': False, 'issues': ['圖片內容為空白，無法辨識任何文字或圖形。']})
        self.assertIn('沒有可辨識', text)
        self.assertTrue(saved['blank'])

    def test_an_incomplete_page_still_stops_with_a_plain_message(self):
        with self.assertRaises(ValueError) as caught:
            self.recover({'text': '3x', 'complete': False, 'issues': ['右半頁模糊']})
        self.assertIn('第 31 頁辨識不完整：右半頁模糊', str(caught.exception))


class TestIdsNeverReachTheRealLogTest(unittest.TestCase):
    """Cause: tests wrote 'aaaa…' / 'bbbb…' job events into logs/workflow-v2.jsonl and made real error counts look worse."""

    def test_fixture_ids_are_dropped_on_the_real_data_root_but_work_elsewhere(self):
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / 'workflow-v2.jsonl'
            from unittest.mock import patch
            with patch.object(runlog, 'SYSTEM_LOG', log):
                runlog.log_event('deck_validation_failed', 'a' * 32, stage='render')
                self.assertFalse(log.exists())
                real = '0123456789abcdef0123456789abcdef'
                runlog.log_event('stage_started', real, job_file=False, stage='write')
                self.assertEqual(json.loads(log.read_text(encoding='utf-8').splitlines()[0])['job_id'], real)
            runlog.log_event('stage_started', 'a' * 32, root=Path(t), stage='write')
            self.assertTrue((Path(t) / 'run.jsonl').exists())


if __name__ == '__main__':
    unittest.main()