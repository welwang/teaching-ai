"""Regression tests for the four recurring console messages (real job 0da5f1b5, 2026-10-04)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_v2 import pipeline, qa as quality, local_images
from workflow_v2.contracts import VISUAL_STYLE
from workflow_v2.monitor_report import describe, plain_reason
from workflow_v2.store import atomic

BODY = {'bullets': [], 'columns': [], 'question': '', 'answer': '', 'code_snippet': {'language': '', 'code': ''}}


def slide(**changes):

    value = {'layout_id': 'Text_Visual', 'heading': '放大縮小，邊角怎麼變？', 'subheading': '找出圖中對應的邊與角',
             'body': dict(BODY, bullets=['觀察左邊的小三角形和右邊的大三角形。', '它們形狀一樣，只是大小不同。']),
             'modules': [{'keyword': '對應邊', 'description': '放大或縮小後，位置相對的兩條邊。'}],
             'visual_asset': {'is_required': False, 'reasoning': '', 'asset_type': 'none', 'image_prompt': '',
                              'style_tags': VISUAL_STYLE},
             'media_hint': {'search_keyword': '', 'image_description': ''},
             'speaker_notes': '1. 開場：請學生觀察兩個三角形，停20秒思考。', 'source_pages': [1]}
    value.update(changes)
    return value


class QualityRuleTest(unittest.TestCase):
    def test_answer_blank_label_is_not_a_cut_sentence(self):
        self.assertTrue(quality.is_blank_label('算出實際長度。\n\n作答區：\n方法說明：\n最終答案（含單位）：'))
        self.assertTrue(quality.is_blank_label('答案：'))
        self.assertFalse(quality.is_blank_label('所以小明買了：'))
        self.assertFalse(quality.is_blank_label('先算 4.5 × 50000，再'))
        question = '在比例尺為 1:50000 的地圖上，量得 4.5 公分，實際多長？\n\n作答區：\n最終答案（含單位）：'
        s = slide(heading='獨立練習：求實際長度', body=dict(BODY, question=question))
        self.assertNotIn('truncated', [f['code'] for f in quality.check_residue(s)])

    def test_real_cut_sentence_is_still_caught(self):
        s = slide(body=dict(BODY, bullets=['小明有 5 個蘋果，他又買了橘子和']))
        self.assertIn('truncated', [f['code'] for f in quality.check_residue(s)])

    def test_scale_ruler_term_is_not_mistaken_for_a_ruler_object(self):
        s = slide(heading='認識比例尺', subheading='', body=dict(BODY, bullets=['地圖上的 1 公分代表真實世界多遠？']))
        self.assertNotIn('mismatch', [f['code'] for f in quality.check_consistency(s)])
        real = slide(heading='鉛筆和尺的價錢', subheading='', body=dict(BODY, bullets=['小華買了蘋果和香蕉。']))
        self.assertIn('mismatch', [f['code'] for f in quality.check_consistency(real)])

    def test_feedback_tells_the_model_how_to_fix_a_ghost_image(self):
        text = quality.feedback([quality.finding('ghost_image', '文字提到圖，但本頁沒有圖', 'major', 'body')])
        self.assertIn('visual_model', text)
        self.assertIn('刪掉', text)

    def test_keepable_only_for_presentation_problems(self):
        ghost = [quality.finding('ghost_image', 'x')]
        wrong_math = [quality.finding('arithmetic', 'x')]
        self.assertTrue(quality.keepable(ghost))
        self.assertFalse(quality.keepable(wrong_math))
        self.assertFalse(quality.keepable(ghost + wrong_math))
        self.assertFalse(quality.keepable([]))


def make_job(root, draft, pages=(1,)):
    out = Path(root)
    atomic(out / 'plan.json', {'objectives': ['x'], 'slides': [
        {'layout_id': 'Text_Visual', 'topic': '對應關係', 'phase': 'concept', 'difficulty': '共用', 'source_pages': list(pages)}]})
    atomic(out / 'source.json', {'sha256': 'x', 'pages': [{'page': 1, 'text': '許多人喜歡自助旅行，需要地圖幫助。地圖有比例尺。'}]})
    atomic(out / 'drafts' / '001.json', draft)
    (out / 'slides').mkdir(exist_ok=True)
    return out


REQUEST = {'grade': 6, 'subject': '數學', 'unit': 'u', 'model': 'm', 'difficulty': '全部'}


class PageRecoveryTest(unittest.TestCase):
    def test_draft_with_only_a_missing_figure_is_kept_for_the_teacher_not_replaced_by_source_text(self):
        with tempfile.TemporaryDirectory() as folder:
            out = make_job(folder, slide(subheading='找出圖中對應的邊與角'))
            with patch.object(pipeline, 'log_event') as logged:
                result = pipeline.fallback_page(REQUEST, out, 0, '本地 AI 修復失敗：文字提到圖')
            saved = json.loads((out / 'slides' / '001.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['heading'], '放大縮小，邊角怎麼變？')
            self.assertTrue(saved['speaker_notes'].startswith('【待教師確認】'))
            self.assertEqual(result['heading'], saved['heading'])
            self.assertIn('1', pipeline.teacher_checks(out))
            self.assertFalse((out / 'quality-warnings.json').exists())
            self.assertEqual(logged.call_args.args[0], 'draft_kept_for_check')
            report = json.loads((out / 'qa-report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['pages']['1']['final'], 'warning')

    def test_page_with_a_real_content_error_still_falls_back_to_source_text(self):
        bad = slide(body=dict(BODY, bullets=['2 + 3 = 6'], question='', answer=''))
        with tempfile.TemporaryDirectory() as folder:
            out = make_job(folder, bad)
            pipeline.fallback_page(REQUEST, out, 0, '算式錯誤')
            self.assertIn('1', json.loads((out / 'quality-warnings.json').read_text(encoding='utf-8')))
            self.assertEqual(pipeline.teacher_checks(out), {})

    def test_review_that_rejects_twice_keeps_the_page_and_drops_the_flagged_diagram(self):
        diagram = {'type': 'concept_map', 'title': '', 'root': '重點',
                   'children': [{'label': '比例尺', 'example': '1:5000 → 1cm=5', 'note': '先統一單位'}]}
        good = slide(subheading='', body=dict(BODY, bullets=['放大後邊長變倍數，角度不變。']), visual_model=diagram)
        issues = ['visual_model中比例尺例子「1:5000 → 1cm=5」數值錯誤']
        with tempfile.TemporaryDirectory() as folder:
            out = make_job(folder, good)
            item = json.loads((out / 'plan.json').read_text(encoding='utf-8'))['slides'][0]
            with patch.object(pipeline, 'log_event') as logged:
                pipeline.settle_after_review(REQUEST, out, 0, item, good, issues, [])
            saved = json.loads((out / 'slides' / '001.json').read_text(encoding='utf-8'))
            self.assertNotIn('visual_model', saved)
            self.assertIn('1cm=5', saved['speaker_notes'])
            self.assertIn('有疑問的圖解已移除', saved['speaker_notes'])
            self.assertIn('1', pipeline.teacher_checks(out))
            self.assertFalse((out / 'quality-warnings.json').exists())
            self.assertEqual(logged.call_args.args[0], 'review_unresolved')
            self.assertTrue(logged.call_args.kwargs['visual_dropped'])

    def test_review_feedback_forbids_keeping_the_quoted_wrong_text(self):
        text = pipeline.review_feedback(['比例尺例子「1:5000 → 1cm=5」數值錯誤'])
        self.assertIn('不可再出現「1:5000 → 1cm=5」', text)
        self.assertIn('visual_model', text)

    def test_teacher_check_is_cleared_when_the_page_is_regenerated(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            pipeline.mark_teacher_check(out, 2, 'x', ['ghost_image'])
            pipeline.clear_teacher_check(out, 2)
            self.assertEqual(pipeline.teacher_checks(out), {})


class MessageTest(unittest.TestCase):
    def test_each_message_says_cause_and_what_was_done(self):
        qa_text = describe({'event': 'qa_rejected', 'codes': ['truncated'], 'hard': 1, 'soft': 0})
        self.assertIn('句子沒有寫完', qa_text)
        self.assertIn('已請模型', qa_text)
        fallback = describe({'event': 'fallback_page_created', 'reason': '句子似乎在中途被截斷'})
        self.assertIn('原文', fallback)
        self.assertIn('請老師', fallback)
        review = describe({'event': 'review_rejected', 'issue_count': 1, 'issues': ['標題不完整']})
        self.assertIn('再審一次', review)
        kept = describe({'event': 'draft_kept_for_check', 'codes': ['ghost_image']})
        self.assertIn('待教師確認', kept)

    def test_image_message_is_about_the_image_service_not_the_text_model(self):
        text = describe({'event': 'image_generation_unavailable',
                         'reason': "HTTPConnectionPool(host='127.0.0.1', port=7860): Max retries exceeded [WinError 10061]"})
        self.assertIn('生圖', text)
        self.assertIn('不受影響', text)
        self.assertNotIn('模型服務已啟動', text)

    def test_plain_reason_translates_known_failures(self):
        self.assertEqual(plain_reason('文字提到圖，但本頁沒有圖'), '文字提到圖，頁面卻沒有圖')
        self.assertEqual(plain_reason('本地 AI 單次修復後審核仍未通過：[...]'), '審核員仍有疑問')


class LocalImageTest(unittest.TestCase):
    def test_disabled_unless_config_says_true(self):
        with patch.object(local_images.yaml, 'safe_load', return_value={}):
            self.assertFalse(local_images.enabled())
        with patch.object(local_images.yaml, 'safe_load', return_value={'image_generation_enabled': True}):
            self.assertTrue(local_images.enabled())
        with patch.object(local_images.yaml, 'safe_load', return_value={'image_generation_enabled': 'false'}):
            self.assertFalse(local_images.enabled())

    def test_shipped_config_is_on_only_with_a_start_path_and_the_installer_package_keeps_it_off(self):

        if local_images.enabled():
            config = local_images._config()
            self.assertTrue(str(config.get('image_generation_python') or '').strip())
            self.assertTrue(str(config.get('image_generation_launcher') or '').strip())
        build = (Path(__file__).resolve().parents[1] / 'build_installer.ps1').read_text(encoding='utf-8')
        self.assertIn('image_generation_enabled: false', build)

    def test_unavailable_reason_is_plain_chinese_without_urls(self):
        raw = "HTTPConnectionPool(host='127.0.0.1', port=7860): Max retries exceeded (WinError 10061)"
        text = local_images.explain_unavailable(raw)
        self.assertIn('沒有開啟', text)
        self.assertNotIn('HTTPConnectionPool', text)
        self.assertIn('逾時', local_images.explain_unavailable('Read timed out'))


if __name__ == '__main__':
    unittest.main()