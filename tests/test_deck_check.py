"""Age bands, whole-deck validation and image-credit lines (no model, no network)."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from workflow_v2 import age_bands, deck_check, images, pipeline
from tests.test_design_system import sample_deck
from tests.test_workflow_v2 import REQUEST


class AgeBandTest(unittest.TestCase):
    def test_grades_map_to_four_bands(self):
        self.assertEqual([age_bands.band_key(g) for g in range(1, 10)],
                         ['low', 'low', 'mid', 'mid', 'high', 'high', 'junior', 'junior', 'junior'])
        for bad in (0, 10, 'x', None):
            with self.assertRaises(ValueError):
                age_bands.band_key(bad)

    def test_limits_grow_with_age_and_are_consistent(self):
        previous = 0
        for key in ('low', 'mid', 'high', 'junior'):
            band = age_bands.BANDS[key]
            low, high = band['body_target']
            self.assertLess(low, high)
            self.assertLessEqual(high, band['body_max'])
            self.assertGreater(band['body_max'], previous)
            previous = band['body_max']
            for field in ('tone', 'interaction', 'notes', 'label'):
                self.assertTrue(band[field].strip())

    def test_page_prompt_uses_the_band_not_a_fixed_number(self):
        source = {'chunks': [{'page': 1, 'text': '分數的意義。'}]}
        item = {'phase': 'example', 'stage': '計算', 'difficulty': '低難度', 'source_pages': [1]}
        texts = {}
        for grade in (4, 6, 8):
            with tempfile.TemporaryDirectory() as temp:
                texts[grade] = pipeline.page_prompt(dict(REQUEST, grade=grade), {'objectives': ['x']}, item, source, Path(temp))
        self.assertIn(age_bands.length_rule(4), texts[4])
        self.assertIn(age_bands.length_rule(6), texts[6])
        self.assertIn(age_bands.length_rule(8), texts[8])
        self.assertIn(age_bands.interaction_rule(8), texts[8])
        self.assertNotEqual(texts[4], texts[6])

    def test_system_prompt_carries_the_band_tone(self):
        from workflow_v2.pedagogy import system_prompt
        self.assertIn(age_bands.band_for(4)['tone'], system_prompt(dict(REQUEST, grade=4)))
        self.assertIn(age_bands.band_for(9)['tone'], system_prompt(dict(REQUEST, grade=9)))

    def test_density_flags_long_text_by_band(self):
        slide = {'layout_id': 'Text_Visual', 'heading': '分數', 'body': {'bullets': ['這是一段文字。' * 15]}}
        self.assertTrue(any(code == 'too_long' for code, _ in age_bands.density_findings(slide, 4)))
        self.assertFalse(any(code == 'too_long' for code, _ in age_bands.density_findings(slide, 9)))
        self.assertEqual(age_bands.density_findings('not a slide', 4)[0][0], 'malformed')


def clean_deck(grade=6):
    deck = copy.deepcopy(sample_deck())
    for slide in deck['slides']:
        slide['speaker_notes'] = '講解約 40 秒，提問：你看到什麼？停 20 秒。'
    return deck


class DeckCheckTest(unittest.TestCase):
    def codes(self, report, severity=None):
        return {f['code'] for f in report['findings'] if severity in (None, f['severity'])}

    def test_clean_deck_has_no_major_findings(self):
        report = deck_check.check_deck(clean_deck(), dict(REQUEST, grade=6))
        self.assertEqual(report['major'], 0, report['findings'])

    def test_empty_heading_and_empty_slide_are_major(self):
        deck = clean_deck()
        deck['slides'][2]['heading'] = '  '
        deck['slides'][2]['body'] = {'bullets': [], 'columns': [], 'question': '', 'answer': '', 'code_snippet': {'language': '', 'code': ''}}
        deck['slides'][2]['modules'] = []
        report = deck_check.check_deck(deck, dict(REQUEST, grade=6))
        self.assertTrue({'empty_heading', 'empty_slide'} <= self.codes(report, 'major'))
        self.assertIn(3, report['pages_with_major'])

    def test_placeholder_text_is_major_but_math_ellipsis_is_allowed(self):
        deck = clean_deck()
        deck['slides'][2]['body']['bullets'] = ['2, 4, 6, …']
        self.assertNotIn('placeholder', self.codes(deck_check.check_deck(deck, dict(REQUEST, grade=6))))
        deck['slides'][2]['body']['bullets'] = ['詳細步驟見備註']
        self.assertIn('placeholder', self.codes(deck_check.check_deck(deck, dict(REQUEST, grade=6)), 'major'))

    def test_overlong_notes_timing_duplicates_and_page_cap(self):
        deck = clean_deck()
        deck['slides'][2]['body']['bullets'] = ['很長的一句話。' * 40]
        deck['slides'][3]['speaker_notes'] = ''
        deck['slides'][4]['speaker_notes'] = '只有講解，沒有時間。'
        deck['slides'][5]['heading'] = deck['slides'][4]['heading']
        found = self.codes(deck_check.check_deck(deck, dict(REQUEST, grade=4)))
        self.assertTrue({'too_long', 'no_notes', 'notes_no_timing', 'duplicate_heading'} <= found)
        big = {'slides': [copy.deepcopy(deck['slides'][2]) for _ in range(51)]}
        self.assertIn('too_many_pages', self.codes(deck_check.check_deck(big, dict(REQUEST, grade=6)), 'major'))

    def test_fallback_pages_do_not_need_timing_notes(self):
        deck = clean_deck()
        deck['slides'][3]['speaker_notes'] = '未經 AI 審核；完整原文在此。'
        self.assertNotIn('notes_no_timing', self.codes(deck_check.check_deck(deck, dict(REQUEST, grade=6))))

    def test_every_picture_needs_a_complete_credit(self):
        deck = clean_deck()
        good = {'title': 'Cat', 'license': 'CC BY 4.0', 'artist': 'Ann', 'description_url': 'https://x.test/a', 'source_site': 'Openverse'}
        no_artist = dict(good, artist='')
        report = deck_check.check_deck(deck, dict(REQUEST, grade=6), sources={'3': good, '4': no_artist}, media={3: 'a.png', 4: 'b.png', 5: 'c.png', 6: 'd.png'})
        majors = [(f['page'], f['code']) for f in report['findings'] if f['severity'] == 'major']
        self.assertNotIn((3, 'attribution_incomplete'), majors)
        self.assertIn((4, 'attribution_incomplete'), majors)
        self.assertIn((5, 'image_no_credit'), majors)
        generated = deck_check.check_attribution(7, {'generated': True, 'title': '本機 AI 生成插圖'})
        self.assertEqual(generated, [])
        cc0 = deck_check.check_attribution(8, {'license': 'CC0 1.0', 'artist': '', 'description_url': 'https://x.test'})
        self.assertEqual(cc0, [])
        proprietary = deck_check.check_attribution(9, {'license': 'All rights reserved', 'artist': 'x', 'description_url': 'https://x.test'})
        self.assertEqual(proprietary[0]['severity'], 'major')

    def test_validation_report_is_written_by_the_pipeline_and_never_raises(self):
        from workflow_v2.store import atomic
        import json
        deck = clean_deck()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / ('a' * 32)
            out.mkdir()
            with patch.object(pipeline, 'log_event'):
                report = pipeline.validate_rendered_deck(dict(REQUEST, grade=6), out, deck, {}, {})
            self.assertEqual(json.loads((out / 'deck-validation.json').read_text(encoding='utf-8'))['pages'], len(deck['slides']))
            self.assertEqual(report['major'], 0)
            with patch.object(pipeline, 'log_event'):
                self.assertIsNone(pipeline.validate_rendered_deck(dict(REQUEST, grade=6), out, 'broken', {}, {}))


class CreditLineTest(unittest.TestCase):
    def test_line_skips_empty_parts_and_never_leaves_creator_blank(self):
        line = images.credit_line({'title': 'Cat on sofa', 'artist': '', 'license': 'CC BY 4.0', 'source_site': 'Openverse'})
        self.assertEqual(line, '圖片：Cat on sofa｜作者未標示｜CC BY 4.0｜Openverse')
        self.assertNotIn('｜｜', line)

    def test_html_in_creator_is_removed_and_generated_image_is_labelled(self):
        line = images.credit_line({'title': 'Dog', 'artist': '<a href="x">Bob</a>', 'license': 'CC0 1.0'})
        self.assertIn('Bob', line)
        self.assertNotIn('<', line)
        self.assertTrue(line.endswith('Wikimedia Commons'))
        self.assertEqual(images.credit_line({'generated': True}), '圖片：本機 AI 生成')

    def test_attribution_text_is_used_when_creator_is_missing(self):
        line = images.credit_line({'title': 'T', 'artist': '', 'attribution': '"T" by Zed is licensed', 'license': 'CC BY 2.0', 'source_site': 'Openverse'})
        self.assertIn('Zed', line)


if __name__ == '__main__':
    unittest.main()