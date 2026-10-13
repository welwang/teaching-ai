"""因數、倍數與學習單來源長度的回歸測試。"""
import json
import unittest

from workflow_v2 import qa, worksheet


def codes(found):
    return [f['code'] for f in found]


class TraceableFactorsTest(unittest.TestCase):
    def test_short_division_divisor_named_before_the_division(self):
        steps = ['觀察題目中的數字 30。因為它是偶數，所以能被最小的質數 2 整除。\n計算：30 ÷ 2 = 15。',
                 '看上一步得到的商 15。它不能被 2 整除，試下一個最小質數 3。\n計算：15 ÷ 3 = 5。',
                 '看上一步得到的商 5。5 本身是質數，不能再拆了。\n把左邊的除數寫出來：2、3、5。']
        self.assertEqual(qa.check_traceable('我們要把數字 30 分解成質因數。', steps), [])

    def test_prime_factorization_and_gcd(self):
        steps = ['12 = 2 × 2 × 3\n20 = 2 × 2 × 5', '找出兩行都有的數字：兩個 2。', '把圈出的數相乘：2 × 2 = 4。']
        self.assertEqual(qa.check_traceable('請找出 12 和 20 的最大公因數。', steps), [])

    def test_common_division_quotients(self):
        steps = qa.sentences('1. 同時除以 2 → 剩餘 24、54\n2. 再除以 2 → 剩餘 12、27\n3. 再除以 3 → 剩餘 4、9')
        self.assertEqual(qa.check_traceable('請用短除法分解 48 和 108，找出它們的最大公因數。', steps), [])

    def test_lcm_stated_as_the_answer(self):
        self.assertEqual(qa.check_traceable('長24公分、寬18公分的卡片拼成最小的正方形', ['72公分（24和18的最小公倍數是72）']), [])

    def test_digit_sum_divisibility(self):
        steps = ['78 ÷ 2 = 39', '39 ÷ 3 = 13（因為 3+9=12，能被 3 整除）']
        self.assertEqual(qa.check_traceable('請將 78 做質因數分解。', steps), [])

    def test_invented_numbers_are_still_rejected(self):
        self.assertEqual(codes(qa.check_traceable('紅筆：藍筆＝2：3，有幾枝藍筆？', ['12÷2=6', '3×6=18'])), ['untraceable'])
        self.assertEqual(codes(qa.check_traceable('0.3 ÷ 0.5 = ?', ['3 ÷ 5 = 0.6', '再乘以 17 得到 10.2'])), ['untraceable'])
        self.assertEqual(codes(qa.check_traceable('求 12 和 20 的最大公因數', ['已知 7 組，7 × 4 = 28'])), ['untraceable'])


class KeepDraftTest(unittest.TestCase):
    def test_untraceable_or_dense_hook_keeps_the_draft_for_the_teacher(self):
        for code in ('untraceable', 'hook_dense'):
            self.assertTrue(qa.keepable([qa.finding(code, 'x')]))

    def test_wrong_maths_or_copying_still_falls_back(self):
        for code in ('arithmetic', 'verbatim_copy', 'mismatch'):
            self.assertFalse(qa.keepable([qa.finding(code, 'x'), qa.finding('untraceable', 'y')]))


class WorksheetBudgetTest(unittest.TestCase):
    def evidence(self, pages):
        slides = [{'topic': f't{i}', 'source_pages': [i % pages + 1, 1], 'heading': 'h', 'modules': [],
                   'bullets': [], 'question': '', 'answer': ''} for i in range(25)]
        return {'slides': slides, 'source_excerpts': [{'page': p, 'text': '題' * 1200} for p in range(1, pages + 1)]}

    def test_small_evidence_is_unchanged(self):
        value = self.evidence(3)
        self.assertIs(worksheet._fit_evidence(value, 20000), value)

    def test_large_evidence_drops_whole_excerpts_and_keeps_slides(self):
        value = self.evidence(17)
        fitted = worksheet._fit_evidence(value, 20000)
        self.assertLessEqual(len(json.dumps(fitted, ensure_ascii=False, separators=(',', ':'))), 20000)
        self.assertEqual(fitted['slides'], value['slides'])
        self.assertTrue(all(e['text'] == '題' * 1200 for e in fitted['source_excerpts']))
        self.assertIn(1, [e['page'] for e in fitted['source_excerpts']])

    def test_slides_alone_too_large_still_refuses(self):
        value = self.evidence(2)
        value['slides'][0]['bullets'] = ['字' * 21000]
        with self.assertRaises(ValueError):
            worksheet._fit_evidence(value, 20000)


if __name__ == '__main__':
    unittest.main()


class ReviewCitationTest(unittest.TestCase):
    def run_filter(self, qa_value):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from workflow_v2 import pipeline
        with tempfile.TemporaryDirectory() as t, patch.object(pipeline, 'log_event'):
            return pipeline.without_citation_issues(Path(t), 7, qa_value, [])

    def test_a_citation_only_complaint_passes_the_page(self):
        value = self.run_filter({'passed': False, 'issues': [
            'source_pages 引用錯誤：本頁內容（空心菜漲價）對應主教材 page 8，但投影片標註 source_pages: [9]。']})
        self.assertEqual(value, {'passed': True, 'issues': []})

    def test_real_errors_still_reject(self):
        wrong = 'visual_model中哥哥count為2，但168公分並非140公分的整數倍，圖示數量與題目數據不符。'
        value = self.run_filter({'passed': False, 'issues': ['頁碼標註應為第 5 頁', wrong]})
        self.assertEqual(value, {'passed': False, 'issues': [wrong]})
