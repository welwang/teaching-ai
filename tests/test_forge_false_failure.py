"""2026-10-05: a Forge that had started and generated images on 10-04 was counted as a failed start
after a reboot (fails=2), so automatic start was paused and no illustrations were made that day."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_forge_start import forge_tree
from workflow_v2 import local_images as li


class FalseFailureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = forge_tree(self.temp.name)
        self.python = li._paths(self.config)[0]
        root = Path(self.temp.name)
        (root / 'logs').mkdir(exist_ok=True)
        self.log = root / 'logs' / 'forge-api.out.log'
        self.log.write_text('old session\nRunning on local URL:  http://127.0.0.1:7860\n', encoding='utf-8')
        for name, value in (('DATA', root / 'data'), ('ROOT', root)):
            patcher = patch.object(li, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.events = patch.object(li, 'log_event').start()
        self.addCleanup(patch.stopall)

    def start(self, pid=999999, started=None):
        li._note_start(pid)
        if started is not None:
            li._save_state({**li._state(), 'started': started})

    def test_a_start_that_became_ready_and_was_closed_is_not_a_failure(self):
        self.start()
        with self.log.open('a', encoding='utf-8') as handle:
            handle.write('Startup time: 11.3s\nRunning on local URL:  http://127.0.0.1:7860\n')
        value = li.settle_previous_start(self.python, ready=False)
        self.assertTrue(value['settled'])
        self.assertEqual(value.get('fails', 0), 0)
        self.assertEqual(li.blocked_reason(), '')

    def test_an_old_ready_line_from_an_earlier_session_does_not_count(self):
        self.start()
        value = li.settle_previous_start(self.python, ready=False)
        self.assertEqual(value['fails'], 1)
        self.assertIn('forge-api.err.log', value['reason'])

    def test_a_start_from_before_the_last_reboot_is_not_a_failure(self):
        self.start(started=time.time() - 86400)
        with patch('psutil.boot_time', return_value=time.time() - 3600):
            value = li.settle_previous_start(self.python, ready=False)
        self.assertEqual(value.get('fails', 0), 0)

    def test_the_console_seeing_forge_ready_records_the_good_start(self):
        li._save_state({'fails': 1, 'pid': 5, 'started': time.time(), 'settled': False, 'log_offset': 0})
        state, _ = li.describe(True, self.config)
        self.assertEqual(state, 'ready')
        self.assertEqual(li._state()['fails'], 0)
        self.assertTrue(li._state()['settled'])

    def test_our_shutdown_settles_the_start(self):
        self.start()
        li.mark_stopped_by_us()
        self.assertTrue(li._state()['settled'])
        self.assertEqual(li.settle_previous_start(self.python, ready=False).get('fails', 0), 0)


if __name__ == '__main__':
    unittest.main()
