"""Automatic beautify pass and final visual QA (deterministic, no model; LibreOffice test skips if absent)."""
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from tests.sample_ratio_deck import sample_deck
from workflow_v2 import beautify, visual_qa
from workflow_v2.renderer import render
from workflow_v2.template_styles import style_for, theme, contrast, BANDS

ROOT = Path(__file__).resolve().parents[1]
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def deck_for(grade, subject):
    deck = sample_deck()
    deck['deck_meta'].update(subject=subject, grade=grade)
    deck['deck_meta'].pop('template_id', None)
    return deck


class StyleTest(unittest.TestCase):
    def test_every_grade_and_subject_is_readable(self):
        for grade in range(1, 10):
            for subject in ('國語', '數學', '英語', '自然'):
                style = style_for(grade, subject)
                report = beautify.palette_report(style)
                self.assertGreaterEqual(min(report.values()), 4.5, (grade, subject, report))
                self.assertGreaterEqual(report['ink-on-paper'], 12)

    def test_style_follows_age_band_and_subject_and_is_deterministic(self):
        self.assertEqual({k: v for k, v in style_for(5, '數學').items() if k != 'grade'},
                         {k: v for k, v in style_for(6, '數學').items() if k != 'grade'})
        self.assertNotEqual(style_for(5, '數學')['primary'], style_for(5, '國語')['primary'])
        self.assertNotEqual(style_for(5, '數學')['primary'], style_for(5, '英語')['primary'])
        sizes = [style_for(g, '數學')['title_max'] for g in (2, 4, 6, 8)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertGreaterEqual(min(sizes), 36)
        self.assertEqual(theme('g6-math-diagram'), theme(None))
        self.assertEqual(style_for(None, None)['id'], 'default')
        self.assertEqual(set(BANDS), {'low', 'mid', 'high', 'junior'})

    def test_contrast_helper_matches_wcag(self):
        self.assertAlmostEqual(contrast('000000', 'FFFFFF'), 21.0, places=1)
        self.assertAlmostEqual(contrast('777777', 'FFFFFF'), 4.48, places=1)


class RenderPolishTest(unittest.TestCase):
    def render(self, grade=6, subject='數學', media=None, sources=None, deck=None):
        folder = tempfile.mkdtemp()
        target = Path(folder) / 'deck.pptx'
        deck = deck or deck_for(grade, subject)
        render(deck, target, media=media, sources=sources, grade=grade)
        return target, Presentation(target), deck

    def test_every_slide_has_bar_icon_and_page_number(self):
        _, prs, deck = self.render()
        total = len(prs.slides)
        for number, slide in enumerate(prs.slides, 1):
            texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
            self.assertIn(f'{number} / {total}', texts, number)
            names = [s.shape_type for s in slide.shapes]
            self.assertGreaterEqual(len(names), 5)

    def test_runs_carry_their_own_size_colour_and_east_asian_font(self):
        _, prs, _ = self.render()
        for slide in prs.slides:
            for run in slide._element.iter(A + 'r'):
                rpr = run.find(A + 'rPr')
                self.assertIsNotNone(rpr)
                self.assertIsNotNone(rpr.get('sz'), run.find(A + 't').text)
                if rpr.find(A + 'latin') is not None:
                    self.assertIsNotNone(rpr.find(A + 'ea'))
                self.assertEqual(rpr.get('lang'), 'zh-TW')

    def test_no_empty_placeholders_are_left_behind(self):
        _, prs, _ = self.render()
        for slide in prs.slides:
            for shape in slide.placeholders:
                self.assertTrue(shape.text_frame.text.strip(), shape.name)

    def test_one_short_statement_becomes_a_key_point_card(self):
        deck = deck_for(6, '數學')
        slide = deck['slides'][3]
        slide.pop('visual_model')
        slide['key_sentence'] = ''
        slide['body']['bullets'] = ['前項和後項同時乘同一個數，比的關係不變']
        _, prs, _ = self.render(deck=deck)
        names = [s.name for s in prs.slides[3].shapes]
        self.assertIn('重點卡片', names)
        self.assertIn('引號', names)

    def test_picture_is_cropped_or_framed_and_credited(self):
        folder = Path(tempfile.mkdtemp())
        wide, tall = folder / 'wide.png', folder / 'tall.png'
        Image.new('RGB', (1200, 800), (40, 120, 150)).save(wide)
        Image.new('RGB', (600, 1000), (150, 70, 90)).save(tall)
        source = {'title': '示意圖片', 'artist': '示範作者', 'license': 'CC BY 4.0', 'source_site': 'Wikimedia Commons',
                  'description_url': 'https://example.org/a', 'license_url': 'https://example.org/l'}
        _, prs, _ = self.render(media={2: str(wide), 4: str(tall)}, sources={'2': source, '4': source})
        pictures = {n: [s for s in prs.slides[n - 1].shapes if s.name == '教學圖片'] for n in (2, 4)}
        self.assertEqual(len(pictures[2]), 1)
        near = pictures[2][0]
        self.assertTrue(near.crop_left > 0 or near.crop_top > 0)
        tall_pic = pictures[4][0]
        self.assertEqual((tall_pic.crop_left, tall_pic.crop_top), (0, 0))
        self.assertIn('圖片底板', [s.name for s in prs.slides[3].shapes])
        credit = next(s for s in prs.slides[1].shapes if s.name == '圖片來源')
        size = credit.text_frame.paragraphs[0].runs[0].font.size.pt
        self.assertGreaterEqual(size, 9)
        self.assertLessEqual((credit.top + credit.height) / 914400, 7.5)
        self.assertIn('示範作者', credit.text_frame.text)

    def test_rendering_is_deterministic(self):
        def slides(path):
            with zipfile.ZipFile(path) as z:
                return {n: z.read(n) for n in sorted(z.namelist()) if n.startswith('ppt/slides/slide')}
        first, _, _ = self.render(5, '國語')
        second, _, _ = self.render(5, '國語')
        self.assertEqual(slides(first), slides(second))

    def test_every_grade_and_subject_renders_inside_the_slide(self):
        for grade, subject in ((4, '國語'), (6, '數學'), (9, '英語')):
            _, prs, _ = self.render(grade, subject)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.left is None:
                        continue
                    self.assertGreaterEqual(shape.left, 0)
                    self.assertGreaterEqual(shape.top, 0)
                    self.assertLessEqual(shape.left + shape.width, prs.slide_width + 10)
                    self.assertLessEqual(shape.top + shape.height, prs.slide_height + 10)


def synthetic(case):
    """(pptx path, pdf path) for one defect case: a one-slide deck whose PDF is drawn by hand."""
    folder = Path(tempfile.mkdtemp())
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text_frame.text = '' if case == 'blank' else 'Hello world teaching text'
    if case != 'blank':
        run = box.text_frame.paragraphs[0].runs[0]
        run.font.size = Pt(28)
        run.font.color.rgb = RGBColor(0x20, 0x20, 0x20)
    prs.save(folder / '教材.pptx')
    pdf = pymupdf.open()
    page = pdf.new_page(width=960, height=540)
    left, top = 72, 72
    if case == 'ok':
        page.insert_text((left, top + 30), 'Hello world teaching text', fontsize=28, color=(.12, .12, .12))
    elif case == 'overflow':
        page.insert_text((left, top + 30), 'Hello world', fontsize=28)
        page.insert_text((left, top + 200), 'teaching text spills far below the box', fontsize=28)
    elif case == 'contrast':
        page.insert_text((left, top + 30), 'Hello world teaching text', fontsize=28, color=(.93, .93, .93))
    elif case == 'offslide':
        page.insert_text((900, top + 30), 'Hello world teaching text', fontsize=28)
    elif case == 'blank':
        pass
    pdf.save(folder / '教材.pdf')
    return folder


class VisualQaTest(unittest.TestCase):
    def codes(self, case):
        folder = synthetic(case)
        found = visual_qa.analyze(folder / '教材.pptx', folder / '教材.pdf')
        return folder, found, {i['code'] for i in found['issues']}

    def test_clean_page_has_no_findings(self):
        folder, found, codes = self.codes('ok')
        self.assertEqual(codes, set(), found)

    def test_each_defect_is_found(self):
        self.assertIn('text_overflow', self.codes('overflow')[2])
        self.assertIn('low_contrast', self.codes('contrast')[2])
        self.assertIn('off_slide', self.codes('offslide')[2])
        self.assertIn('blank_page', self.codes('blank')[2])

    def test_messages_are_plain_chinese(self):
        for case in ('overflow', 'contrast', 'offslide', 'blank'):
            for issue in self.codes(case)[1]['issues']:
                self.assertRegex(issue['message'], r'[\u4e00-\u9fff]')

    def test_overlapping_words_are_found(self):
        folder = synthetic('ok')
        pdf = pymupdf.open()
        page = pdf.new_page(width=960, height=540)
        page.insert_text((72, 100), 'Hello world teaching text', fontsize=28)
        page.insert_textbox(pymupdf.Rect(80, 80, 600, 130), 'Another overlapping sentence', fontsize=28)
        pdf.save(folder / 'overlap.pdf')
        found = visual_qa.analyze(folder / '教材.pptx', folder / 'overlap.pdf')
        self.assertIn('text_overlap', {i['code'] for i in found['issues']})

    def test_fixes_shrink_text_and_restore_contrast(self):
        folder, found, _ = self.codes('contrast')
        fixes = [i for i in found['issues'] if i['code'] == 'low_contrast']
        self.assertTrue(fixes and fixes[0]['shape_id'])
        fixes[0]['background'] = 'FFFFFF'

        deck = Presentation(folder / '教材.pptx')
        run = deck.slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
        run.font.color.rgb = RGBColor(0xEE, 0xEE, 0xEE)
        deck.save(folder / '教材.pptx')
        self.assertGreaterEqual(visual_qa.apply_fixes(folder / '教材.pptx', fixes), 1)
        after = Presentation(folder / '教材.pptx').slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
        self.assertGreaterEqual(contrast(str(after.font.color.rgb), 'FFFFFF'), 4.5)
        overflow = [i for i in self.codes('overflow')[1]['issues'] if i['code'] == 'text_overflow']
        folder2 = synthetic('overflow')
        before = Presentation(folder2 / '教材.pptx').slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt
        self.assertGreaterEqual(visual_qa.apply_fixes(folder2 / '教材.pptx', overflow), 1)
        shrunk = Presentation(folder2 / '教材.pptx').slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt
        self.assertLess(shrunk, before)
        self.assertGreaterEqual(shrunk, 14)

    def test_run_reports_remaining_problems_without_touching_words(self):
        folder = synthetic('blank')
        calls = []
        report = visual_qa.run(folder, lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(report['remaining_pages'], [1])
        self.assertEqual(report['remaining'][0]['code'], 'blank_page')
        self.assertTrue((folder / 'visual-qa.json').is_file())

    def test_pipeline_runs_the_check_after_the_preview_and_never_blocks(self):
        from workflow_v2 import pipeline
        self.assertIs(pipeline.HANDLERS['preview'], pipeline.preview_stage)
        folder = Path(tempfile.mkdtemp()) / ('a' * 32)
        folder.mkdir()
        events = []
        with patch.object(pipeline, 'preview', lambda request, out: None), \
                patch.object(pipeline, 'log_event', lambda name, *a, **k: events.append(name)), \
                patch('workflow_v2.visual_qa.run', side_effect=RuntimeError('boom')):
            pipeline.preview_stage({}, folder)
        self.assertEqual(events, ['visual_qa_failed'])


def soffice_available():
    try:
        from workflow_v2.office import executable
        executable()
        return True
    except Exception:
        return False


@unittest.skipUnless(soffice_available(), 'LibreOffice is not installed')
class EndToEndTest(unittest.TestCase):
    def test_real_deck_passes_the_visual_check_for_three_styles(self):
        from workflow_v2.office import convert_pdf
        for grade, subject in ((4, '國語'), (6, '數學'), (8, '英語')):
            folder = Path(tempfile.mkdtemp())
            render(deck_for(grade, subject), folder / '教材.pptx', grade=grade)
            convert_pdf(folder / '教材.pptx', folder)
            report = visual_qa.run(folder, lambda: convert_pdf(folder / '教材.pptx', folder))
            self.assertEqual(report['checked_pages'], 12)
            self.assertEqual(report['remaining'], [], (grade, subject, report['remaining']))


if __name__ == '__main__':
    unittest.main()
