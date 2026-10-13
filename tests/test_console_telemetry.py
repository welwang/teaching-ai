"""監控數值、階段與歷史資料測試。"""
import unittest

from workflow_v2 import console_state as cs


class HelperTest(unittest.TestCase):
    def test_hms(self):
        self.assertEqual(cs.hms(0), '00:00:00')
        self.assertEqual(cs.hms(3725), '01:02:05')
        self.assertEqual(cs.hms(100 * 3600), '100:00:00')
        self.assertEqual(cs.hms(None), '--:--:--')
        self.assertEqual(cs.hms(-5), '00:00:00')

    def test_stage_track_has_seven_steps_and_one_active(self):
        for index, stage in enumerate(cs.STAGES):
            track = cs.stage_track({'stage': stage})
            self.assertEqual(len(track), 7)
            self.assertEqual([c['state'] for c in track].count('active'), 1)
            self.assertEqual(track[index]['state'], 'active')
            self.assertTrue(all(c['state'] == 'done' for c in track[:index]))
            self.assertTrue(all(c['state'] == 'todo' for c in track[index + 1:]))
        self.assertTrue(all(c['state'] == 'todo' for c in cs.stage_track(None)))

    def test_speed_is_whole_job_average_and_none_without_data(self):
        self.assertEqual(cs.speed_per_second({'tokens': {'output_tokens': 600, 'generation_seconds': 20}}), 30)
        self.assertIsNone(cs.speed_per_second({'tokens': {}}))
        self.assertIsNone(cs.speed_per_second(None))

    def test_gpu_numbers(self):
        g = cs.gpu_numbers({'gpu': {'memory_total_mb': 32768, 'memory_used_mb': 16384, 'utilization': 140}})
        self.assertEqual((g['util'], g['percent']), (100, 50))
        self.assertAlmostEqual(g['used_gb'], 16)
        self.assertIsNone(cs.gpu_numbers({'gpu': {'error': 'x'}}))
        self.assertIsNone(cs.gpu_numbers({}))

    def test_history_is_capped_and_clamped(self):
        h = []
        for i in range(200):
            h = cs.push_history(h, i)
        self.assertEqual(len(h), cs.HISTORY_LENGTH)
        self.assertEqual(max(h), 100)
        self.assertEqual(cs.push_history([], -9), [0])


if __name__ == '__main__':
    unittest.main()
