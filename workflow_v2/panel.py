"""教材製作、任務監控與成果管理介面。"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

from . import panel_view as view
from .console_state import gpu_numbers, headline, health_rows, live_feed, queue_rows, refresh_seconds, service_health, status_text
from .monitor_report import STAGE_LABELS, event_rows, explain_error, markdown_table, page_table, problem_table, recent_events, stage_table
from .panel_style import TEXT_SIZES, THEME_NOTES, THEMES, css, load_prefs, normalize_theme, save_prefs
from .runlog import SYSTEM_LOG, clear_log
from .service import approve_outline, regenerate, result
from .store import DATA, ROOT, STAGES, Store
from .worker import pause, resume

REFRESH = refresh_seconds()
FILES = {'pptx': '簡報檔', 'pdf': 'PDF 預覽檔', 'docx': '教師備課稿', 'worksheet_docx': '學生學習單', 'worksheet_answers_docx': '學習單解答',
         'json': '簡報資料', 'qa_report': '品質檢查報告', 'teaching_profile': '教學設定', 'teaching_prompt': '教學提示詞',
         'quality_warnings': '品質警示', 'visual_assets': '插圖紀錄', 'layout_warnings': '排版警示', 'final_optimization': '最後優化報告',
         'final_original_pptx': '優化前簡報', 'deck_validation': '簡報檢查報告', 'visual_qa': '版面檢查報告', 'template_selection': '舊版選版紀錄'}
FIELDS = {'整頁': 'slide', '標題': 'heading', '主要內容': 'body', '教師備註': 'speaker_notes', '圖片描述': 'visual_asset'}


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _request(row):
    try:
        return json.loads(row['request'])
    except (TypeError, ValueError):
        return {}


def _files(job_id, store):
    data = result(job_id, store)
    return data, {kind: Path(path) for kind, path in (data.get('artifacts') or {}).items() if Path(path).exists()}


def _download(label, path, key, primary=False):
    path = Path(path)
    st.download_button(label, lambda: path.read_bytes(), file_name=path.name, key=key, on_click='ignore',
                       type='primary' if primary else 'secondary')


def _display_menu():
    prefs = st.session_state['pn-prefs']

    def remember():
        prefs.update(theme=st.session_state['pn-theme'], size=st.session_state['pn-size'], calm=st.session_state['pn-calm'])
        try:
            save_prefs(prefs['theme'], prefs['size'], prefs['calm'])
        except (OSError, ValueError):
            pass
    with st.popover('顯示'):
        st.selectbox('配色風格', list(THEMES), key='pn-theme', index=None if 'pn-theme' in st.session_state else list(THEMES).index(prefs['theme']), on_change=remember,
                     format_func=lambda name: THEME_NOTES[name],
                     help='白、黑、暖米、森林綠、暮紫，五種明顯不同的配色。整個面板會一起換色。')
        st.radio('字體大小', list(TEXT_SIZES), key='pn-size', index=list(TEXT_SIZES).index(prefs['size']), horizontal=True, on_change=remember)
        st.toggle('減少動畫', key='pn-calm', value=prefs['calm'], on_change=remember)


def _header():
    from .brand import data_uri
    logo = data_uri(48)
    mark = f'<img src="{logo}" alt="">' if logo else ''
    with st.container(key='pn-head', horizontal=True, vertical_alignment='center'):
        st.markdown(f'<p class="pn-brand">{mark}<span>{view.NAME}</span></p>', unsafe_allow_html=True)
        _display_menu()


def _notes(job, store, health):
    notes = []
    if job:
        report = job.get('report') or {}
        if report.get('fallback_pages'):
            notes.append('第 ' + '、'.join(map(str, report['fallback_pages'])) + ' 頁暫時放了待補提示頁（不含教材原文），請老師補寫。')
        checks = _read(store.folder(job['id']) / 'teacher-checks.json', {})
        if checks:
            notes.append('第 ' + '、'.join(sorted(checks, key=int)) + ' 頁已保留內容，備註最前面標了【待教師確認】。')
    notes.extend(row['name'] + '：' + row['detail'] for row in health
                 if (row.get('key') == 'disk' and row.get('state') in ('warn', 'error')) or (row.get('key') == 'image' and row.get('state') == 'error'))
    return notes


def _act(head):
    try:
        if head['action'] == 'retry':
            Store().retry(head['job_id'])
        resume()
    except Exception as exc:  # noqa: BLE001 - a plain sentence instead of a stack trace
        st.error('沒有成功：' + (explain_error(str(exc)) or '請稍後再試，或到「系統」查看紀錄。'))
        return
    st.toast('已經開始。')
    st.rerun(scope='app')


def _stop_service():
    try:
        done = subprocess.run([sys.executable, str(ROOT / 'shutdown.py')], cwd=str(ROOT), capture_output=True, text=True, timeout=40,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            st.error('生成服務沒有停止：' + (done.stderr.strip() or done.stdout.strip() or '原因不明')[-300:])
        else:
            st.success('生成服務已停止；這個面板仍可使用，之後按「啟動並接著製作」即可恢復。')
    except (OSError, subprocess.TimeoutExpired) as exc:
        st.error('生成服務沒有停止：' + str(exc))


def _queue_menu():
    with st.popover('佇列'):
        if (DATA / 'pause').exists():
            st.caption('佇列已暫停：目前這一步做完後不會再往下。')
            if st.button('繼續佇列', key='pn-resume-queue', type='primary'):
                resume()
                st.rerun(scope='app')
        elif st.button('暫停佇列', key='pn-pause-queue', help='目前這一步做完後停下，已完成的頁面都保留。'):
            pause()
            st.toast('這一步做完後會暫停。')
        if st.session_state.get('pn-stop-ask'):
            st.warning('停止生成服務？正在做的這一步會中斷，已完成的頁面會保留。')
            yes, no = st.columns(2)
            if yes.button('停止', key='pn-stop-yes', type='primary'):
                st.session_state['pn-stop-ask'] = False
                _stop_service()
            if no.button('取消', key='pn-stop-no'):
                st.session_state['pn-stop-ask'] = False
                st.rerun(scope='fragment')
        elif st.button('停止生成服務', key='pn-stop'):
            st.session_state['pn-stop-ask'] = True
            st.rerun(scope='fragment')


def _tech(job, state):
    """Maintenance numbers (stage and page timing, problems, tokens) behind one switch."""
    from .monitoring import duration
    if job and (job.get('report') or {}).get('available'):
        report = job['report']
        if report['stages']:
            st.markdown(stage_table(report))
        if report['pages']:
            st.markdown(page_table(report))
        if report.get('problems'):
            st.markdown(problem_table(report['problems']))
    tokens = state.get('session_tokens') or {}
    if tokens:
        st.caption(f"本次啟動共 {tokens.get('total_tokens', 0):,} 詞元。")
    if job:
        usage = job.get('tokens') or {}
        st.caption(f"本份：輸入 {usage.get('prompt_tokens', 0):,}、輸出 {usage.get('output_tokens', 0):,} 詞元；載入 {duration(usage.get('load_seconds'))}、"
                   f"讀取 {duration(usage.get('prompt_seconds'))}、生成 {duration(usage.get('generation_seconds'))}；截斷 {usage.get('truncated_calls', 0)} 次。")


@st.fragment(run_every=f'{REFRESH}s')
def _telemetry():
    from .monitoring import snapshot
    store = Store()
    clock = time.strftime('%H:%M:%S')
    try:
        state = snapshot(store)
    except Exception:  # noqa: BLE001 - the database may be busy for a moment
        st.markdown(view.unavailable_html(REFRESH, clock), unsafe_allow_html=True)
        return
    job = state['job']
    try:
        queue = queue_rows(store.list())
    except Exception:  # noqa: BLE001
        queue = []
    try:
        feed = live_feed(store, job['id'] if job else None, 8)
    except Exception:  # noqa: BLE001
        feed = []
    try:
        health = service_health(state)
    except Exception:  # noqa: BLE001
        health = []
    head = headline(state, queue, health)
    notes = _notes(job, store, health)
    st.markdown(view.band_html(head, state, clock, queue, feed[0] if feed else None, notes), unsafe_allow_html=True)
    with st.container(key='pn-ops', horizontal=True, vertical_alignment='center'):
        if head['action'] and st.button(head['action_label'], key='pn-action', type='primary'):
            _act(head)
        _queue_menu()
    with st.expander('遙測詳情'):
        # Fixed height: the page never jumps when this opens or when events arrive; the content scrolls inside.
        with st.container(height=380, key='pn-detail-scroll', border=False):
            st.markdown(view.details_html(state, feed, health, notes), unsafe_allow_html=True)
            if st.toggle('維護用技術統計', key='pn-tech'):
                _tech(job, state)


def _teaching_prompt_editor(request_bits, context):
    from .curriculum_prompts import full_prompt, selected
    default = full_prompt(request_bits)
    if st.session_state.pop('nt-teaching-reset', False) or st.session_state.get('nt-teaching-context') != context:
        st.session_state['nt-teaching-editor'] = default
        st.session_state['nt-teaching-context'] = context
    with st.expander('教學提示詞（可修改，僅本次有效）'):
        st.caption('修改只套用到這份教材；開始製作後會還原預設，不會更改系統的教學提示詞。')
        edited = st.text_area('本次教學提示詞', key='nt-teaching-editor', height=360,
                              help='可直接修改教學方式、示範與練習要求；留空則使用系統預設。')

        def restore():
            st.session_state['nt-teaching-editor'] = default

        st.button('還原系統預設', key='nt-teaching-restore', on_click=restore)
        effective = edited if edited.strip() else default
        st.download_button('下載本次提示詞（.md）', effective.encode('utf-8'),
                           file_name=selected(request_bits)['age']['label'] + '_' + request_bits['subject'] + '_教學提示詞.md',
                           mime='text/markdown', key='nt-prompt')
    return edited if edited.strip() and edited.strip() != default.strip() else ''


def _make_tab():
    from .model_policy import configured_model
    store = Store()
    model = configured_model()
    form, side = st.columns([7, 3], gap='large')
    with form:
        unit, publisher, source, grade, subject, semester, difficulty, count, options = _task_form()
    with side:
        _task_brief(store, model, unit, publisher, source, grade, subject, semester, difficulty, count, options)


def _task_form():
    from .age_bands import band_for
    from .library import units as library_units
    from .local_images import enabled as image_enabled
    st.markdown('<p class="pn-step"><i>1</i>選擇主教材</p>', unsafe_allow_html=True)
    source_kind = st.segmented_control('來源', ['教材庫', '上傳檔案'], default='教材庫', key='nt-source', label_visibility='collapsed') or '教材庫'
    a, b, c, d = st.columns(4)
    grade = a.selectbox('年級', [4, 5, 6, 7, 8, 9], index=2, format_func=view.grade_name, key='nt-grade')
    subject = b.selectbox('科目', ['數學', '國語', '英語'], key='nt-subject')
    semester = c.selectbox('學期', ['上學期', '下學期'], key='nt-semester')
    difficulty = d.selectbox('難度', ['全部', '低難度', '中難度', '高難度'], key='nt-difficulty')
    source = unit = publisher = ''
    if source_kind == '教材庫':
        choices = [u for u in library_units() if u['grade'] == grade and u['subject'] == subject and u['semester'] == semester]
        if choices:
            chosen = st.selectbox('單元', choices, format_func=lambda u: (u.get('publisher') or '版本待核對') + '　' + u['title'], key='nt-unit')
            source, unit, publisher = chosen['path'], chosen['title'], chosen.get('publisher', '')
        else:
            st.info('教材庫裡還沒有這個年級、科目、學期的主教材，請改用「上傳檔案」。')
    else:
        upload = st.file_uploader('主教材檔案', type=['pdf', 'docx', 'md', 'txt'], key='nt-file', label_visibility='collapsed')
        left, right = st.columns(2)
        unit = left.text_input('單元名稱', key='nt-name')
        publisher = right.text_input('教材版本', key='nt-publisher')
        if upload:
            raw = upload.getvalue()
            folder = DATA / 'uploads'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (hashlib.sha256(raw).hexdigest() + Path(upload.name).suffix.lower())
            if not target.exists():
                target.write_bytes(raw)
            source = str(target)
    st.markdown('<p class="pn-step"><i>2</i>調整內容</p>', unsafe_allow_html=True)
    count = st.slider('簡報頁數（8～50 頁）', 8, 50, 12, key='nt-count')
    band = band_for(grade)
    st.caption(f"{band['label']}：每頁正文約 {band['body_target'][0]}～{band['body_target'][1]} 字、列點最多 {band['bullets_max']} 項，語氣與互動會配合這個年級。")
    request_bits = {'grade': grade, 'subject': subject, 'difficulty': difficulty}
    teaching_override = _teaching_prompt_editor(request_bits, (grade, subject, semester, difficulty, source, unit))
    with st.expander('進階選項'):
        review_outline = st.toggle('先確認大綱再製作', key='nt-outline', help='大綱完成後暫停，可修改頁序、主題與教學階段，再繼續製作。')
        worksheet = st.toggle('同時製作學習單與教師解答', key='nt-worksheet', help='完成後另外提供兩份可編輯的 Word 檔。')
        web_images = st.toggle('上網搜尋開放授權圖片並放進簡報', value=True, key='nt-web',
                               help='作者與授權寫在頁面下方與備註；搜尋失敗時仍輸出文字簡報。')
        ai_images = image_enabled() and st.toggle('優先用本機生圖製作教學插圖', value=True, key='nt-ai',
                                                  help='生圖服務就緒時生成；未就緒時改搜尋圖片。數線、維恩圖等一律用可編輯圖形。')
    options = dict(review_outline=review_outline, include_worksheet=worksheet, online_cc0_images=web_images, ai_illustrations=bool(ai_images))
    if teaching_override:
        options['teaching_prompt_override'] = teaching_override
    return unit, publisher, source, grade, subject, semester, difficulty, count, options


def _task_brief(store, model, unit, publisher, source, grade, subject, semester, difficulty, count, options):
    from . import strata
    st.markdown('<p class="pn-step"><i>3</i>確認並開始</p>', unsafe_allow_html=True)
    feedback = st.session_state.pop('nt-submit-feedback', None)
    if feedback:
        getattr(st, feedback[0])(feedback[1])
    labels = {'review_outline': '先確認大綱', 'include_worksheet': '附學習單與解答', 'online_cc0_images': '開放授權圖片',
              'ai_illustrations': '本機生圖', 'teaching_prompt_override': '本次自訂教學提示詞'}
    chosen = '、'.join(labels[k] for k, v in options.items() if v) or '無'
    blocked = strata.is_strata(model) and not strata.installed()
    ready = bool(source and unit)
    st.markdown(f'<dl class="pn-brief"><dt>單元</dt><dd>{view.e(unit or "尚未選擇")}</dd><dt>對象</dt><dd>{view.e(view.grade_name(grade) + subject + "　" + semester)}</dd>'
                f'<dt>頁數</dt><dd>{count} 頁</dd><dt>難度</dt><dd>{view.e(difficulty)}</dd><dt>選項</dt><dd>{view.e(chosen)}</dd></dl>', unsafe_allow_html=True)
    if blocked:
        st.warning('輕量模型還在安裝，裝好才能開始；進度在「系統與紀錄」。')
    if not ready:
        st.caption('選好主教材並填上單元名稱後就能開始。教材只在這台電腦上處理，不會上傳。')
    if st.button('開始製作簡報', key='nt-go', type='primary', disabled=not ready or blocked, width='stretch'):
        request = dict(schema_version=1, grade=grade, semester=semester, subject=subject, unit=unit, publisher=publisher,
                       difficulty=difficulty, slide_count=count, source_path=source, model=model, page_model=model, locale='zh-TW',
                       audience='國小學童' if grade <= 6 else '國中學生', **options)
        try:
            store.submit(request)
        except (ValueError, OSError) as exc:
            st.error('沒有建立任務：' + str(exc))
            return
        st.session_state['nt-teaching-reset'] = True
        try:
            resume()
            st.session_state['nt-submit-feedback'] = ('success', '已加入佇列，上方會即時顯示進度。本次教學提示詞已存入任務，編輯區已還原預設。')
        except (OSError, RuntimeError):
            st.session_state['nt-submit-feedback'] = ('warning', '任務與本次教學提示詞已存好，但製作程式沒有啟動；按上方「啟動並接著製作」就會開始。')
        st.rerun()


def _system_tab():
    from . import strata
    from .health import run as run_health_check
    check, logs = st.columns([5, 7], gap='large')
    with check:
        st.markdown('<p class="pn-sect">服務檢查</p>', unsafe_allow_html=True)
        if strata.settings().get('generation_architecture') == 'strata_iq3_s':
            state = strata.install_status()
            if state['installed']:
                st.success(f'輕量模型已安裝，上下文 {strata.context_limit():,} 詞元。')
            elif state['running']:
                st.info('輕量模型正在下載與安裝。')
            elif st.button('安裝輕量模型', key='sys-strata'):
                strata.start_installation()
            if state.get('log'):
                st.code('\n'.join(state['log'].splitlines()[-12:]), language='text')
        st.caption('逐項檢查模型、資料庫、轉檔與生圖服務，約需一分鐘。')
        if st.button('開始檢查', key='sys-check', type='primary'):
            with st.spinner('檢查中…'):
                st.session_state['sys-health'] = run_health_check()
        if 'sys-health' in st.session_state:
            st.markdown(view.health_html(health_rows(st.session_state['sys-health'])), unsafe_allow_html=True)
    with logs:
        st.markdown('<p class="pn-sect">運行紀錄</p>', unsafe_allow_html=True)
        store = Store()
        rows = store.list()
        names = {row['id']: view.job_title(_request(row)) + '　' + row['id'][:8] for row in rows}
        scope = st.selectbox('範圍', ['系統整體'] + [row['id'] for row in rows], format_func=lambda v: names.get(v, v), key='sys-scope')
        job_id = None if scope == '系統整體' else scope
        path = SYSTEM_LOG if job_id is None else store.folder(job_id) / 'run.jsonl'
        events = recent_events(path, 100)
        if events:
            st.caption('最近 100 筆，新的在上面。教材原文與提示詞不會寫進紀錄。')
            st.markdown(markdown_table(['時間', '事件', '階段', '頁', '說明', '耗時（秒）'], event_rows(events)))
        else:
            st.caption('這個範圍還沒有紀錄。')
        left, right = st.columns(2)
        if Path(path).is_file():
            with left:
                _download('下載紀錄', path, 'sys-dl-' + scope)
        if right.button('清除這個範圍的紀錄', key='sys-clear-' + scope):
            try:
                st.success(f'已清除 {clear_log(job_id):,} 位元組；教材與任務都保留。')
            except (OSError, ValueError) as exc:
                st.error(explain_error(str(exc)) or '清除失敗，請稍後再試。')
        with st.expander('簡報修改記錄（分析用）'):
            from .change_log import history_paths
            paths = history_paths(store.root, job_id)
            st.caption('記錄修改前後內容、頁碼、欄位、原因與模型；系統整體按月份保存，另保留每份教材的記錄。')
            if not paths:
                st.caption('後續簡報修改會自動記錄在這裡。')
            for log_path in reversed(paths):
                label = '下載本教材修改記錄' if job_id else '下載 ' + log_path.stem + ' 修改記錄'
                _download(label, log_path, 'change-log-' + scope + '-' + log_path.stem)


def _quality(data, out):
    """Plain sentences about what the checks found, most important first."""
    lines = []
    checks = _read(out / 'teacher-checks.json', {})
    if checks:
        lines.append(('warn', '請老師確認這幾頁：' + '；'.join(f"第 {n} 頁（{str(info.get('reason', ''))[:50]}）"
                                                    for n, info in sorted(checks.items(), key=lambda x: int(x[0])))))
    if data.get('fallback_pages'):
        lines.append(('warn', '待補提示頁（不含教材原文）：第 ' + '、'.join(map(str, data['fallback_pages'])) + ' 頁。'))
    if data.get('qa_warning_pages'):
        lines.append(('warn', '仍有教學品質提醒：第 ' + '、'.join(map(str, data['qa_warning_pages'])) + ' 頁。'))
    visual = data.get('visual_qa') or {}
    if visual.get('remaining_pages'):
        lines.append(('warn', '版面可能還不夠好：第 ' + '、'.join(map(str, visual['remaining_pages'])) + ' 頁。'))
    elif visual.get('checked_pages'):
        lines.append(('ok', f"版面逐頁檢查 {visual['checked_pages']} 頁" + (f"，自動修好 {visual['fixed']} 處。" if visual.get('fixed') else '，沒有問題。')))
    if data.get('missing_image_pages'):
        lines.append(('warn', '找不到合適插圖、改用文字版面：第 ' + '、'.join(map(str, data['missing_image_pages'])) + ' 頁。'))
    if data.get('worksheet_status') == 'failed':
        lines.append(('warn', '學習單沒有完成：' + str(data.get('worksheet_error') or '請查看運行紀錄。')))
    summary = data.get('qa_summary') or {}
    if summary:
        first = summary.get('first_passed', summary.get('passed', 0))
        lines.append(('ok', f"教學品質：{first}／{summary.get('pages', 0)} 頁一次通過，重寫 {len(summary.get('regenerated_pages', []))} 頁。"))
    optimization = _read(out / 'final-optimization.json', {})
    if optimization:
        if optimization.get('status') == 'skipped':
            lines.append(('ok', '最後優化：沒有發現疑慮，版面與格式維持不變。'))
        else:
            lines.append(('ok' if optimization.get('status') == 'completed' else 'warn',
                          f"最後優化：檢查 {optimization.get('pages_checked', optimization.get('pages', 0))} 頁，修正 {len(optimization.get('changes', []))} 處。"))
    validation = _read(out / 'deck-validation.json', {})
    for item in (validation.get('findings') or [])[:20]:
        lines.append(('note', ('第 ' + str(item['page']) + ' 頁：' if item.get('page') else '整份：') + str(item.get('message', ''))))
    return lines


def _outline(row, store, out):
    from .design import PHASE_FUNCTION
    current = _read(out / 'plan.json', {'objectives': [], 'slides': []})
    st.info('大綱好了。確認後才會逐頁製作；改「順序」可以重新排列。')
    with st.form('outline-' + row['id']):
        objectives = st.text_area('學習目標（每行一項）', value='\n'.join(current['objectives']))
        entries = [{'順序': i + 1, '主題': s['topic'], '教學階段': s['phase'], '難度': s['difficulty'], '版型': s['layout_id'],
                    '頁面角色': s.get('page_role', ''), '階段': s.get('stage', ''), '學生任務': s.get('student_task', ''),
                    '迷思頁': bool(s.get('misconception')), '主教材頁碼': ','.join(map(str, s['source_pages']))}
                   for i, s in enumerate(current['slides'])]
        edited = st.data_editor(entries, num_rows='fixed', hide_index=True, key='outline-rows-' + row['id'])
        approved = st.form_submit_button('確認大綱並繼續', type='primary')
    if approved:
        try:
            slides = []
            for item in sorted(edited, key=lambda x: int(x['順序'])):
                entry = {'topic': item['主題'], 'phase': item['教學階段'], 'difficulty': item['難度'], 'layout_id': item['版型'],
                         'source_pages': [int(p.strip()) for p in str(item['主教材頁碼']).split(',') if p.strip()]}
                if str(item.get('學生任務', '')).strip() or item.get('頁面角色'):
                    entry.update(function=PHASE_FUNCTION.get(item['教學階段'], 'Concept'), page_role=item.get('頁面角色') or None,
                                 stage=item.get('階段') or None, student_task=str(item.get('學生任務', '')).strip(),
                                 misconception=bool(item.get('迷思頁')))
                    entry = {k: v for k, v in entry.items() if v is not None}
                slides.append(entry)
            approve_outline(row['id'], {'objectives': [s.strip() for s in objectives.splitlines() if s.strip()], 'slides': slides}, store)
            resume()
            st.toast('已確認，繼續製作。')
            st.rerun()
        except (ValueError, KeyError, TypeError) as exc:
            st.error('大綱沒有存檔：' + str(exc))


def _changes(row, req, store, out):
    from . import restyle
    from .template_styles import style_for
    count = len(_read(out / 'plan.json', {'slides': []})['slides'])
    if row['status'] in ('done', 'failed') and count:
        st.markdown('<p class="pn-sect">重做某一頁</p>', unsafe_allow_html=True)
        a, b = st.columns([1, 2])
        page = a.number_input('頁碼', 1, count, 1, key='redo-page-' + row['id'])
        field = b.selectbox('範圍', list(FIELDS), key='redo-field-' + row['id'])
        wish = st.text_input('要怎麼改', key='redo-text-' + row['id'], placeholder='例如：把例題換成分數乘法')
        if st.button('重做這一頁', key='redo-go-' + row['id'], disabled=not wish, type='primary'):
            try:
                new = regenerate(row['id'], int(page) - 1, wish, store, FIELDS[field])
                resume()
                st.success('已建立修訂任務 ' + new[:8] + '，原本的簡報保留不動。')
            except Exception as exc:  # noqa: BLE001
                st.error('沒有開始：' + str(exc))
    if style_for(req.get('grade'), req.get('subject')).get('look') == 'mission' and not restyle.is_current(req, out) and restyle.can_restyle(row, out):
        st.markdown('<p class="pn-sect">新版面</p>', unsafe_allow_html=True)
        st.caption('這份是舊版面。換成新的國中版面不會重寫內容、不用模型，約一分鐘；原檔會先備份。')
        if st.button('套用新版面', key='restyle-' + row['id']):
            try:
                with st.spinner('重新排版中…'):
                    st.success(restyle.restyle(row['id'], store)['message'])
            except ValueError as exc:
                st.error(str(exc))
    st.markdown('<p class="pn-sect">移除</p>', unsafe_allow_html=True)
    if st.session_state.get('remove-ask-' + row['id']):
        st.warning(f'「{view.job_title(req)}」會先放進回收區，之後還可以還原。')
        yes, no = st.columns(2)
        if yes.button('確定移除', key='remove-yes-' + row['id'], type='primary'):
            try:
                store.remove_job(row['id'])
                st.toast('已移到回收區。')
                st.rerun()
            except (ValueError, KeyError, OSError) as exc:
                st.error('沒有移除：' + str(exc))
        if no.button('取消', key='remove-no-' + row['id']):
            st.session_state['remove-ask-' + row['id']] = False
            st.rerun(scope='fragment')
    elif st.button('移除這份任務', key='remove-' + row['id']):
        st.session_state['remove-ask-' + row['id']] = True
        st.rerun(scope='fragment')


@st.dialog('任務', width='large')
def _job(job_id):
    from .job_thumb import page_thumbs, previews
    store = Store()
    try:
        row = store.get(job_id)
    except KeyError:
        st.info('找不到這份任務，可能已經移除。')
        return
    req, out = _request(row), store.folder(job_id)
    data, files = _files(job_id, store)
    mark = view.bucket(row['status'])
    st.markdown(f'<div class="pn-dhead {mark}"><b>{view.e(view.job_title(req))}</b>'
                f'<small><i class="dot"></i>{view.e(status_text(row["status"]))}　{view.e(view.job_meta(req))}</small></div>', unsafe_allow_html=True)
    with st.container(horizontal=True):
        if 'pptx' in files:
            _download('下載簡報', files['pptx'], 'job-pptx-' + job_id, primary=True)
        if 'pdf' in files:
            _download('下載 PDF', files['pdf'], 'job-pdf-' + job_id)
        if row['status'] == 'failed' and st.button('從失敗處重試', key='job-retry-' + job_id, type='primary'):
            try:
                store.retry(job_id)
                resume()
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error('沒有重新開始：' + str(exc))
        if row['status'] in view.BUSY and row['status'] != 'staging' and st.button('暫停這份', key='job-pause-' + job_id):
            try:
                store.pause_job(job_id)
                st.rerun()
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                st.error(str(exc))
        if row['status'] in ('paused', 'pausing') and st.button('繼續這份', key='job-resume-' + job_id, type='primary'):
            try:
                store.resume_job(job_id)
                resume()
                st.rerun()
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                st.error(str(exc))
    if row['status'] != 'done':
        step = min(row['stage'], len(STAGES))
        saved = len(list((out / 'slides').glob('*.json')))
        name = STAGE_LABELS[STAGES[min(row['stage'], len(STAGES) - 1)]]
        st.progress(step / len(STAGES), text=f'第 {step + 1}／{len(STAGES)} 步　{name}　已寫好 {saved}／{req.get("slide_count", 0)} 頁')
    if row['error']:
        st.warning((explain_error(row['error']) or '過程中出了點問題。') + ' 做好的頁面都保留著，重試會從失敗的地方接著做。')
        with st.expander('原始錯誤訊息'):
            st.code(row['error'][-1200:], language='text')
    if row['status'] == 'awaiting_outline' and (out / 'plan.json').exists():
        _outline(row, store, out)
    pages = previews(out)
    others = {k: v for k, v in files.items() if k not in ('pptx', 'pdf')}
    names = (['頁面'] if pages else []) + (['檔案'] if others else []) + (['品質'] if row['status'] in ('done', 'failed') else []) + ['修改']
    for name, tab in zip(names, st.tabs(names)):
        with tab:
            if name == '頁面':
                thumbs = page_thumbs(out)
                st.markdown(view.thumbs_html(thumbs, len(pages)), unsafe_allow_html=True)
                number = st.number_input('放大看第幾頁', 1, len(pages), 1, key='zoom-' + job_id)
                st.image(str(pages[int(number) - 1]))
            elif name == '檔案':
                for kind, path in others.items():
                    _download(f'{FILES.get(kind, "檔案")}（{path.suffix}）', path, f'job-{kind}-{job_id}')
            elif name == '品質':
                found = _quality(data, out)
                if not found:
                    st.caption('沒有需要特別注意的地方。')
                for level, text in found:
                    (st.warning if level == 'warn' else st.caption)(text)
            else:
                _changes(row, req, store, out)


@st.dialog('移除這份教材？')
def _confirm_remove(job_id, title):
    st.write(f'「{title}」會先放進回收區，不會馬上消失，之後還可以還原。')
    yes, no = st.columns(2)
    if yes.button('確定移除', key='rm-yes-' + job_id, type='primary', width='stretch'):
        try:
            Store().remove_job(job_id)
            st.toast('已移到回收區。')
            st.rerun()
        except (ValueError, KeyError, OSError) as exc:
            st.error('沒有移除：' + str(exc))
    if no.button('先不要', key='rm-no-' + job_id, width='stretch'):
        st.rerun()


def _card(row, req, store):
    from .job_thumb import cover_uri
    from .monitoring import production_seconds
    job_id, out = row['id'], store.folder(row['id'])
    stage_name = STAGE_LABELS[STAGES[min(row['stage'], len(STAGES) - 1)]]
    saved = len(list((out / 'slides').glob('*.json'))) if row['status'] != 'done' else 0
    with st.container(key='card-' + job_id[:12]):
        st.markdown(view.card_html(row, req, stage_name, saved, cover_uri(out),
                                   elapsed_seconds=production_seconds(store, row)), unsafe_allow_html=True)
        with st.container(horizontal=True, vertical_alignment='center'):
            pptx = _files(job_id, store)[1].get('pptx') if row['status'] == 'done' else None
            if pptx:
                _download('下載簡報', pptx, 'card-dl-' + job_id, primary=True)
            elif row['status'] == 'failed':
                if st.button('從失敗處重試', key='card-retry-' + job_id, type='primary'):
                    try:
                        store.retry(job_id)
                        resume()
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error('沒有重新開始：' + str(exc))
            elif st.button('開啟', key='card-open-' + job_id, type='primary'):
                _job(job_id)
            with st.popover('更多'):
                if st.button('預覽與檔案', key='card-view-' + job_id, width='stretch'):
                    _job(job_id)
                if row['status'] in view.BUSY and row['status'] != 'staging':
                    if st.button('暫停這份', key='card-pause-' + job_id, width='stretch'):
                        try:
                            store.pause_job(job_id)
                            st.rerun()
                        except (ValueError, KeyError, OSError, RuntimeError) as exc:
                            st.error(str(exc))
                elif row['status'] in ('paused', 'pausing'):
                    if st.button('繼續這份', key='card-resume-' + job_id, width='stretch'):
                        try:
                            store.resume_job(job_id)
                            resume()
                            st.rerun()
                        except (ValueError, KeyError, OSError, RuntimeError) as exc:
                            st.error(str(exc))
                if st.button('移除…', key='card-rm-' + job_id, width='stretch'):
                    _confirm_remove(job_id, view.job_title(req))


def _jobs_tab(store):
    rows = store.list()[:60]
    if not rows:
        st.markdown('<p class="pn-empty">還沒有任何教材。到「製作教材」選好單元，按「開始製作簡報」，做好的簡報就會出現在這裡。</p>',
                    unsafe_allow_html=True)
        return
    found = view.counts(rows)
    with st.container(key='pn-bar', horizontal=True, vertical_alignment='center'):
        which = st.segmented_control('篩選', list(view.BUCKETS), default='all', key='pn-filter', label_visibility='collapsed',
                                     format_func=lambda k: f'{view.BUCKETS[k]} {found[k]}') or 'all'
        query = st.text_input('搜尋', key='pn-query', placeholder='搜尋單元、年級或科目', label_visibility='collapsed')
    shown = [(row, req) for row in rows for req in [_request(row)] if view.matches(row, req, query, which)]
    if not shown:
        st.markdown('<p class="pn-empty">沒有符合的教材。換個關鍵字或篩選看看。</p>', unsafe_allow_html=True)
        return
    with st.container(key='pn-cards'):
        for row, req in shown:
            _card(row, req, store)


def _signature(store):
    try:
        return [(r['id'], r['status'], r['stage']) for r in store.list()[:30]]
    except Exception:  # noqa: BLE001
        return []


@st.fragment(run_every='3s')
def _watch(seen):
    """Redraw the manifest once when a deck starts, finishes or changes stage."""
    if _signature(Store()) != seen:
        st.rerun()


def show():
    if 'pn-prefs' not in st.session_state:
        st.session_state['pn-prefs'] = load_prefs()
    prefs = st.session_state['pn-prefs']
    prefs['theme'] = normalize_theme(st.session_state.get('pn-theme', prefs['theme']))
    if 'pn-theme' in st.session_state:
        st.session_state['pn-theme'] = prefs['theme']
    st.markdown(css(prefs['theme'], prefs['size'], prefs['calm']), unsafe_allow_html=True)
    store = Store()
    _header()
    _telemetry()
    _watch(_signature(store))
    make, decks, system = st.tabs(['製作教材', '我的教材', '系統與紀錄'])
    with make:
        _make_tab()
    with decks:
        _jobs_tab(store)
    with system:
        _system_tab()
