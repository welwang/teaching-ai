"""One built-in design: the grade/subject templates are gone, old data must still render."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation

from tests.test_design_system import sample_deck
from workflow_v2.contracts import VISUAL_STYLE, validate_slide
from workflow_v2.renderer import render, route_visual_pages, make_template
from workflow_v2.template_styles import theme
from workflow_v2.worker import source_changed

ROOT = Path(__file__).resolve().parents[1]


class DefaultDesignTest(unittest.TestCase):
    def test_theme_is_always_the_default_and_ignores_legacy_ids(self):
        base = theme(None)
        self.assertEqual(base['id'], 'default')
        for legacy in ('g6-math-diagram', 'g4-chinese-story', 'not-a-template'):
            self.assertEqual(theme(legacy), base)
        base['primary'] = 'FFFFFF'
        self.assertNotEqual(theme(None)['primary'], 'FFFFFF')

    def test_master_is_drawn_in_memory_not_loaded_from_a_file(self):
        canvas = make_template('g6-math-diagram')
        self.assertTrue(hasattr(canvas, 'read') and not isinstance(canvas, (str, Path)))
        self.assertFalse((ROOT / 'assets' / 'workflow-v2' / 'template.pptx').exists())
        self.assertFalse((ROOT / 'assets' / 'workflow-v2' / 'design-cache').exists())
        self.assertFalse((ROOT / 'assets' / 'workflow-v2' / 'templates').exists())
        self.assertFalse((ROOT / 'assets' / 'workflow-v2' / 'template-previews').exists())

    def test_old_deck_with_template_id_still_renders_with_the_default_look(self):
        for legacy in (None, 'g6-math-diagram', 'g9-english-focus'):
            deck = sample_deck()
            if legacy:
                deck['deck_meta']['template_id'] = legacy
            else:
                deck['deck_meta'].pop('template_id', None)
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'deck.pptx'
                report = render(deck, target)
                self.assertTrue(target.exists())
                self.assertEqual({row['template_id'] for row in report}, {'math-high'})
                self.assertEqual(len(Presentation(target).slides), len(deck['slides']))

    def test_section_handles_schema_maximum_description(self):
        deck = sample_deck()
        deck['slides'][1]['modules'][0]['description'] = '保留來源全部條件並且用自己的話說明理解' * 2
        self.assertLessEqual(len(deck['slides'][1]['modules'][0]['description']), 45)
        with tempfile.TemporaryDirectory() as folder:
            render(deck, Path(folder) / 'section.pptx')

    def test_visual_request_reflows_cards_without_dropping_content(self):
        deck = sample_deck()
        card = deck['slides'][4]
        original = [part['description'] for part in card['modules']]
        card['visual_asset'] = {'is_required': True, 'reasoning': '用具體場景輔助認識分類',
                                'asset_type': 'illustration', 'image_prompt': 'Three different colorful doors',
                                'style_tags': VISUAL_STYLE}
        validate_slide(card, {1})
        result = route_visual_pages(deck)
        page = result['slides'][4]
        self.assertEqual(page['layout_id'], 'Text_Visual')
        for text in original:
            self.assertIn(text, '\n'.join(page['body']['bullets']))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'deck.pptx'
            render(result, path)
            slide = Presentation(path).slides[4]
            self.assertNotIn('插圖預留區', ' '.join(s.text for s in slide.shapes if s.has_text_frame))

    def test_source_fingerprint_detects_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'book.txt'
            source.write_text('A', encoding='utf-8')
            job = root / 'job'
            job.mkdir()
            (job / 'source.json').write_text(json.dumps({'sha256': hashlib.sha256(b'A').hexdigest()}), encoding='utf-8')
            self.assertFalse(source_changed({'source_path': str(source)}, job))
            source.write_text('B', encoding='utf-8')
            self.assertTrue(source_changed({'source_path': str(source)}, job))


class NoTemplateInActivePathTest(unittest.TestCase):
    ACTIVE = ('pipeline.py', 'panel.py', 'panel_style.py', 'panel_view.py', 'console_state.py', 'curriculum_prompts.py',
              'worksheet.py', 'final_optimizer.py')

    def test_removed_modules_are_not_importable_or_referenced(self):
        for name in ('template_selection', 'template_preview', 'rebuild_templates'):
            self.assertFalse((ROOT / 'workflow_v2' / (name + '.py')).exists(), name)
        for name in self.ACTIVE:
            text = (ROOT / 'workflow_v2' / name).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'from \.template_(selection|preview)|import template_|choose_template|rebuild_templates', name)

    def test_visible_console_and_prompts_do_not_offer_templates(self):
        for name in ('panel.py', 'panel_view.py'):
            text = (ROOT / 'workflow_v2' / name).read_text(encoding='utf-8')
            self.assertNotIn('模板', text.replace("舊版選版紀錄", ''), name)
        prompts = (ROOT / 'workflow_v2' / 'curriculum_prompts.py').read_text(encoding='utf-8')
        self.assertNotIn('模板', prompts)

    def test_pipeline_deck_has_no_template_id_and_no_selection_call(self):
        from workflow_v2 import pipeline
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            slides = [{'layout_id': 'Cover', 'heading': 'x'}]
            (out / 'slides').mkdir()
            (out / 'plan.json').write_text(json.dumps({'slides': [{}]}), encoding='utf-8')
            (out / 'slides' / '001.json').write_text(json.dumps(slides[0]), encoding='utf-8')
            value = pipeline.deck({'unit': 'u', 'subject': '數學', 'grade': 6}, out)
            self.assertNotIn('template_id', value['deck_meta'])
            self.assertFalse((out / 'template-selection.json').exists())
            self.assertRegex(value['deck_meta']['primary_color'], r'^#[0-9A-F]{6}$')


if __name__ == '__main__':
    unittest.main()
