"""監控資料與狀態判斷測試。"""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


from workflow_v2 import console_state as cs
from workflow_v2.monitor_report import STAGE_LABELS
from workflow_v2.store import STAGES, Store
from tests.test_monitoring_report import REQUEST, GPU, english_in, ev

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r'[\u4e00-\u9fff]')


def job(**extra):
    base = dict(id='a' * 32, unit='分數的加減', grade=6, semester='上學期', subject='數學', stage='write',
                stage_name='逐頁編寫', stage_number=3, stage_count=7, progress='編寫第 6 頁', stage_completed=5,
                stage_total=12, stage_unit='頁', activity_state='inference', activity_age_seconds=12, model='m',
                elapsed_seconds=600, eta_seconds=420, tokens={}, report={'available': True, 'calls': {'finished': 4, 'failed': 1, 'retries': 2},
                'problem_counts': {'warning': 2, 'error': 0}, 'pages': [{'retries': 1}]})
    base.update(extra)
    return base


def state(**extra):
    base = dict(counts={}, job=None, recent=None, gpu=GPU, worker_alive=True, queue_paused=False,
                session_tokens={'total_tokens': 0}, status={'level': 'info', 'title': '目前沒有進行中的工作', 'detail': '可到「製作教材」建立新的簡報。'})
    base.update(extra)
    return base


class ProgressTest(unittest.TestCase):
    def test_percent_follows_stage_weights_and_never_reaches_100_while_running(self):
        self.assertEqual(cs.overall_percent(None), 0)
        self.assertEqual(sum(cs.STAGE_WEIGHTS.values()), 100)
        self.assertEqual(cs.overall_percent(job(stage='source', stage_total=None)), 0)
        self.assertEqual(cs.overall_percent(job(stage='write', stage_completed=0, stage_total=10)), 15)
        self.assertEqual(cs.overall_percent(job(stage='write', stage_completed=5, stage_total=10)), 35)
        self.assertEqual(cs.overall_percent(job(stage='publish', stage_completed=9, stage_total=9)), 99)
        values = [cs.overall_percent(job(stage=name, stage_completed=0, stage_total=10)) for name in STAGES]
        self.assertEqual(values, sorted(values))
        self.assertEqual(cs.overall_percent(job(stage_completed=99, stage_total=10)), 55)

    def test_overall_eta_needs_enough_evidence(self):
        self.assertIsNone(cs.overall_eta(job(elapsed_seconds=30)))
        self.assertIsNone(cs.overall_eta(job(stage='source', stage_total=None)))
        eta = cs.overall_eta(job(stage_completed=5, stage_total=10, elapsed_seconds=700))
        self.assertEqual(eta, int(700 * 65 / 35))

    def test_current_page_from_label_or_checkpoint(self):
        self.assertEqual(cs.current_page(job()), 6)
        self.assertEqual(cs.current_page(job(progress='整理主教材', stage_completed=3)), 4)
        self.assertIsNone(cs.current_page(job(progress='x', stage_total=None)))
        self.assertIsNone(cs.current_page(None))

    def test_chips_mark_done_active_and_todo(self):
        chips = cs.stage_chips(job())
        self.assertEqual([c['state'] for c in chips], ['done', 'done', 'active', 'todo', 'todo', 'todo', 'todo'])
        self.assertEqual([c['name'] for c in chips], [STAGE_LABELS[s] for s in STAGES])


class QueueAndFeedTest(unittest.TestCase):
    def rows(self):
        def row(i, status, stage=0, request=None):
            return dict(id=f'{i:032x}', status=status, stage=stage, error='', created=i, request=request or json.dumps(dict(REQUEST, unit=f'單元{i}')))
        return [row(1, 'done', 7), row(2, 'pending'), row(3, 'running', 2), row(4, 'failed', 3), row(5, 'paused'),
                row(6, 'pending', 0, '{broken'), row(7, 'done', 7), row(8, 'done', 7), row(9, 'done', 7)]

    def test_running_first_then_waiting_by_age_then_latest_finished(self):
        queue = cs.queue_rows(self.rows())
        self.assertEqual(queue[0]['status'], 'running')
        self.assertEqual([r['status'] for r in queue[1:4]], ['pending', 'paused', 'pending'])
        self.assertEqual([r['position'] for r in queue], list(range(1, len(queue) + 1)))
        self.assertEqual(sum(r['status'] in ('done', 'failed') for r in queue), 3)
        self.assertIn('（資料損毀）', [r['unit'] for r in queue])
        for item in queue:
            self.assertTrue(CJK.search(item['status_text']), item)

    def test_every_status_has_a_chinese_name(self):
        for status in ('staging', 'pending', 'running', 'rendering', 'reviewing', 'repairing', 'awaiting_outline',
                       'paused', 'pausing', 'removing', 'done', 'failed'):
            self.assertTrue(CJK.search(cs.status_text(status)), status)
        self.assertEqual(cs.status_text('???'), '狀態未知')

    def test_feed_is_newest_first_localized_and_skips_noise(self):
        with tempfile.TemporaryDirectory() as t:
            store = Store(t)
            jid = store.submit(REQUEST)
            base = time.time() - 60
            lines = [ev('job_snapshot', base), ev('model_call_started', base + 1, stage='write', label='編寫第 1 頁'),
                     ev('model_call_finished', base + 5, stage='write', label='編寫第 1 頁', attempt=1, prompt_tokens=100, output_tokens=50),
                     ev('model_call_error', base + 6, stage='write', error='connection refused'),
                     ev('page_retry', base + 7, stage='write', page=1, reason='標題不符')]
            (store.folder(jid) / 'run.jsonl').write_text(''.join(lines), encoding='utf-8')
            feed = cs.live_feed(store, jid, 8)
            self.assertEqual([f['label'] for f in feed], ['頁面重寫', '模型呼叫失敗', '模型回覆完成'])
            self.assertEqual(feed[1]['level'], 'error')
            self.assertIn('連不上本機模型服務', feed[1]['text'])
            self.assertEqual(len(cs.live_feed(store, jid, 2)), 2)
            self.assertEqual(cs.live_feed(store, None, 5), cs.live_feed(store, None, 5))

    def test_feed_survives_missing_log(self):
        with tempfile.TemporaryDirectory() as t:
            store = Store(t)
            jid = store.submit(REQUEST)
            (store.folder(jid) / 'run.jsonl').unlink()
            self.assertEqual(cs.live_feed(store, jid), [])


class HealthTest(unittest.TestCase):
    def rows(self, **kw):
        probes = dict(model_probe=lambda: {'reachable': True, 'loaded': []}, image_probe=lambda: {'reachable': False})
        probes.update(kw)
        return {r['key']: r for r in cs.service_health(kw.pop('state', state()), disk_path=ROOT, **probes)}

    def test_model_down_is_error_only_when_work_is_waiting(self):
        down = lambda: {'reachable': False, 'reason': 'refused'}
        idle = self.rows(model_probe=down)['model']
        busy = {r['key']: r for r in cs.service_health(state(counts={'pending': 1}), model_probe=down, image_probe=lambda: {'reachable': False}, disk_path=ROOT)}['model']
        self.assertEqual(idle['state'], 'warn')
        self.assertEqual(busy['state'], 'error')
        self.assertIn('連不上', busy['detail'])

    def test_worker_gpu_image_and_loaded_model_rows(self):
        rows = {r['key']: r for r in cs.service_health(state(worker_alive=False, counts={'pending': 2}, gpu={'error': 'x'}),
                model_probe=lambda: {'reachable': True, 'loaded': ['qwen3.8:27b-q4_K_M']}, image_probe=lambda: {'reachable': False}, disk_path=ROOT)}
        self.assertEqual(rows['worker']['state'], 'error')
        self.assertEqual(rows['gpu']['state'], 'warn')
        self.assertIn('qwen3.8:27b-q4_K_M', rows['model']['detail'])
        self.assertEqual(rows['image']['state'], 'off')
        full = {r['key']: r for r in cs.service_health(state(gpu={'utilization': 99, 'memory_used_mb': 32000, 'memory_total_mb': 32600}),
                model_probe=lambda: {'reachable': True, 'loaded': []}, image_probe=lambda: {'reachable': True}, disk_path=ROOT)}
        self.assertEqual(full['gpu']['state'], 'warn')
        self.assertIn('接近滿載', full['gpu']['detail'])
        self.assertEqual(full['image']['state'], 'ok')

    def test_probes_never_raise_when_services_are_down(self):
        with patch('requests.get', side_effect=OSError('down')):
            self.assertFalse(cs.probe_model_service()['reachable'])
            self.assertFalse(cs.probe_image_service()['reachable'])

    def test_health_rows_are_chinese_and_optional_parts_are_not_errors(self):
        report = {'database': {'ready': True, 'detail': 'SQLite read/write OK'}, 'models': {'ready': False, 'detail': '連線失敗'},
                  'local_image': {'ready': False, 'optional': True, 'detail': {'ready': False, 'reason': 'x'}},
                  'disk': {'ready': True, 'detail': {'free_gb': 800.5}}}
        rows = {r['key']: r for r in cs.health_rows(report)}
        self.assertEqual(rows['models']['state'], 'error')
        self.assertEqual(rows['local_image']['state'], 'off')
        self.assertIn('不影響文字簡報', rows['local_image']['detail'])
        self.assertEqual(rows['disk']['detail'], 'free_gb：800.5')
        for row in rows.values():
            self.assertTrue(CJK.search(row['name']))


class ErrorHintTest(unittest.TestCase):
    def test_new_pipeline_failures_get_plain_chinese(self):
        from workflow_v2.monitor_report import explain_error
        for raw in ('LibreOffice PDF轉檔未完成', 'PDF頁數與原稿不符', '單頁保底排版仍無法顯示', '第3頁沒有可引用的主教材文字'):
            hint = explain_error(raw)
            self.assertTrue(CJK.search(hint), raw)
            self.assertEqual(english_in(hint), [], raw)
        self.assertEqual(explain_error('LibreOffice PDF轉檔未完成').count('預覽檔'), 1)


def healthy(**kw):
    rows = [dict(key='worker', state='ok'), dict(key='model', state='ok')]
    for r in rows:
        r.update(kw.get(r['key'], {}))
    return rows


class HeadlineTest(unittest.TestCase):
    def head(self, s=None, queue=(), health=None):
        return cs.headline(s or state(), list(queue), healthy() if health is None else health, now=1000)

    def test_idle_is_calm_and_has_no_button(self):
        h = self.head()
        self.assertEqual(h['level'], 'ok')
        self.assertIn('一切正常', h['title'])
        self.assertIsNone(h['action'])

    def test_running_says_page_and_minutes_in_plain_words(self):
        h = self.head(state(job=job(), counts={'running': 1}))
        self.assertIn('正在製作第 6 頁（共 12 頁）', h['title'])
        self.assertRegex(h['title'], r'約 \d+ 分鐘後完成|不到 1 分鐘')
        self.assertIsNone(h['action'])

    def test_problems_surface_only_when_the_user_must_act_and_offer_one_button(self):
        down = self.head(health=healthy(worker={'state': 'error'}), queue=[dict(status='pending', unit='x', id='1')])
        self.assertTrue(down['title'].startswith('需要你處理'))
        self.assertEqual(down['action'], 'start')
        model = self.head(state(job=job()), health=healthy(model={'state': 'error'}))
        self.assertTrue(model['title'].startswith('需要你處理'))
        self.assertEqual(model['action'], 'resume')
        failed = self.head(queue=[dict(status='failed', unit='分數', id='f' * 32, error='x', created=900)])
        self.assertEqual((failed['level'], failed['action'], failed['job_id']), ('error', 'retry', 'f' * 32))
        paused = self.head(state(queue_paused=True))
        self.assertEqual(paused['action'], 'resume')
        outline = self.head(queue=[dict(status='awaiting_outline', unit='x', id='1')])
        self.assertTrue(outline['title'].startswith('需要你處理'))

    def test_warnings_and_retries_alone_never_raise_the_alarm(self):
        h = self.head(state(job=job(report={'available': True, 'calls': {'failed': 3, 'retries': 5}, 'problem_counts': {'warning': 9, 'error': 0}})), health=healthy())
        self.assertEqual(h['level'], 'ok')
        self.assertIsNone(h['action'])

    def test_old_failures_do_not_nag(self):
        h = self.head(queue=[dict(status='failed', unit='x', id='1', error='', created=1000 - 5 * 86400)])
        self.assertEqual(h['level'], 'ok')

    def test_every_headline_is_plain_chinese(self):
        samples = [self.head(), self.head(state(job=job())), self.head(state(queue_paused=True)),
                   self.head(health=healthy(worker={'state': 'error'}))]
        for h in samples:
            self.assertTrue(CJK.search(h['title']))
            self.assertEqual(english_in(h['title'] + h['hint'] + h['action_label']), [])

    def test_minutes_text(self):
        self.assertFalse(cs.minutes_text(None))
        self.assertEqual(cs.minutes_text(20), '不到 1 分鐘')
        self.assertEqual(cs.minutes_text(180), '約 3 分鐘')


if __name__ == '__main__':
    unittest.main()
