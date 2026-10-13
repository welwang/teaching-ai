
import contextvars
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tests.sample_ratio_deck import sample_deck
from workflow_v2 import images, pipeline, speedup, timing
from workflow_v2.contracts import slide_schema, validate_slide


def job_folder(root=None):
    root = Path(root or tempfile.mkdtemp())
    folder = root / 'jobs' / ('a' * 32)
    folder.mkdir(parents=True)
    return root, folder


class SharedCacheTest(unittest.TestCase):
    def test_round_trip_ttl_and_damage(self):
        root, _ = job_folder()
        self.assertIsNone(speedup.get(root, 'k', ['a']))
        speedup.put(root, 'k', ['a'], {'x': 1})
        self.assertEqual(speedup.get(root, 'k', ['a']), {'x': 1})
        self.assertIsNone(speedup.get(root, 'k', ['b']))
        self.assertIsNone(speedup.get(root, 'k', ['a'], ttl=10, now=time.time() + 11))
        next((root / 'cache' / 'k').glob('*.json')).write_text('{broken', encoding='utf-8')
        self.assertIsNone(speedup.get(root, 'k', ['a']))

    def test_only_real_job_folders_have_a_cache_and_old_files_are_pruned(self):
        root, folder = job_folder()
        self.assertEqual(speedup.root_of(folder), root)
        self.assertIsNone(speedup.root_of(root / 'scratch' / 'x'))
        self.assertIsNone(speedup.get(None, 'k', 1))
        speedup.put(None, 'k', 1, 2)
        for i in range(7):
            speedup.put(root, 'p', i, i)
        speedup.prune(root, 'p', limit=3)
        self.assertEqual(len(list((root / 'cache' / 'p').glob('*.json'))), 3)

    def test_parallel_is_bounded_ordered_and_keeps_the_callers_context(self):
        var = contextvars.ContextVar('v', default='none')
        var.set('deadline')
        active, peak = [0], [0]
        lock = threading.Lock()

        def work(n):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(.05)
            with lock:
                active[0] -= 1
            if n == 3:
                raise ValueError('bad')
            return (n, var.get())
        results = speedup.parallel(work, range(6), workers=3)
        self.assertEqual([r for r in results if isinstance(r, tuple)], [(0, 'deadline'), (1, 'deadline'), (2, 'deadline'), (4, 'deadline'), (5, 'deadline')])
        self.assertIsInstance(results[3], ValueError)
        self.assertLessEqual(peak[0], 3)
        self.assertGreaterEqual(peak[0], 2)
        self.assertEqual(speedup.parallel(work, [], workers=3), [])


class SharedWorkTest(unittest.TestCase):
    def test_analysis_of_the_same_source_is_reused_by_a_later_job(self):
        root, first = job_folder()
        second = root / 'jobs' / ('b' * 32)
        second.mkdir()
        for folder in (first, second):
            (folder / 'source.json').write_text(json.dumps({'pages': [], 'chunks': [], 'sha256': 'x'}), encoding='utf-8')
        request = dict(model='m', unit='比', grade=6, subject='數學')
        analysis = {'objectives': ['能說出比'], 'core_concepts': [{'name': '比', 'meaning': '兩量關係'}], 'worked_examples': [],
                    'practice_questions': [], 'misconceptions': [], 'life_scenarios': []}
        with patch.object(pipeline, 'call', return_value=analysis) as call, patch.object(pipeline, 'log_event'):
            one = pipeline.analyze(request, first, '{}')
            two = pipeline.analyze(request, second, '{}')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(one, two)

    def test_image_search_is_remembered_across_jobs_and_failures_are_not(self):
        root, folder = job_folder()
        candidate = {'title': 'ball', 'url': 'https://x/ball.png', 'license': 'CC0 1.0'}
        with patch.object(images, 'find_image', return_value=candidate) as find:
            self.assertEqual(images.find_image_cached('ball', root=root), candidate)
            self.assertEqual(images.find_image_cached('ball', root=root), candidate)
        self.assertEqual(find.call_count, 1)
        with patch.object(images, 'find_image', return_value=None) as find:
            images.find_image_cached('nothing here', root=root)
            images.find_image_cached('nothing here', root=root)
        self.assertEqual(find.call_count, 2)

    def test_pictures_for_several_pages_are_looked_up_at_the_same_time(self):
        root, folder = job_folder()
        deck = sample_deck()
        pages = []
        for slide, word in zip((deck['slides'][1], deck['slides'][3], deck['slides'][2]), ('ruler', 'compass', 'scale')):
            slide['layout_id'] = 'Text_Visual'
            slide['media_hint']['search_keyword'] = word
            slide['visual_asset'].update(is_required=True, asset_type='illustration', image_prompt='A ' + word)
            pages.append(slide)
        picture = folder / 'p.png'
        Image.new('RGB', (200, 200), 'teal').save(picture)
        active, peak = [0], [0]
        lock = threading.Lock()

        def slow_find(keyword, session=None):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(.15)
            with lock:
                active[0] -= 1
            return {'title': keyword, 'url': 'https://x/' + keyword, 'license': 'CC0 1.0', 'license_url': images.CC0_URL,
                    'description_url': 'https://x/d', 'source_site': 'Test'}
        started = time.time()
        with patch.object(images, 'find_image', slow_find), patch.object(images, 'download', return_value=picture):
            media = images.online_images({'slides': pages}, folder)
        self.assertEqual(sorted(media), [1, 2, 3])
        self.assertGreaterEqual(peak[0], 2)
        self.assertLess(time.time() - started, 0.15 * 3)


class LeanOutputTest(unittest.TestCase):
    def test_photo_boilerplate_may_be_left_out_and_is_filled_by_the_program(self):
        item = {'layout_id': 'Text_Visual', 'source_pages': [1]}
        full = slide_schema([1], 'Text_Visual', strict=False, grade=6)
        lean = pipeline.lean_schema(full)
        self.assertIn('visual_asset', full['required'])
        self.assertNotIn('visual_asset', lean['required'])
        self.assertNotIn('media_hint', lean['required'])
        for rule in lean.get('allOf', []):
            self.assertNotIn('visual_asset', rule['then'].get('required', []))
        self.assertIn('visual_asset', full['required'])
        slide = sample_deck()['slides'][1]
        slide['source_pages'] = [1]
        for key in ('visual_asset', 'media_hint'):
            slide.pop(key)
        fixed = pipeline.normalize_slide(slide, item)
        self.assertFalse(fixed['visual_asset']['is_required'])
        self.assertEqual(fixed['media_hint'], {'search_keyword': '', 'image_description': ''})
        validate_slide(fixed, [1])
        self.assertEqual(fixed['visual_asset']['style_tags'], pipeline.VISUAL_STYLE)

    def test_a_requested_photo_is_kept(self):
        slide = sample_deck()['slides'][1]
        slide['visual_asset'].update(is_required=True, asset_type='illustration', image_prompt='A cute ruler on a desk')
        slide['media_hint']['search_keyword'] = 'ruler'
        fixed = pipeline.normalize_slide(slide, None)
        self.assertTrue(fixed['visual_asset']['is_required'])
        self.assertEqual(fixed['media_hint']['search_keyword'], 'ruler')

    def test_the_prompt_tells_the_model_it_may_skip_the_photo_fields(self):
        text = Path(pipeline.__file__).read_text(encoding='utf-8')
        self.assertIn('不需要就整個省略', text)
        self.assertNotIn('每頁必填visual_asset', text)


class TimingReportTest(unittest.TestCase):
    def make(self):
        def line(minutes, **fields):
            return json.dumps({'time': f'2026-10-04T02:{minutes:02d}:00.000+00:00', **fields}, ensure_ascii=False) + '\n'
        rows = [line(0, event='stage_started', stage='write'),
                line(0, event='stage_started', stage='plan')]

        for i in range(6):
            prompt, output = (5000, 8200, 6100, 9900, 5600, 7300)[i], (300, 700, 450, 900, 380, 620)[i]
            duration = 2 + prompt / 6000 + output / 70
            rows.append(json.dumps({'time': f'2026-10-04T02:0{i + 1}:30.000+00:00', 'event': 'model_call_finished',
                                    'stage': 'write', 'label': f'編寫第 {i + 1} 頁', 'prompt_tokens': prompt,
                                    'output_tokens': output, 'duration_seconds': duration}) + '\n')
        rows.append(line(9, event='page_retry', stage='write'))
        rows.append(line(10, event='stage_completed', stage='write', duration_seconds=600))
        folder = Path(tempfile.mkdtemp())
        (folder / 'run.jsonl').write_text(''.join(rows), encoding='utf-8')
        return folder

    def test_profile_splits_wall_time_into_model_and_other(self):
        data = timing.profile(self.make())
        row = data['stages']['write']
        self.assertEqual(row['wall'], 600)
        self.assertGreater(row['model'], 30)
        self.assertAlmostEqual(row['wall'], row['model'] + row['idle'], places=0)
        self.assertEqual(data['calls'], 6)
        self.assertEqual(data['rework'], {'page_retry': 1})
        self.assertIn('編寫／修正頁面', row['by_kind'])

    def test_speed_fit_recovers_the_known_rates(self):
        decode, prefill = timing.fit_speed(self.make())
        self.assertAlmostEqual(decode, 70, delta=3)
        self.assertAlmostEqual(prefill, 6000, delta=400)

    def test_report_is_plain_text(self):
        text = timing.report(self.make())
        self.assertIn('write', text)
        self.assertIn('模型', text)


if __name__ == '__main__':
    unittest.main()
