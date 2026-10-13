import ast
import io
import json
import re
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from workflow_v2 import monitor_report, monitoring
from workflow_v2.store import Store

REQUEST = dict(schema_version=1, grade=6, subject='數學', semester='上學期', unit='測試單元', publisher='測試',
               difficulty='全部', slide_count=8, source_path='test.md', model='qwen3.8:27b-q4_K_M', locale='zh-TW')
ROOT = Path(__file__).resolve().parents[1]
GPU = {'utilization': 20, 'memory_used_mb': 1000, 'memory_total_mb': 32000}
CJK = re.compile(r'[\u4e00-\u9fff]')
ENGLISH = re.compile(r'[A-Za-z]{2,}')
ALLOWED = ('qwen3.8:27b-q4_K_M', 'AI')


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='milliseconds')


def ev(name, at, **fields):
    return json.dumps({'time': iso(at), 'event': name, 'job_id': 'x' * 32, **fields}, ensure_ascii=False) + '\n'


def sample_events(base):
    return [
        ev('stage_started', base, stage='source', attempt=1),
        ev('stage_completed', base + 1, stage='source', duration_seconds=1.0),
        ev('stage_started', base + 2, stage='write', attempt=1),
        ev('model_call_started', base + 3, stage='write', label='編寫第 1 頁', gpu_wait_seconds=2.5),
        ev('model_call_finished', base + 13, stage='write', label='編寫第 1 頁', duration_seconds=10.0,
           prompt_tokens=100, output_tokens=50, done_reason='stop'),
        ev('qa_rejected', base + 14, stage='write', page=1, hard=1, soft=0, codes=['mismatch']),
        ev('page_retry', base + 14, stage='write', page=1, attempt=1, reason='本頁未通過\n- 標題與內容不符'),
        ev('model_call_finished', base + 30, stage='write', label='編寫第 1 頁', duration_seconds=16.0,
           prompt_tokens=100, output_tokens=60, done_reason='length'),
        ev('model_call_error', base + 31, model='qwen3.8:27b-q4_K_M', attempt=1, http_status=404,
           error='{"error":"model \'qwen3.8:27b-q4_K_M\' not found"}'),
        ev('model_retry_scheduled', base + 32, retry_count=1, delay_seconds=5, http_status=503),
        ev('fallback_page_created', base + 40, stage='write', page=2, reason='本頁未通過\n- 數字找不到來源'),
        ev('model_call_finished', base + 50, stage='review', label='審核第 1～2 頁', duration_seconds=20.0,
           prompt_tokens=10, output_tokens=5),
        ev('review_rejected', base + 51, stage='review', page=2, issue_count=1, issues=['標題不完整']),
    ]


class ReportTest(unittest.TestCase):
    def test_incremental_reader_survives_partial_and_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'run.jsonl'
            base = time.time()
            lines = sample_events(base)
            path.write_text(''.join(lines[:3]) + '{壞掉的行\n' + lines[3][:40], encoding='utf-8')
            first = monitor_report.log_report(path, base + 5)
            self.assertTrue(first['available'])
            self.assertEqual((first['events'], first['bad_lines']), (3, 1))
            with path.open('a', encoding='utf-8') as stream:
                stream.write(lines[3][40:] + ''.join(lines[4:]))
            second = monitor_report.log_report(path, base + 60)
            self.assertEqual(second['events'], len(lines))
            self.assertEqual(second['calls']['finished'], 3)
            path.write_text(lines[0], encoding='utf-8')
            third = monitor_report.log_report(path, base + 61)
            self.assertEqual(third['events'], 1)
            self.assertEqual(third['calls']['finished'], 0)

    def test_report_counts_calls_pages_stages_and_problems(self):
        with tempfile.TemporaryDirectory() as t:
            base = time.time() - 100
            (Path(t) / 'run.jsonl').write_text(''.join(sample_events(base)), encoding='utf-8')
            report = monitor_report.job_report(t, base + 60)
        calls = report['calls']
        self.assertEqual((calls['finished'], calls['failed'], calls['retries'], calls['truncated']), (3, 1, 1, 1))
        self.assertAlmostEqual(calls['gpu_wait_seconds'], 2.5)
        self.assertEqual(calls['max_seconds'], 20.0)
        pages = {row['page']: row for row in report['pages']}
        self.assertEqual(pages[1]['write_calls'], 2)
        self.assertAlmostEqual(pages[1]['write_seconds'], 26.0)
        self.assertEqual((pages[1]['retries'], pages[1]['qa_rejected']), (1, 1))
        self.assertEqual(pages[2]['fallback'], 1)
        self.assertEqual((pages[1]['review_calls'], pages[2]['review_calls']), (1, 1))
        self.assertAlmostEqual(pages[2]['review_seconds'], 10.0)
        self.assertEqual(report['fallback_pages'], [2])
        stages = {row['stage']: row for row in report['stages']}
        self.assertTrue(stages['source']['completed'])
        self.assertTrue(stages['write']['running'])
        self.assertEqual(stages['write']['calls'], 2)
        self.assertGreater(report['problem_counts']['error'], 0)
        newest = report['problems'][0]
        self.assertGreaterEqual(newest['time'], report['problems'][-1]['time'])
        texts = ' '.join(item['text'] for item in report['problems'])
        self.assertIn('找不到指定的本地模型', texts)
        self.assertIn('標題與內容對不上', texts)
        self.assertNotIn('not found', texts)
        for table in (monitor_report.stage_table(report), monitor_report.page_table(report),
                      monitor_report.problem_table(report['problems'])):
            self.assertIn('---', table)

    def test_identical_warnings_are_merged_with_a_count(self):
        with tempfile.TemporaryDirectory() as t:
            base = time.time() - 50
            lines = [ev('image_generation_unavailable', base + i, stage='render', page=3, reason='本機圖像服務尚未啟用')
                     for i in range(5)]
            (Path(t) / 'run.jsonl').write_text(''.join(lines), encoding='utf-8')
            report = monitor_report.job_report(t, base + 10)
        self.assertEqual(len(report['problems']), 1)
        self.assertEqual(report['problems'][0]['count'], 5)
        self.assertEqual(report['problem_counts']['warning'], 5)
        self.assertIn('×5', monitor_report.problem_table(report['problems']))
        self.assertIn('本機生圖服務沒有開啟', monitor_report.problem_table(report['problems']))

    def test_missing_or_unreadable_log_gives_empty_report(self):
        with tempfile.TemporaryDirectory() as t:
            report = monitor_report.job_report(t)
            self.assertFalse(report['available'])
            self.assertEqual((report['events'], report['problems'], report['pages']), (0, [], []))
            self.assertIsNone(report['last_event_age'])
            self.assertEqual(monitor_report.recent_events(Path(t) / 'nope.jsonl'), [])

    def test_recent_events_reads_only_the_tail_newest_first(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'run.jsonl'
            base = time.time()
            path.write_text(''.join(ev('job_event', base + i, stage='write', message=f'第{i}筆') for i in range(200))
                            + '{半行', encoding='utf-8')
            with patch.object(monitor_report, 'TAIL_BYTES', 3000):
                rows = monitor_report.recent_events(path, 5)
                everything = monitor_report.recent_events(path, 500)
            self.assertEqual([row['message'] for row in rows], [f'第{i}筆' for i in (199, 198, 197, 196, 195)])
            self.assertLess(len(everything), 200)
            self.assertTrue(all(isinstance(row, dict) for row in everything))

    def test_markdown_table_escapes_special_characters_without_pandas(self):
        table = monitor_report.markdown_table(['欄|一', '欄二'], [['a|b\nc', '$5 *x* _y_ `z`']])
        self.assertEqual(len(table.splitlines()), 3)
        self.assertNotIn('\nc', table)
        self.assertIn(r'a\|b', table)
        self.assertIn(r'\$5', table)
        self.assertIn(r'\*x\*', table)
        self.assertNotIn('pandas', ' '.join(monitor_report.__dict__.keys()))

    def test_error_explanations_are_plain_chinese(self):
        cases = {
            ("model 'x' not found", 404): '找不到指定的本地模型',
            ('', 500): '內部錯誤',
            ('', 503): '暫時無法回應',
            ('Connection refused', None): '連不上',
            ('階段超時：write', None): '逾時',
            ('輸出截斷；精簡說明', None): '截斷',
            ('本地模型 3 次仍無完整有效 JSON：x', None): '完整格式',
        }
        for (text, status), expected in cases.items():
            self.assertIn(expected, monitor_report.explain_error(text, status), text)
        self.assertEqual(monitor_report.explain_error('totally unknown'), '')
        self.assertEqual(monitor_report.pages_in('審核第 4～6 頁'), [4, 5, 6])
        self.assertEqual(monitor_report.pages_in('整理主教材片段'), [])
        self.assertEqual(monitor_report.localize_fields('內容太長（body.answer）與（steps[2]）'),
                         '內容太長（內容．答案）與（解題步驟）')
        self.assertEqual(monitor_report.localize_fields('（heading）'), '（標題）')


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        monitoring._SESSION_CACHE.clear()
        monitoring._GPU_CACHE.update(at=0.0, value=None)

    def seed(self, root, stage=2):
        with patch('workflow_v2.model_policy.settings', return_value={}):
            store = Store(root)
            jid = store.submit(REQUEST)
        with store.db() as connection:
            connection.execute("UPDATE jobs SET stage=?,status='running' WHERE id=?", (stage, jid))
        return store, jid

    def test_snapshot_contains_report_and_status(self):
        with tempfile.TemporaryDirectory() as t:
            store, jid = self.seed(t)
            base = time.time() - 30
            (store.folder(jid) / 'run.jsonl').write_text(''.join(sample_events(base)), encoding='utf-8')
            with patch('workflow_v2.monitoring.gpu', return_value=GPU), \
                    patch('workflow_v2.monitoring._worker_alive', return_value=True):
                state = monitoring.snapshot(store)
            self.assertEqual(state['job']['report']['calls']['finished'], 3)
            self.assertIn(state['status']['level'], ('ok', 'warn'))

    def test_snapshot_survives_corrupt_request_and_missing_log(self):
        with tempfile.TemporaryDirectory() as t:
            store, jid = self.seed(t)
            with store.db() as connection:
                connection.execute("UPDATE jobs SET request='{壞' WHERE id=?", (jid,))
            with patch('workflow_v2.monitoring.gpu', return_value=GPU):
                state = monitoring.snapshot(store)
            self.assertEqual(state['job']['unit'], '未命名教材')
            self.assertEqual(state['job']['report']['calls']['finished'], 0)
            self.assertEqual(state['status']['level'], 'error')

    def test_session_usage_scan_is_cached_between_refreshes(self):
        with tempfile.TemporaryDirectory() as t:
            store, _ = self.seed(t)
            with patch('workflow_v2.monitoring.gpu', return_value=GPU), \
                    patch('workflow_v2.monitoring.session_usage', wraps=monitoring.session_usage) as scan:
                monitoring.snapshot(store)
                monitoring.snapshot(store)
                self.assertEqual(scan.call_count, 1)
                monitoring.snapshot(store, now=time.time())
                self.assertEqual(scan.call_count, 2)

    def test_usage_cache_keeps_numbers_only(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'page-1-attempt-0.json'
            path.write_text(json.dumps({'prompt_eval_count': 3, 'eval_count': 4, 'done_reason': 'stop',
                                        'message': {'content': '很長的模型回覆' * 100}}, ensure_ascii=False), encoding='utf-8')
            stat = path.stat()
            record = monitoring._usage_record(path, stat.st_mtime_ns, stat.st_size)
            self.assertNotIn('message', record)
            self.assertEqual(monitoring.usage(Path(t))['total_tokens'], 7)

    def test_gpu_probe_is_cached_briefly(self):
        with patch('workflow_v2.monitoring._gpu_query', return_value=GPU) as query:
            monitoring.gpu()
            monitoring.gpu()
            self.assertEqual(query.call_count, 1)

    def test_overall_status_levels_and_wording(self):
        base = {'counts': {}, 'worker_alive': True, 'queue_paused': False, 'recent': None, 'job': None}
        job = {'stage_number': 3, 'stage_count': 7, 'stage_name': '逐頁編寫', 'elapsed_seconds': 90,
               'eta_seconds': None, 'activity_age_seconds': 5, 'activity_state': 'inference', 'report': {}}
        cases = [
            (dict(base, job=job), 'ok'),
            (dict(base, job=dict(job, activity_age_seconds=400)), 'warn'),
            (dict(base, job=dict(job, activity_state='waiting_gpu')), 'warn'),
            (dict(base, job=job, worker_alive=False), 'error'),
            (dict(base, job=dict(job, report={'last_error': {'time': time.time() - 10, 'text': '模型服務暫時無法回應'}})), 'warn'),
            (dict(base, counts={'pending': 2}, queue_paused=True), 'info'),
            (dict(base, counts={'pending': 2}, worker_alive=False), 'warn'),
            (dict(base, recent={'status': 'failed', 'unit': '甲', 'error': '階段超時：write'}), 'error'),
            (dict(base, recent={'status': 'done', 'unit': '甲'}), 'info'),
            (base, 'info'),
        ]
        for state, level in cases:
            status = monitoring.overall_status(state)
            self.assertEqual(status['level'], level, status)
            for text in (status['title'], status['detail']):
                self.assertTrue(CJK.search(text), text)
                self.assertIsNone(ENGLISH.search(text), text)


def english_in(text):
    for item in ALLOWED:
        text = text.replace(item, '')
    return ENGLISH.findall(text)


class ChineseOnlyTest(unittest.TestCase):
    UI_CALLS = {'metric', 'caption', 'markdown', 'info', 'warning', 'error', 'success', 'subheader',
                'write', 'expander', 'progress', 'button', 'download_button', 'selectbox', 'text', 'header', 'title'}
    SKIP_KEYWORDS = {'key', 'file_name', 'mime', 'type', 'language', 'on_click', 'on_change',
                     'width', 'height', 'gap', 'vertical_alignment', 'label_visibility', 'format_func',
                     'index', 'disabled', 'options', 'default', 'horizontal', 'border'}

    def ui_literals(self, source):
        found = []

        def collect(node):
            if isinstance(node, ast.JoinedStr):
                found.append(''.join(part.value for part in node.values
                                     if isinstance(part, ast.Constant) and isinstance(part.value, str)))
                return
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ('encode', 'read_bytes', 'read_text', 'getvalue'):
                return
            if isinstance(node, ast.Subscript):
                collect(node.value)
                return
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                for child in node.args[1:] + [k.value for k in node.keywords]:
                    collect(child)
                return
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append(node.value)
            for child in ast.iter_child_nodes(node):
                collect(child)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in self.UI_CALLS:
                for arg in node.args:
                    collect(arg)
                for keyword in node.keywords:
                    if keyword.arg not in self.SKIP_KEYWORDS:
                        collect(keyword.value)
        return found

    def test_monitoring_ui_literals_are_chinese_only(self):
        literals = self.ui_literals((ROOT / 'workflow_v2' / 'panel.py').read_text(encoding='utf-8'))
        self.assertGreater(len(literals), 25)
        for text in literals:
            visible = re.sub(r'<[^>]+>', '', text)
            visible = re.sub(r'\.[a-zA-Z0-9]{2,5}\b', '', visible)
            self.assertEqual(english_in(visible), [], text)

    def test_display_dictionaries_and_tables_are_chinese_only(self):
        values = list(monitor_report.EVENT_LABELS.values()) + list(monitor_report.STAGE_LABELS.values()) \
            + list(monitor_report.CODE_LABELS.values()) + [hint for _, hint in monitor_report.ERROR_HINTS]
        for text in values:
            self.assertTrue(CJK.search(text), text)
            self.assertEqual(english_in(text), [], text)
        self.assertEqual(set(monitor_report.STAGE_LABELS), set(monitor_report.STAGE_ORDER))
        self.assertEqual(monitor_report.STAGE_LABELS, monitoring.STAGE_NAMES)
        base = time.time() - 50
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'run.jsonl').write_text(''.join(sample_events(base)), encoding='utf-8')
            report = monitor_report.job_report(t, base + 60)
            rows = monitor_report.event_rows(monitor_report.recent_events(Path(t) / 'run.jsonl', 50))
        self.assertEqual(len(rows), len(sample_events(base)))
        log_table = monitor_report.markdown_table(['時間', '事件', '階段', '頁', '說明', '耗時'], rows)
        for text in (monitor_report.stage_table(report), monitor_report.page_table(report),
                     monitor_report.problem_table(report['problems']), log_table):
            self.assertEqual(english_in(text), [], text)

    def test_every_known_event_is_described_in_chinese(self):
        names = set(monitor_report.EVENT_LABELS) | set(monitor_report.LEVELS)
        self.assertTrue(set(monitor_report.LEVELS) <= set(monitor_report.EVENT_LABELS))
        for name in names:
            text = monitor_report.describe({'event': name, 'label': '編寫第 2 頁', 'error': 'boom', 'reason': 'x',
                                            'http_status': 500, 'attempt': 2, 'codes': ['zzz'], 'issues': ['問題'],
                                            'unit': '單元', 'message': '開始執行', 'duration_seconds': 3})
            if name in ('model_call_error', 'stage_failed', 'engine_start_failed', 'worksheet_generation_failed',
                        'review_batch_unavailable', 'image_generation_failed', 'model_unload_failed', 'analysis_fallback'):
                self.assertIn('內部錯誤', text)
            self.assertEqual(english_in(text), [], (name, text))


class PageRenderTest(unittest.TestCase):
    def test_monitoring_panel_and_log_tab_render_in_chinese(self):
        from streamlit.testing.v1 import AppTest
        monitoring._SESSION_CACHE.clear()
        monitoring._GPU_CACHE.update(at=0.0, value=None)
        with tempfile.TemporaryDirectory() as t:
            with patch('workflow_v2.model_policy.settings', return_value={}):
                store = Store(t)
                jid = store.submit(REQUEST)
            with store.db() as connection:
                connection.execute("UPDATE jobs SET stage=2,status='running' WHERE id=?", (jid,))
            (store.folder(jid) / 'run.jsonl').write_text(''.join(sample_events(time.time() - 60)), encoding='utf-8')
            system_log = Path(t) / 'system.jsonl'
            system_log.write_text(''.join(sample_events(time.time() - 60)), encoding='utf-8')
            (store.folder(jid) / 'plan.json').write_text(json.dumps({'slides': [{}] * 8}), encoding='utf-8')

            def app():
                from workflow_v2.panel import _telemetry, _system_tab
                _telemetry()
                _system_tab()
            import os
            with patch.dict(os.environ, {'MON_TEST_ROOT': t}), \
                    patch('workflow_v2.panel.Store', lambda: Store(t)), \
                    patch('workflow_v2.panel.SYSTEM_LOG', system_log), \
                    patch('workflow_v2.monitoring.gpu', return_value=GPU), \
                    patch('workflow_v2.console_state._cached', side_effect=lambda key, ttl, fn: fn()), \
                    patch('workflow_v2.console_state.probe_model_service', return_value={'reachable': True, 'loaded': []}), \
                    patch('workflow_v2.console_state.probe_image_service', return_value={'reachable': False}), \
                    patch('workflow_v2.monitoring._worker_alive', return_value=True):
                at = AppTest.from_function(app, default_timeout=30).run()
            self.assertFalse(at.exception, [str(e.value) for e in at.exception])
            texts = []

            def walk(block):
                for child in block:
                    for name in ('value', 'label', 'body', 'help'):
                        value = getattr(child, name, None)
                        if isinstance(value, str):
                            texts.append(value)
                    proto = getattr(child, 'proto', None)
                    if proto is not None and isinstance(getattr(proto, 'text', None), str):
                        texts.append(proto.text)
                    if hasattr(child, 'children'):
                        walk(child.children.values())
            walk(at.main.children.values())
            joined = '\n'.join(texts)
            self.assertIn('遙測詳情', joined)
            self.assertIn('製作中', joined)

            visible = [re.sub(r'<[^>]+>', ' ', text) for text in texts]
            leftovers = [word for text in visible
                         for word in english_in(re.sub(re.escape(jid[:8]), '', text.replace(jid, '')))]
            self.assertEqual(leftovers, [], leftovers)


if __name__ == '__main__':
    unittest.main()
