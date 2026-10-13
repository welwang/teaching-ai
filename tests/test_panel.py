"""Launch-control panel (workflow_v2/panel*.py): pure HTML pieces and the remembered display settings."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_v2 import panel_style as style
from workflow_v2 import panel_view as view

GPU = {'utilization': 72, 'memory_used_mb': 21800, 'memory_total_mb': 32607}
JOB = {'id': 'a' * 32, 'unit': '因數與倍數', 'grade': 6, 'subject': '數學', 'stage': 'write', 'stage_name': '逐頁編寫',
       'stage_number': 3, 'stage_count': 7, 'stage_completed': 8, 'stage_total': 25, 'stage_unit': '頁', 'progress': '',
       'elapsed_seconds': 522, 'tokens': {'output_tokens': 12000, 'generation_seconds': 300, 'total_tokens': 184220}}
OK = {'level': 'ok', 'title': '', 'hint': '', 'action': None}


def visible(html):
    return re.sub(r'<[^>]+>', ' ', re.sub(r'data:[^"]+', '', html))


class BandTest(unittest.TestCase):
    def test_running_deck_shows_clock_dials_page_and_timeline(self):
        html = view.band_html(OK, {'job': JOB, 'gpu': GPU}, '11:58:42', queue=[{'status': 'pending'}])
        text = visible(html)
        for needle in ('製作中', '國小六年級數學', '因數與倍數', 'T+', '00:08:42', '第 9／25 頁', '完成度', '顯卡負載', '另有 1 份排隊', '11:58:42'):
            self.assertIn(needle, text)
        self.assertIn('style="--n:72"', html)
        self.assertIn('aria-label="顯卡負載 72%"', html)
        self.assertEqual(html.count('<figure class="lx-gauge"'), 2)
        self.assertEqual(html.count('<li class='), 7)
        self.assertEqual(html.count('aria-current="step"'), 1)
        self.assertIn('lx-live', html)

    def test_idle_counts_down_and_points_to_new_task(self):
        head = {'level': 'ok', 'title': '一切正常，目前沒有進行中的工作', 'hint': 'x', 'action': None}
        text = visible(view.band_html(head, {'job': None, 'gpu': GPU}, '09:00:00'))
        self.assertIn('T−', text)
        self.assertIn('00:00:00', text)
        self.assertIn('新任務', text)
        self.assertNotIn('aria-current', view.band_html(head, {'job': None, 'gpu': GPU}))

    def test_problems_and_notes_are_shown_in_plain_words(self):
        head = {'level': 'error', 'title': '需要你處理：「比與比值」沒有做完', 'hint': 'AI 模型沒有回應。', 'action': 'retry'}
        html = view.band_html(head, {'job': None, 'gpu': {'error': 'x'}}, notes=['第 2 頁請補寫', '另一件'],
                              latest={'time': '11:57:02', 'label': '重寫', 'text': '已請模型縮短'})
        text = visible(html)
        for needle in ('需要處理', '比與比值', '第 2 頁請補寫', '另有 1 項', '11:57:02', '重寫：已請模型縮短'):
            self.assertIn(needle, text)
        self.assertIn('lx-error', html)
        self.assertIn('顯卡負載 無資料', html)

    def test_dial_arc_tip_and_ticks_follow_the_percentage(self):
        arc = f'{view.GAUGE_ARC:.1f}'
        full = view.gauge_html('完成度', 100, '%', 100)
        self.assertIn(f'style="stroke-dasharray:{arc} 999"', full)
        self.assertIn('rotate(270.0deg)', full)
        self.assertIn('class="lx-ticks"', full)
        half = view.gauge_html('完成度', 50, '%', 50)
        self.assertIn(f'stroke-dasharray:{view.GAUGE_ARC / 2:.1f} 999', half)
        self.assertIn('rotate(135.0deg)', half)
        unknown = view.gauge_html('顯卡負載', None, '%')
        self.assertIn('lx-off', unknown)
        self.assertNotIn('lx-tip', unknown)
        self.assertIn('—', unknown)

    def test_timeline_marks_finished_and_current_stages(self):
        idle = view.timeline_html(None)
        self.assertEqual(idle.count('<li class="todo"'), 7)
        self.assertNotIn('aria-current', idle)
        running = view.timeline_html(JOB)
        self.assertEqual(running.count('<li class="done"'), 2)
        self.assertEqual(running.count('<li class="active" aria-current="step"'), 1)
        self.assertEqual(running.count('<li class="todo"'), 4)

    def test_everything_dynamic_is_escaped(self):
        evil = '<script>alert(1)</script>$x$'
        job = dict(JOB, unit=evil)
        html = view.band_html({'level': 'warn', 'title': evil, 'hint': evil, 'action': None}, {'job': job, 'gpu': GPU},
                              evil, latest={'time': evil, 'label': evil, 'text': evil}, notes=[evil])
        self.assertNotIn('<script>', html)
        self.assertNotIn('$x$', html)
        card = view.card_html({'status': 'running'}, {'unit': evil, 'subject': evil}, evil, 0)
        self.assertNotIn('<script>', card)


class DetailsTest(unittest.TestCase):
    def test_numbers_services_and_events(self):
        health = [{'key': 'worker', 'name': '製作程式', 'state': 'ok', 'detail': '運作中'},
                  {'key': 'image', 'name': '本機生圖', 'state': 'warn', 'detail': '正在啟動'}]
        feed = [{'time': '11:57:40', 'label': '審核', 'text': '第 8 頁通過', 'level': 'info'}]
        feed = feed + [{'time': '11:50:00', 'label': '開始', 'text': '開始逐頁編寫', 'level': 'info'}]
        text = visible(view.details_html({'job': JOB, 'gpu': GPU}, feed, health, ['第 5 頁待確認', '第 7 頁待補']))
        for needle in ('40 詞元／秒', '184,220', '21.3／32 吉位元組', '製作程式', '正在啟動', '開始逐頁編寫', '第 5 頁待確認', '第 7 頁待補'):
            self.assertIn(needle, text)

    def test_details_do_not_repeat_the_band(self):
        feed = [{'time': '11:57:40', 'label': '審核', 'text': '第 8 頁通過', 'level': 'info'}]
        text = visible(view.details_html({'job': JOB, 'gpu': GPU}, feed, [], ['只有一則']))
        for repeated in ('完成度', '8／25', '預估剩餘', '第 8 頁通過', '只有一則'):
            self.assertNotIn(repeated, text)

    def test_empty_states_say_what_will_happen(self):
        self.assertIn('還沒有事件', view.feed_html([]))
        self.assertIn('讀不到服務狀態', view.services_html([]))


class ManifestTest(unittest.TestCase):
    ROWS = [{'status': 'done'}, {'status': 'failed'}, {'status': 'running'}, {'status': 'pending'}, {'status': 'awaiting_outline'}]

    def test_counts_by_what_the_teacher_filters(self):
        self.assertEqual(view.counts(self.ROWS), {'all': 5, 'live': 2, 'done': 1, 'attention': 2})

    def test_search_and_filter(self):
        req = {'unit': '因數與倍數', 'grade': 6, 'subject': '數學', 'semester': '上學期', 'slide_count': 12}
        self.assertTrue(view.matches({'status': 'done'}, req, '六年級 倍數', 'done'))
        self.assertFalse(view.matches({'status': 'done'}, req, '', 'live'))
        self.assertFalse(view.matches({'status': 'done'}, req, '分數'))
        self.assertTrue(view.matches({'status': 'failed'}, req, '', None))

    def test_card_shows_cover_progress_while_running_and_date_when_done(self):
        req = {'unit': '因數與倍數', 'grade': 6, 'subject': '數學', 'slide_count': 20}
        running = view.card_html({'status': 'running'}, req, '逐頁編寫', 5)
        self.assertIn('5／20 頁', running)
        self.assertIn('width:25%', running)
        self.assertIn('aria-valuenow="25"', running)
        self.assertIn('pn-meter live', running)
        self.assertIn('>數</b>', running)
        done = view.card_html({'status': 'done', 'updated': 1700000000.0}, req, '發布', 0, 'data:image/jpeg;base64,AA', now=1700000000.0)
        self.assertIn('今天', done)
        self.assertIn('<img src="data:image/jpeg;base64,AA"', done)
        self.assertNotIn('pn-meter', done)
        self.assertIn('class="pn-card attention"', view.card_html({'status': 'failed'}, req, '審核', 0))

    def test_card_shows_recorded_production_time_and_preserves_unknown(self):
        req = {'unit': '因數與倍數', 'grade': 6, 'subject': '數學', 'slide_count': 20}
        done = visible(view.card_html({'status': 'done'}, req, '發布', 20, elapsed_seconds=3665))
        self.assertIn('製作總時長', done)
        self.assertIn('01:01:05', done)
        live = visible(view.card_html({'status': 'running'}, req, '逐頁編寫', 5, elapsed_seconds=65))
        self.assertIn('製作已累計', live)
        self.assertIn('00:01:05', live)
        unknown = visible(view.card_html({'status': 'done'}, req, '發布', 20))
        self.assertIn('製作總時長', unknown)
        self.assertIn('—', unknown)


class ProductionTimeTest(unittest.TestCase):
    def test_total_uses_execution_intervals_and_stops_when_done(self):
        from workflow_v2.monitoring import production_seconds
        events = [{'stage': 'source', 'message': '開始執行', 'created': 10},
                  {'stage': 'source', 'message': '完成', 'created': 20},
                  {'stage': 'plan', 'message': '開始執行', 'created': 50},
                  {'stage': 'plan', 'message': '模型失敗', 'created': 100},
                  {'stage': 'plan', 'message': '開始執行', 'created': 110},
                  {'stage': 'plan', 'message': '完成', 'created': 130}]
        row = {'id': 'a' * 32, 'status': 'done'}
        with patch('workflow_v2.monitoring._events', return_value=events):
            self.assertEqual(production_seconds(None, row, now=1000), 80)
            self.assertEqual(production_seconds(None, row, now=2000), 80)
        events.append({'stage': 'write', 'message': '開始執行', 'created': 1000})
        with patch('workflow_v2.monitoring._events', return_value=events):
            self.assertEqual(production_seconds(None, dict(row, status='running'), now=1030), 110)

    def test_missing_history_is_unknown_and_queued_work_is_zero(self):
        from workflow_v2.monitoring import production_seconds
        row = {'id': 'a' * 32, 'status': 'done'}
        with patch('workflow_v2.monitoring._events', return_value=[]):
            self.assertIsNone(production_seconds(None, row))
            self.assertEqual(production_seconds(None, dict(row, status='pending')), 0)


class StyleTest(unittest.TestCase):
    def test_five_distinct_palettes_default_to_white(self):
        self.assertEqual(list(style.THEMES), ['白色', '任務控制（深色）', '米色', '淡綠', '暮紫灰'])
        self.assertEqual(set(style.THEME_NOTES), set(style.THEMES))
        self.assertEqual(style.THEMES[style.DEFAULT_THEME]['bg'], '#ffffff')
        for name in style.THEMES:
            sheet = style.css(name)
            self.assertIn('--bg:' + style.THEMES[name]['bg'], sheet)
            self.assertIn('.lx-clock', sheet)
            self.assertIn('Bahnschrift', sheet)
            self.assertIn('@property --n', sheet)
            self.assertIn('transition:stroke-dasharray var(--glide)', sheet)
            self.assertNotIn('http', sheet)

    def test_text_is_readable_on_both_appearances(self):
        def lum(hexcode):
            channels = [int(hexcode[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            channels = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]

        def contrast(a, b):
            hi, lo = sorted((lum(a), lum(b)), reverse=True)
            return (hi + .05) / (lo + .05)
        for name, t in style.THEMES.items():
            for key in ('fg', 'muted'):
                self.assertGreaterEqual(contrast(t[key], t['bg']), 7, (name, key))
                self.assertGreaterEqual(contrast(t[key], t['raise_']), 7, (name, key, 'raised'))
            for key in ('ok', 'warn', 'err'):
                self.assertGreaterEqual(contrast(t[key], t['bg']), 4.5, (name, key))
            self.assertGreaterEqual(contrast(t['ink'], t['accent']), 4.5, (name, 'button text'))
            self.assertGreaterEqual(contrast(t['accent'], t['bg']), 3, (name, 'accent marks'))

    def test_text_size_and_calm(self):
        self.assertIn('html{font-size:150%!important}', style.css('任務控制（深色）', '特大'))
        self.assertIn('animation:none!important', style.css('任務控制（深色）', '中', True))
        self.assertNotIn('*,*::before,*::after{animation:none!important;transition:none!important}</style>', style.css('任務控制（深色）'))

    def test_settings_are_remembered_and_old_names_fall_back(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'prefs.json'
            self.assertEqual(style.load_prefs(path), {'theme': '白色', 'size': '中', 'calm': False})
            path.write_text(json.dumps({'theme': '白色', 'font': '大', 'accent': '橘', 'other': 1}), encoding='utf-8')
            self.assertEqual(style.load_prefs(path), {'theme': '白色', 'size': '大', 'calm': False})
            style.save_prefs('暮紫灰', '特大', True, path)
            self.assertEqual(style.load_prefs(path), {'theme': '暮紫灰', 'size': '特大', 'calm': True})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['other'], 1)
            with self.assertRaises(ValueError):
                style.save_prefs('粉紅', '中', False, path)

    def test_existing_panel_theme_is_migrated_without_losing_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'prefs.json'
            for old, new in style.LEGACY_THEMES.items():
                path.write_text(json.dumps({'theme': old, 'font': '大', 'calm': True}), encoding='utf-8')
                self.assertEqual(style.load_prefs(path), {'theme': new, 'size': '大', 'calm': True})


class EntryPointTest(unittest.TestCase):
    def test_real_entry_point_renders_every_palette_and_preserves_controls(self):
        from streamlit.testing.v1 import AppTest
        from workflow_v2.store import ROOT, Store
        with tempfile.TemporaryDirectory() as folder:
            root, prefs = Path(folder) / 'data', Path(folder) / 'prefs.json'
            Store(root)
            with patch('workflow_v2.panel.Store', lambda: Store(root)), \
                    patch('workflow_v2.panel_style._path', lambda path=None: Path(path or prefs)), \
                    patch('workflow_v2.monitoring.snapshot', return_value={'job': None, 'gpu': GPU}), \
                    patch('workflow_v2.panel.service_health', return_value=[]):
                at = AppTest.from_file(str(ROOT / 'app_v2.py'), default_timeout=60).run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(at.selectbox(key='pn-theme').options, list(style.THEME_NOTES.values()))
                for name in style.THEMES:
                    at.selectbox(key='pn-theme').set_value(name).run()
                    self.assertFalse(at.exception, (name, [e.value for e in at.exception]))
                    sheet = next(m.value for m in at.markdown if m.value.startswith('<style id="pn-style">'))
                    self.assertIn('--bg:' + style.THEMES[name]['bg'], sheet)
                    self.assertIn('max-width:1240px!important', sheet)
                    self.assertEqual(style.load_prefs(prefs)['theme'], name)
                    buttons = {b.label for b in at.button}
                    self.assertTrue({'開始製作簡報', '停止生成服務', '開始檢查'}.issubset(buttons))
                    self.assertTrue({'暫停佇列', '繼續佇列'} & buttons)
                    self.assertIn('維護用技術統計', {t.label for t in at.toggle})
                    self.assertEqual([tab.label for tab in at.tabs], ['製作教材', '我的教材', '系統與紀錄'])

                at = AppTest.from_file(str(ROOT / 'app_v2.py'), default_timeout=60)
                at.session_state['pn-theme'] = '酒紅黑'
                at.session_state['pn-prefs'] = {'theme': '酒紅黑', 'size': '大', 'calm': True}
                at.run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(at.selectbox(key='pn-theme').value, '任務控制（深色）')
                self.assertEqual(at.session_state['pn-prefs']['size'], '大')
                self.assertTrue(at.session_state['pn-prefs']['calm'])


class TaskPromptTest(unittest.TestCase):
    def test_custom_prompt_is_saved_only_on_submitted_task_and_editor_resets(self):
        from streamlit.testing.v1 import AppTest
        from workflow_v2.curriculum_prompts import full_prompt, LIBRARY
        from workflow_v2.store import ROOT, Store
        with tempfile.TemporaryDirectory() as folder:
            root, prefs = Path(folder) / 'data', Path(folder) / 'prefs.json'
            store = Store(root)
            source = Path(folder) / 'lesson.txt'
            source.write_text('因數與倍數', encoding='utf-8')
            units = [dict(grade=6, subject='數學', semester='上學期', title='因數與倍數', publisher='測試', path=str(source))]
            original_library = LIBRARY.read_bytes()
            default = full_prompt(dict(grade=6, subject='數學', difficulty='全部'))
            custom = '先讓學生操作積木，接著口述自己的方法。'
            with patch('workflow_v2.panel.Store', lambda: Store(root)), \
                    patch('workflow_v2.panel_style._path', lambda path=None: Path(path or prefs)), \
                    patch('workflow_v2.monitoring.snapshot', return_value={'job': None, 'gpu': GPU}), \
                    patch('workflow_v2.panel.service_health', return_value=[]), \
                    patch('workflow_v2.library.units', return_value=units), \
                    patch('workflow_v2.panel.resume'):
                at = AppTest.from_file(str(ROOT / 'app_v2.py'), default_timeout=60).run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(at.text_area(key='nt-teaching-editor').value, default)
                at.text_area(key='nt-teaching-editor').set_value(custom).run()
                at.selectbox(key='pn-theme').set_value('米色').run()
                self.assertEqual(at.text_area(key='nt-teaching-editor').value, custom)
                at.button(key='nt-go').click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(len(store.list()), 1)
                self.assertEqual(json.loads(store.list()[0]['request'])['teaching_prompt_override'], custom)
                self.assertEqual(at.text_area(key='nt-teaching-editor').value, default)
                at.button(key='nt-go').click().run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertEqual(len(store.list()), 2)
                requests = [json.loads(row['request']) for row in store.list()]
                self.assertEqual(sum('teaching_prompt_override' in req for req in requests), 1)
                at.text_area(key='nt-teaching-editor').set_value(custom).run()
                at.button(key='nt-teaching-restore').click().run()
                self.assertEqual(at.text_area(key='nt-teaching-editor').value, default)
                at.text_area(key='nt-teaching-editor').set_value(custom).run()
                at.selectbox(key='nt-grade').set_value(5).run()
                self.assertEqual(at.text_area(key='nt-teaching-editor').value,
                                 full_prompt(dict(grade=5, subject='數學', difficulty='全部')))
            self.assertEqual(LIBRARY.read_bytes(), original_library)


if __name__ == '__main__':
    unittest.main()
