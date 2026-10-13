"""Local image service (Forge): clear status, background start from the launcher, auto-recovery, packaged config."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow_v2 import console_state as cs, local_images as li

ROOT = Path(__file__).resolve().parents[1]


def forge_tree(base):
    base = Path(base)
    (base / 'system' / 'python').mkdir(parents=True)
    (base / 'webui' / 'models' / 'Stable-diffusion').mkdir(parents=True)
    (base / 'system' / 'python' / 'python.exe').write_bytes(b'')
    (base / 'webui' / 'launch.py').write_text('', encoding='utf-8')
    (base / 'webui' / 'models' / 'Stable-diffusion' / 'm.safetensors').write_bytes(b'')
    return {'image_generation_enabled': True, 'image_generation_python': str(base / 'system' / 'python' / 'python.exe'),
            'image_generation_launcher': str(base / 'webui' / 'launch.py')}


class InstallProblemTest(unittest.TestCase):
    def test_each_missing_piece_is_named_in_plain_chinese(self):
        with tempfile.TemporaryDirectory() as t:
            config = forge_tree(t)
            self.assertEqual(li.install_problem(config), '')
            self.assertIn('還沒有設定', li.install_problem({}))
            self.assertIn('找不到生圖程式的 Python', li.install_problem({**config, 'image_generation_python': str(Path(t) / 'x.exe')}))
            self.assertIn('找不到 Forge 的 launch.py', li.install_problem({**config, 'image_generation_launcher': str(Path(t) / 'x.py')}))
            (Path(t) / 'webui' / 'models' / 'Stable-diffusion' / 'm.safetensors').unlink()
            self.assertIn('繪圖模型檔', li.install_problem(config))

    def test_status_sentence_for_every_state(self):
        with tempfile.TemporaryDirectory() as t:
            config = forge_tree(t)
            with patch.object(li, 'DATA', Path(t) / 'data'):
                self.assertEqual(li.describe(False, {**config, 'image_generation_enabled': False})[0], 'off')
                self.assertEqual(li.describe(True, config)[0], 'ready')
                self.assertEqual(li.describe(False, config)[0], 'stopped')
                with patch.object(li, '_marker_running', return_value=True):
                    self.assertEqual(li.describe(False, config)[0], 'starting')
                kind, text = li.describe(False, {**config, 'image_generation_python': ''})
                self.assertEqual(kind, 'missing')
                self.assertIn('授權素材', text)
        for state in ('off', 'ready', 'stopped'):
            self.assertRegex(li.describe(state == 'ready', {'image_generation_enabled': state != 'off'})[1] or '', r'[\u4e00-\u9fff]')


class BackgroundStartTest(unittest.TestCase):
    def run_start(self, config, ready=False, running=False):
        with tempfile.TemporaryDirectory() as t:
            cfg = config(t) if callable(config) else config
            spawn = MagicMock()
            with patch.object(li, '_config', return_value=cfg), patch.object(li, 'DATA', Path(t) / 'data'), \
                    patch.object(li, 'probe', return_value={'ready': ready}), \
                    patch.object(li, '_marker_running', return_value=running), patch.object(li, '_spawn', spawn), \
                    patch.object(li, 'log_event'):
                return li.start_in_background(), spawn

    def test_disabled_missing_ready_and_starting_never_spawn_a_second_copy(self):
        result, spawn = self.run_start({'image_generation_enabled': False})
        self.assertEqual(result['state'], 'off')
        result, spawn = self.run_start({'image_generation_enabled': True})
        self.assertEqual(result['state'], 'missing')
        spawn.assert_not_called()
        result, spawn = self.run_start(forge_tree, ready=True)
        self.assertEqual(result['state'], 'ready')
        spawn.assert_not_called()
        result, spawn = self.run_start(forge_tree, running=True)
        self.assertEqual(result['state'], 'starting')
        spawn.assert_not_called()

    def test_stopped_service_is_started_once_without_waiting(self):
        result, spawn = self.run_start(forge_tree)
        self.assertEqual(result['state'], 'starting')
        spawn.assert_called_once()
        self.assertIn('背景', result['message'])

    def test_a_failed_start_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as t:
            with patch.object(li, '_config', return_value=forge_tree(t)), patch.object(li, 'DATA', Path(t) / 'data'), \
                    patch.object(li, 'probe', return_value={'ready': False}), patch.object(li, '_marker_running', return_value=False), \
                    patch.object(li, '_spawn', side_effect=OSError('denied')), patch.object(li, 'log_event'):
                result = li.start_in_background()
        self.assertEqual(result['state'], 'failed')
        self.assertIn('授權素材', result['message'])

    def test_launcher_starts_forge_but_a_crash_there_never_stops_the_launch(self):
        import launch_v2
        out = io.StringIO()
        with patch.object(li, 'start_in_background', return_value={'state': 'starting', 'message': '已在背景啟動'}), redirect_stdout(out):
            launch_v2.start_image_service()
        self.assertIn('本機生圖：已在背景啟動', out.getvalue())
        out = io.StringIO()
        with patch.object(li, 'start_in_background', side_effect=RuntimeError('boom')), redirect_stdout(out):
            launch_v2.start_image_service()
        self.assertIn('略過', out.getvalue())
        self.assertIn('start_image_service()', (ROOT / 'launch_v2.py').read_text(encoding='utf-8').split('def main')[1])


class HealthRowTest(unittest.TestCase):
    def row(self, config, reachable):
        state = {'worker_alive': True, 'counts': {}, 'job': None, 'gpu': {}}
        with patch.object(li, '_config', return_value=config), patch.object(li, 'enabled', return_value=config.get('image_generation_enabled') is True), \
                patch.object(cs, '_cached', side_effect=lambda key, ttl, producer: {'reachable': reachable} if key == 'image' else {'reachable': True, 'loaded': []}):
            return {r['key']: r for r in cs.service_health(state)}['image']

    def test_panel_says_what_is_wrong_and_what_happens_next(self):
        with tempfile.TemporaryDirectory() as t:
            config = forge_tree(t)
            with patch.object(li, 'DATA', Path(t) / 'data'):
                self.assertEqual(self.row(config, True)['state'], 'ok')
                stopped = self.row(config, False)
                self.assertEqual(stopped['state'], 'off')
                self.assertIn('自動啟動', stopped['detail'])
                missing = self.row({**config, 'image_generation_launcher': str(Path(t) / 'no.py')}, False)
                self.assertEqual(missing['state'], 'warn')
                self.assertIn('找不到 Forge', missing['detail'])


class GenerateFallbackTest(unittest.TestCase):
    def test_when_forge_is_down_it_is_restarted_in_the_background_and_the_deck_continues_with_fallback(self):
        deck = {'slides': [{'layout_id': 'Cover', 'visual_asset': {'is_required': True, 'image_prompt': 'p', 'reasoning': 'r'}}]}
        with tempfile.TemporaryDirectory() as t, patch.object(li, 'probe', return_value={'ready': False, 'reason': '10061'}), \
                patch.object(li, 'describe', return_value=('stopped', '')), patch.object(li, 'install_problem', return_value=''), \
                patch.object(li, 'start_in_background', return_value={'state': 'starting', 'message': '已在背景啟動'}) as start, \
                patch.object(li, 'log_event'):
            media = li.generate_assets(deck, Path(t), {}, start_service=False)
        self.assertEqual(media, {})
        start.assert_called_once()

    def test_a_forge_that_is_still_starting_is_waited_for_instead_of_given_up_on(self):
        deck = {'slides': [{'layout_id': 'Cover', 'visual_asset': {'is_required': True, 'image_prompt': 'p', 'reasoning': 'r'}}]}
        with tempfile.TemporaryDirectory() as t, patch.object(li, 'probe', return_value={'ready': False, 'reason': 'x'}), \
                patch.object(li, 'describe', return_value=('starting', '')), \
                patch.object(li, 'wait_ready', return_value={'ready': False, 'reason': '10061'}) as wait, patch.object(li, 'log_event'):
            li.generate_assets(deck, Path(t), {}, start_service=False)
        wait.assert_called_once()


class PackageTest(unittest.TestCase):
    def test_installer_turns_local_image_generation_off_and_drops_machine_paths(self):
        build = (ROOT / 'build_installer.ps1').read_text(encoding='utf-8')
        self.assertIn('image_generation_enabled: false', build)
        self.assertIn('image_generation_python|image_generation_launcher', build)


if __name__ == '__main__':
    unittest.main()