"""Stage time limits grow with the deck so a long deck is not killed halfway."""
import unittest

from workflow_v2 import worker
from workflow_v2.monitor_report import explain_error
from workflow_v2.store import STAGES


class StageTimeoutTest(unittest.TestCase):
    def test_never_below_the_base_and_grows_with_pages(self):
        for stage in STAGES:
            previous = 0
            for pages in (8, 12, 30, 50):
                value = worker.stage_timeout(stage, {'slide_count': pages})
                self.assertGreaterEqual(value, worker.TIMEOUTS[stage], (stage, pages))
                self.assertGreaterEqual(value, previous, (stage, pages))
                previous = value

    def test_fifty_page_deck_gets_room_for_every_slow_stage(self):
        request = {'slide_count': 50}
        self.assertGreaterEqual(worker.stage_timeout('write', request), 50 * 120)
        self.assertGreaterEqual(worker.stage_timeout('review', request), 50 * 90)
        self.assertGreaterEqual(worker.stage_timeout('publish', request), 1500)
        self.assertGreaterEqual(worker.stage_timeout('preview', request), 400)

    def test_short_deck_keeps_the_original_limits(self):
        self.assertEqual(worker.stage_timeout('write', {'slide_count': 12}), 3600)
        self.assertEqual(worker.stage_timeout('publish', {'slide_count': 12}), 600)

    def test_bad_request_values_do_not_crash(self):
        self.assertEqual(worker.stage_timeout('write', {}), 3600)
        self.assertEqual(worker.stage_timeout('write', {'slide_count': 0}), 3600)

    def test_every_stage_has_a_chinese_name_and_the_timeout_message_is_explained(self):
        self.assertEqual(set(worker.STAGE_NAMES), set(STAGES))
        message = f"階段超時：{worker.STAGE_NAMES['write']}（60 分鐘內未完成）"
        self.assertIn('逾時', explain_error(message))


if __name__ == '__main__':
    unittest.main()