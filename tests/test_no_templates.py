"""Generated decks are drawn by code: no PowerPoint template file is read, written or shipped."""
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests.test_design_system import sample_deck
from workflow_v2.renderer import render

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_SUFFIXES = ('.potx', '.potm', '.pptx', '.pot', '.thmx')
CODE = [p for p in (ROOT / 'workflow_v2').glob('*.py') if '.bak' not in p.name]


class NoTemplateFilesTest(unittest.TestCase):
    def test_no_template_or_master_file_ships_with_the_app(self):
        found = [str(p.relative_to(ROOT)) for folder in ('assets', 'workflow_v2') for p in (ROOT / folder).rglob('*')
                 if p.suffix.lower() in TEMPLATE_SUFFIXES or p.name in ('layouts.json', 'design-cache')]
        self.assertEqual(found, [])

    def test_rendering_opens_no_template_file_for_any_grade(self):
        opened = []
        real = zipfile.ZipFile.__init__

        def spy(self, file, *args, **kwargs):
            if isinstance(file, (str, Path)):
                opened.append(str(file))
            return real(self, file, *args, **kwargs)

        outputs = []
        for grade in range(1, 10):
            with tempfile.TemporaryDirectory() as folder, mock.patch.object(zipfile.ZipFile, '__init__', spy):
                outputs.append(folder)
                render(sample_deck(), Path(folder) / 'deck.pptx', grade=grade)

        elsewhere = [name for name in opened if 'site-packages' not in name.replace('\\', '/')
                     and not any(name.startswith(folder) for folder in outputs)]
        self.assertEqual(elsewhere, [])

    def test_every_page_has_its_shapes_drawn_by_code(self):
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'deck.pptx'
            render(sample_deck(), path, grade=6)
            self.assertTrue(all(len(slide.shapes) > 2 for slide in Presentation(path).slides))

    def test_code_never_names_a_template_file(self):
        needles = ('.potx', 'template.pptx', 'design-cache', 'layouts.json', 'apply_template', 'import_template')
        for path in CODE:
            text = path.read_text(encoding='utf-8')
            for needle in needles:
                self.assertNotIn(needle, text, f'{path.name} mentions {needle}')

    def test_screens_offer_no_template_choice(self):
        words = re.compile(r'(套用|選擇|選用|挑選|更換|下載)(教學)?(模板|範本|版型)|模板選擇')
        for name in ('panel.py', 'panel_view.py', 'panel_style.py'):
            text = (ROOT / 'workflow_v2' / name).read_text(encoding='utf-8')
            self.assertIsNone(words.search(text), name)


if __name__ == '__main__':
    unittest.main()
