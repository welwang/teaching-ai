"""Forge must start even though F:\forge has an xformers wheel that does not match its torch (the 無法找到輸入點 dialog)."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_forge_start import forge_tree
from workflow_v2 import local_images as li

BOOT = Path(li.__file__).with_name('forge_boot.py')


class BootWrapperTest(unittest.TestCase):
    def test_xformers_is_hidden_from_every_importer_and_forge_args_pass_through(self):
        with tempfile.TemporaryDirectory() as t:
            launch = Path(t) / 'launch.py'
            launch.write_text(
                'import importlib.util, sys, json\n'
                'try:\n    import xformers\n    imported = True\nexcept ImportError:\n    imported = False\n'
                'print(json.dumps({"argv": sys.argv[1:], "spec": importlib.util.find_spec("xformers") is None, "imported": imported}))\n',
                encoding='utf-8')
            done = subprocess.run([sys.executable, str(BOOT), str(launch), '--api', '--port', '7860'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(done.stdout.strip().splitlines()[-1])
            self.assertEqual(result, {'argv': ['--api', '--port', '7860'], 'spec': True, 'imported': False})

    def test_spawn_goes_through_the_wrapper_and_keeps_the_disable_flag(self):
        with tempfile.TemporaryDirectory() as t:
            config = forge_tree(t)
            python, launcher = li._paths(config)
            popen = MagicMock()
            popen.return_value.pid = 4321
            with patch.object(li, 'DATA', Path(t) / 'data'), patch.object(li, 'ROOT', Path(t)), \
                    patch.object(li.subprocess, 'Popen', popen), patch.object(li, 'log_event'):
                li._spawn(python, launcher, 7860)
            command = popen.call_args.args[0]
            self.assertEqual(command[:4], [str(python), '-u', str(BOOT), str(launcher)])
            self.assertIn('--disable-xformers', command)
            self.assertEqual(json.loads((Path(t) / 'data' / 'image-service-state.json').read_text(encoding='utf-8'))['pid'], 4321)


class RetryLimitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = forge_tree(self.temp.name)
        self.python = li._paths(self.config)[0]
        patcher = patch.object(li, 'DATA', Path(self.temp.name) / 'data')
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, pid=999999, started=None):
        li.DATA.mkdir(parents=True, exist_ok=True)
        li._save_state({**li._state(), 'pid': pid, 'started': started or time.time(), 'settled': False})

    def test_a_start_that_died_counts_once_and_two_failures_pause_auto_start(self):
        with patch.object(li, 'log_event'):
            self.start()
            self.assertEqual(li.settle_previous_start(self.python, ready=False)['fails'], 1)
            self.assertEqual(li.blocked_reason(), '')
            self.assertEqual(li.settle_previous_start(self.python, ready=False)['fails'], 1)
            self.start()
            self.assertEqual(li.settle_previous_start(self.python, ready=False)['fails'], 2)
        hint = li.blocked_reason()
        self.assertIn('已暫停自動啟動', hint)
        self.assertIn('授權素材', hint)
        self.assertIn('forge-api.err.log', hint)

    def test_no_third_spawn_and_friendly_state_once_paused(self):
        li._save_state({'fails': 2, 'last_fail': time.time(), 'reason': 'Forge 啟動後就結束了', 'settled': True})
        spawn = MagicMock()
        with patch.object(li, '_config', return_value=self.config), patch.object(li, 'probe', return_value={'ready': False}), \
                patch.object(li, '_marker_running', return_value=False), patch.object(li, '_spawn', spawn), patch.object(li, 'log_event'):
            result = li.start_in_background()
            state, text = li.describe(False, self.config)
            ensured = li.ensure_service()
        spawn.assert_not_called()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(state, 'failed')
        self.assertIn('授權素材', text)
        self.assertFalse(ensured['ready'])
        self.assertIn('啟動失敗', ensured['reason'])

    def test_pause_expires_and_a_good_start_resets_the_count(self):
        li._save_state({'fails': 2, 'last_fail': time.time() - li.FAILURE_WINDOW - 5, 'settled': True})
        self.assertEqual(li.blocked_reason(), '')
        li._save_state({'fails': 1, 'pid': 1, 'started': time.time(), 'settled': False})
        self.assertEqual(li.settle_previous_start(self.python, ready=True)['fails'], 0)

    def test_a_start_stuck_behind_an_error_dialog_is_killed_and_counted(self):
        process = MagicMock()
        process.is_running.return_value = True
        process.status.return_value = 'running'
        process.exe.return_value = str(self.python)
        self.start(pid=1234, started=time.time() - li.START_TIMEOUT - 10)
        with patch('psutil.Process', return_value=process), patch.object(li, '_kill') as kill, patch.object(li, 'log_event'):
            value = li.settle_previous_start(self.python, ready=False)
        kill.assert_called_once_with(1234)
        self.assertEqual(value['fails'], 1)
        self.assertIn('錯誤視窗', value['reason'])

        self.start(pid=1234, started=time.time() - 30)
        with patch('psutil.Process', return_value=process), patch.object(li, '_kill') as kill:
            self.assertFalse(li.settle_previous_start(self.python, ready=False)['settled'])
        kill.assert_not_called()

    def test_deck_generation_falls_back_without_retrying_when_paused(self):
        deck = {'slides': [{'layout_id': 'Text_Visual', 'visual_asset': {'is_required': True, 'reasoning': 'x', 'image_prompt': 'a ruler'}}]}
        li._save_state({'fails': 2, 'last_fail': time.time(), 'reason': 'x', 'settled': True})
        out = Path(self.temp.name) / 'job'
        out.mkdir()
        spawn = MagicMock()
        with patch.object(li, '_config', return_value=self.config), patch.object(li, 'probe', return_value={'ready': False, 'reason': 'refused'}), \
                patch.object(li, '_marker_running', return_value=False), patch.object(li, '_spawn', spawn), patch.object(li, 'log_event'):
            media = li.generate_assets(deck, out, start_service=False)
        spawn.assert_not_called()
        self.assertEqual(media, {})
        record = json.loads((out / 'visual-assets.json').read_text(encoding='utf-8'))['1']
        self.assertEqual(record['status'], 'unavailable')
        self.assertIn('授權素材', record['reason'])


if __name__ == '__main__':
    unittest.main()