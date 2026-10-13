
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workflow_v2 import concurrency, engine, model, pipeline
from workflow_v2.store import atomic

BIG = {'utilization': 5, 'memory_used_mb': 2000, 'memory_total_mb': 32607}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target in ('workflow_v2.concurrency.DATA', 'workflow_v2.model.DATA'):
            patcher = patch(target, Path(self.tmp.name))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('workflow_v2.concurrency.log_event')
        self.logged = patcher.start()
        self.addCleanup(patcher.stop)


class DecisionTest(Isolated):
    def test_two_slots_only_when_the_card_is_big_and_free_enough(self):
        self.assertEqual(concurrency.choose_ollama_parallel(BIG, {})[0], 2)
        small = {'memory_used_mb': 1000, 'memory_total_mb': 16000}
        busy = {'memory_used_mb': 20000, 'memory_total_mb': 32607}
        for gpu in (small, busy, {'error': 'x'}):
            slots, why = concurrency.choose_ollama_parallel(gpu, {})
            self.assertEqual(slots, 1)
            self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in why))
        self.assertEqual(concurrency.choose_ollama_parallel(BIG, {'ollama_parallel': 1})[0], 1)

    def test_settings_are_clamped_and_bad_values_ignored(self):
        self.assertEqual(concurrency.settings({'ollama_parallel': 9, 'write_concurrency': 0})['ollama_parallel'], 2)
        self.assertEqual(concurrency.settings({'ollama_parallel': 9, 'write_concurrency': 0})['write_concurrency'], 1)
        self.assertEqual(concurrency.settings({'ollama_parallel': 'abc'})['ollama_parallel'], 2)

    def test_after_a_memory_error_the_service_starts_with_one_slot(self):
        concurrency.degrade('CUDA error: out of memory')
        self.assertEqual(concurrency.choose_ollama_parallel(BIG, {})[0], 1)
        concurrency.reset()
        self.assertEqual(concurrency.choose_ollama_parallel(BIG, {})[0], 2)

    def test_ensure_server_starts_with_the_decided_slots_and_logs_it_in_chinese(self):
        with patch.object(engine, 'listener', return_value=None), patch.object(engine, '_binary', return_value='ollama.exe'), \
                patch.object(engine, 'start_server') as start, patch.object(engine, 'log_event') as logged, \
                patch.object(concurrency, 'choose_ollama_parallel', return_value=(1, '顯存不足')):
            engine.ensure_server()
        start.assert_called_once_with('ollama.exe', 1)
        self.assertIn('顯存不足', logged.call_args.kwargs['message'])
        with patch.object(engine, 'listener', return_value=None), patch.object(engine, '_binary', return_value='ollama.exe'), \
                patch.object(engine, 'start_server') as start:
            engine.ensure_server(1)
        start.assert_called_once_with('ollama.exe', 1)


class WorkersTest(Isolated):
    def test_workers_follow_config_and_the_real_service(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(concurrency, 'server_parallel', return_value=2):
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {'write_concurrency': 2}), 2)
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {'write_concurrency': 1}), 1)
        with patch.dict('os.environ', {}, clear=True), patch.object(concurrency, 'server_parallel', return_value=1):
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {'write_concurrency': 2}), 1)

    def test_operator_override_and_degrade_flag(self):
        with patch.dict('os.environ', {'MAX_PPT_CONCURRENCY': '1'}), patch.object(concurrency, 'server_parallel', return_value=2):
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {}), 1)
        with patch.dict('os.environ', {'MAX_PPT_CONCURRENCY': '2'}):
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {}), 2)
            concurrency.degrade('out of memory')
            self.assertEqual(concurrency.write_workers({'model': 'm'}, {}), 1)

    def test_server_slots_are_read_from_the_running_process(self):
        owner = Mock()
        owner.environ.return_value = {'OLLAMA_NUM_PARALLEL': '2'}
        with patch.object(engine, 'listener', return_value=owner):
            self.assertEqual(concurrency.server_parallel({}), 2)
        owner.environ.return_value = {}
        with patch.object(engine, 'listener', return_value=owner):
            self.assertEqual(concurrency.server_parallel({}), 1)
        with patch.object(engine, 'listener', return_value=None):
            self.assertEqual(concurrency.server_parallel({'ollama_parallel': 2}), 2)

    def test_status_sentence(self):
        with patch.dict('os.environ', {'MAX_PPT_CONCURRENCY': '2'}):
            self.assertIn('同時編寫 2 頁', concurrency.status()[1])
        concurrency.degrade('out of memory')
        self.assertIn('顯存', concurrency.status()[1])


class DegradeTest(Isolated):
    def test_capacity_errors_are_recognised(self):
        for text in ('CUDA error: out of memory', 'cudaMalloc failed', 'llama runner process has terminated: exit status 2',
                     'unable to allocate CUDA0 buffer', 'memory layout cannot be allocated'):
            self.assertTrue(concurrency.is_capacity_error(text), text)
        for text in ('model not found', 'invalid JSON', ''):
            self.assertFalse(concurrency.is_capacity_error(text), text)

    def test_degrade_is_remembered_once_and_logged_in_chinese(self):
        self.assertTrue(concurrency.degrade('out of memory'))
        self.assertFalse(concurrency.degrade('out of memory again'))
        self.assertTrue(concurrency.degraded())
        self.assertEqual(self.logged.call_count, 1)
        self.assertIn('一次只編寫一頁', self.logged.call_args.kwargs['message'])

    def test_a_model_http_500_out_of_memory_triggers_the_fallback(self):
        reply = Mock(ok=False, status_code=500, text='{"error":"CUDA error: out of memory"}')
        with patch.object(model.requests, 'post', return_value=reply), patch.object(model, 'unload_model'), \
                patch.object(model, 'log_event'), patch('workflow_v2.model.time.sleep'):
            with self.assertRaises(RuntimeError):
                model.call('example:m', 'p', {'type': 'object'}, attempts=1)
        self.assertTrue(concurrency.degraded())

    def test_ordinary_errors_do_not_degrade(self):
        reply = Mock(ok=False, status_code=400, text='bad request')
        with patch.object(model.requests, 'post', return_value=reply), patch.object(model, 'log_event'):
            with self.assertRaises(RuntimeError):
                model.call('example:m', 'p', {'type': 'object'}, attempts=1)
        self.assertFalse(concurrency.degraded())

    def test_idle_worker_restarts_the_service_with_one_slot_once(self):
        concurrency.degrade('out of memory')
        with patch.object(concurrency, 'server_parallel', return_value=2), patch.object(engine, 'restart_owned_server') as restart:
            self.assertTrue(concurrency.restart_if_degraded())
            restart.assert_called_once_with(1)
            self.assertFalse(concurrency.restart_if_degraded())
            restart.assert_called_once()

    def test_a_failed_restart_is_retried_later_not_in_a_loop(self):
        concurrency.degrade('out of memory')
        with patch.object(concurrency, 'server_parallel', return_value=2), \
                patch.object(engine, 'restart_owned_server', side_effect=RuntimeError('仍有教材工作執行中')) as restart:
            self.assertFalse(concurrency.restart_if_degraded())
            self.assertFalse(concurrency.restart_if_degraded())
            restart.assert_called_once()
        self.assertIn('稍後會再試', self.logged.call_args.kwargs['message'])

    def test_nothing_to_restart_when_the_service_already_has_one_slot(self):
        concurrency.degrade('out of memory')
        with patch.object(concurrency, 'server_parallel', return_value=1), patch.object(engine, 'restart_owned_server') as restart:
            self.assertFalse(concurrency.restart_if_degraded())
        restart.assert_not_called()


class WriteStageTest(Isolated):
    def test_a_memory_error_in_the_middle_makes_the_rest_of_the_run_sequential(self):
        out = Path(self.tmp.name) / 'job'
        out.mkdir()
        atomic(out / 'plan.json', {'slides': [{'phase': 'concept'}, {'phase': 'concept'}, {'phase': 'recap'},
                                              {'phase': 'concept'}, {'phase': 'concept'}]})
        seen = {}

        def fake_write(request, folder, index, item, parallel=False, feedback='', defer_repair=False):
            seen[index] = parallel
            if index == 2:
                concurrency.degrade('out of memory')
        with patch.dict('os.environ', {'MAX_PPT_CONCURRENCY': '2'}), patch('workflow_v2.pipeline.unload_model'), \
                patch('workflow_v2.pipeline.log_event'), patch('workflow_v2.pipeline.write_one', side_effect=fake_write):
            pipeline.write({'model': 'm', 'page_model': 'm'}, out)
        self.assertEqual({0: True, 1: True, 2: False, 3: False, 4: False}, seen)

    def test_quality_warnings_survive_two_pages_writing_at_once(self):
        out = Path(self.tmp.name) / 'job2'
        out.mkdir()
        threads = [threading.Thread(target=pipeline.add_quality_warning, args=(out, i, {'reason': str(i)})) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(json.loads((out / 'quality-warnings.json').read_text(encoding='utf-8'))), 12)
        drops = [threading.Thread(target=pipeline.drop_quality_warning, args=(out, i)) for i in range(0, 12, 2)]
        for t in drops:
            t.start()
        for t in drops:
            t.join()
        self.assertEqual(sorted(json.loads((out / 'quality-warnings.json').read_text(encoding='utf-8')), key=int), [str(i) for i in range(2, 13, 2)])


if __name__ == '__main__':
    unittest.main()
