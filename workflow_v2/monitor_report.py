"""監控頁使用的執行紀錄分析：純 Python、不依賴 pandas，容忍缺檔、半行與壞 JSON。"""
import json
import re
import threading
import time
from collections import Counter, OrderedDict, deque
from datetime import datetime
from pathlib import Path

STAGE_ORDER = ('source', 'plan', 'write', 'review', 'render', 'preview', 'publish')
STAGE_LABELS = {
    'source': '讀取主教材', 'plan': '規劃大綱', 'write': '逐頁編寫',
    'review': '本地模型審核', 'render': '製作簡報',
    'preview': '製作預覽', 'publish': '最後內容優化與整理成果',
}
EVENT_LABELS = {
    'engine_started': '模型服務啟動', 'engine_stopped': '模型服務停止',
    'engine_start_failed': '模型服務啟動失敗', 'orphan_model_worker_stopped': '已停止殘留模型程序',
    'image_service_started': '圖像服務啟動', 'image_generation_unavailable': '本機圖像無法使用',
    'image_priority_probe_failed': '圖像優先檢查失敗', 'image_priority_unload_failed': '圖像模型卸載失敗',
    'image_generation_finished': '插圖完成', 'image_generation_failed': '插圖失敗',
    'image_diagram_fallback': '已建立教學圖解後備',
    'image_text_fallback': '未取得插圖，保留文字與補圖提醒',
    'final_optimization_started': '開始最後內容優化',
    'final_optimization_completed': '最後內容優化完成',
    'final_optimization_unavailable': '最後內容優化未完成',
    'final_optimization_skipped': '最後內容優化：沒有疑慮，已略過',
    'concurrency_decision': '同時編寫設定', 'concurrency_degraded': '同時編寫降為一頁',
    'concurrency_restart_failed': '同時編寫設定調整未成功', 'write_concurrency': '編寫頁數設定',
    'model_call_started': '模型開始處理', 'model_call_finished': '模型回覆完成',
    'model_call_error': '模型呼叫失敗', 'model_retry_scheduled': '排定重試',
    'model_unload_failed': '模型卸載失敗', 'model_response_rejected': '模型回覆格式不合格',
    'model_escalation': '改用較大模型修復',
    'source_ocr_started': '開始辨識掃描頁', 'source_ocr_finished': '掃描頁辨識完成',
    'analysis_fallback': '教材解析改用保底', 'outline_prompt_ready': '大綱提示已備妥',
    'qa_rejected': '品質檢查退回', 'draft_recovered': '已復原草稿',
    'fallback_page_created': '改用待補提示頁（不含教材原文）', 'page_cache_invalidated': '頁面快取已失效',
    'page_retry': '頁面重寫', 'review_batch_ready': '審核批次就緒',
    'review_batch_split': '審核批次拆分', 'review_batch_unavailable': '審核批次失敗',
    'review_rejected': '審核發現問題', 'draft_kept_for_check': '保留草稿並請老師確認', 'review_unresolved': '審核疑問已標示', 'worksheet_generated': '學習單完成',
    'worksheet_generation_failed': '學習單失敗', 'page_split': '頁面自動拆分',
    'layout_downgraded': '版面改用保底', 'template_selected': '舊版選版紀錄',
    'visual_qa': '版面檢查', 'visual_qa_failed': '版面檢查未完成',
    'system_snapshot': '系統快照', 'job_snapshot': '工作快照', 'job_submitted': '工作已建立',
    'job_event': '工作事件', 'job_paused': '工作已暫停', 'job_pause_requested': '要求暫停',
    'stage_interrupt_resolved': '中斷處理完成', 'job_resumed': '工作已繼續',
    'job_remove_requested': '要求移除', 'job_removed': '工作已移除',
    'source_changed_restart': '主教材變更，重新開始', 'stage_started': '階段開始',
    'stage_completed': '階段完成', 'stage_failed': '階段失敗',
    'stage_interrupted': '階段中斷', 'stage_cancelled': '階段取消',
}
# 嚴重度：error 代表需要處理，warning 代表系統已自動處理但值得留意。
LEVELS = {
    'model_call_error': 'error', 'stage_failed': 'error', 'engine_start_failed': 'error',
    'worksheet_generation_failed': 'error', 'review_batch_unavailable': 'error',
    'image_generation_failed': 'error',
    'model_unload_failed': 'warning', 'analysis_fallback': 'warning',
    'model_retry_scheduled': 'warning', 'model_response_rejected': 'warning',
    'qa_rejected': 'warning', 'fallback_page_created': 'warning',
    'review_rejected': 'warning', 'layout_downgraded': 'warning', 'draft_kept_for_check': 'warning', 'review_unresolved': 'warning',
    'image_generation_unavailable': 'warning', 'review_batch_split': 'warning',
    'model_escalation': 'warning', 'source_changed_restart': 'warning',
    'concurrency_degraded': 'warning', 'concurrency_restart_failed': 'warning',
    'final_optimization_unavailable': 'warning', 'image_text_fallback': 'warning', 'visual_qa_failed': 'warning',
}
CODE_LABELS = {
    'mismatch': '標題與內容對不上', 'ghost_image': '文字提到圖，頁面卻沒有圖', 'hook_dense': '導入頁文字過多',
    'verbatim_copy': '內容和主教材原文太像，要用自己的話改寫', 'truncated': '句子沒有寫完', 'no_visual': '缺少圖解或圖片', 'too_long': '文字太多', 'long_sentence': '句子太長',
    'untraceable': '算式裡有來源不明的數字', 'residue': '混入殘留文字', 'no_task': '缺少學生任務', 'no_example': '缺少具體例子',
}
# 原始原因 → 白話（依序比對，第一個命中者生效）
REASON_LABELS = (
    ('截斷', '句子沒有寫完'), ('沒有圖', '文字提到圖，頁面卻沒有圖'), ('標題提到', '標題和內容對不上'),
    ('數字找不到來源', '算式裡有來源不明的數字'), ('單次修復後審核仍未通過', '審核員仍有疑問'),
    ('審核服務失敗', '模型審核時沒有回應'), ('修復失敗', '修正後仍未通過檢查'), ('審核未通過', '審核員仍有疑問'),
    ('需要圖解', '缺少圖解或圖片'),
)


def plain_reason(raw, limit=60):
    text = str(raw or '')
    for needle, label in REASON_LABELS:
        if needle in text:
            return label
    return explain_error(text) or _first_line(text, limit) or '原因未記錄'

# (關鍵字, 白話說明)；依序比對，第一個命中者生效。
ERROR_HINTS = (
    (('not found', 'http 404'), '找不到指定的本地模型，請確認模型已安裝且與系統設定一致。'),
    (('out of memory', 'cuda', '顯存'), '顯存不足，建議關閉其他占用顯卡的程式後重試。'),
    (('http 500',), '模型服務內部錯誤（多半是顯存不足或模型崩潰），系統會卸載模型後自動重試。'),
    (('http 502', 'http 503', 'http 504'), '模型服務暫時無法回應，系統會自動重試。'),
    (('connection', 'refused', 'max retries', 'connection_error', '連線'), '連不上本機模型服務，請確認模型服務已啟動。'),
    (('timeout', 'timed out', '逾時', '超時'), '處理逾時，可能是模型回覆太慢或顯卡被占用。'),
    (('輸出截斷',), '模型回覆被截斷，系統會要求精簡後重寫。'),
    (('無完整有效 json', '無完整有效json'), '模型多次沒有回傳完整格式，已放棄這次請求。'),
    (('輸入過長',), '輸入內容超過模型上限，需要先分段整理教材。'),
    (('異常結束',), '工作程序異常結束，請查看該階段的日誌檔。'),
    (('permission', 'winerror 32', 'being used'), '檔案正被其他程式占用，請關閉後重試。'),
    (('損毀',), '工作資料損毀，請重新建立此份教材。'),
    (('libreoffice', '轉檔未完成', 'pdf頁數', 'pdf 頁數'), '簡報轉成預覽檔失敗，請確認簡報轉檔程式可正常開啟，再按「從失敗階段重試」。'),
    (('overflow', '單頁保底排版', '排版仍無法'), '有頁面內容太多、排不進版面；完整原稿已保留，請在「簡報檢查明細」查看該頁並手動調整。'),
    (('沒有可引用的主教材', '主教材'), '主教材內容有問題或無法讀取，請確認檔案可正常開啟，必要時重新上傳。'),
)

TAIL_BYTES = 2_000_000
CHUNK_BYTES = 8_000_000
MAX_PROBLEMS = 60
CACHE_LIMIT = 12
_LOCK = threading.Lock()
_CACHE = OrderedDict()
_PAGE_RE = re.compile(r'第\s*(\d+)\s*(?:[～~\-－至到]\s*(\d+))?\s*頁')


def explain_error(text, status=None):
    """把原始錯誤轉成白話中文；無法判斷時回傳空字串。"""
    blob = (str(text or '') + (' http ' + str(status) if status else '')).lower()
    for keys, hint in ERROR_HINTS:
        if any(key in blob for key in keys):
            return hint
    return ''


def seconds_text(value):
    try:
        value = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return '—'
    hours, rest = divmod(value, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours} 小時 {minutes} 分'
    if minutes:
        return f'{minutes} 分 {secs:02d} 秒'
    return f'{secs} 秒'


def _num(value, default=0.0):
    try:
        number = float(value)
        return number if number == number and abs(number) != float('inf') else default
    except (TypeError, ValueError):
        return default


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def clock_text(epoch):
    try:
        return datetime.fromtimestamp(epoch).strftime('%m-%d %H:%M:%S')
    except (TypeError, ValueError, OSError, OverflowError):
        return '—'


def pages_in(label):
    """從「編寫第 3 頁」「審核第 4～6 頁」取出頁碼；沒有則回傳空清單。"""
    match = _PAGE_RE.search(str(label or ''))
    if not match:
        return []
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if last < first or last - first > 60:
        last = first
    return list(range(first, last + 1))


FIELD_LABELS = {
    'heading': '標題', 'subheading': '副標題', 'body': '內容', 'bullets': '重點', 'steps': '解題步驟',
    'notes': '教師備註', 'speaker_notes': '教師備註', 'answer': '答案', 'question': '題目',
    'columns': '欄位內容', 'points': '要點', 'header': '欄位標題', 'visual_asset': '圖片描述',
    'visual_model': '圖形', 'media_hint': '圖片提示', 'code_snippet': '程式碼', 'code': '程式碼',
    'hint': '提示', 'solution': '解法', 'explanation': '說明', 'keyword': '關鍵字',
}
_FIELD_RE = re.compile(r'[（(]([A-Za-z_][A-Za-z_0-9.\[\]]*)[）)]')


def localize_fields(text):
    """品質檢查原因常以英文欄位名結尾，例如「（heading）」；顯示時改成中文。"""
    def one(match):
        parts = [part for part in re.split(r'[.\[\]]+', match.group(1)) if part and not part.isdigit()]
        names = [FIELD_LABELS.get(part, '其他欄位') for part in parts]
        return '（' + '．'.join(dict.fromkeys(names) or ['欄位']) + '）'
    return _FIELD_RE.sub(one, str(text))


def _first_line(value, limit=90):
    lines = [part.strip() for part in str(value or '').splitlines() if part.strip()]
    text = ''
    for line in lines:
        if line.startswith('-'):
            text = line.lstrip('- ').strip()
            break
    text = localize_fields(text or (lines[0] if lines else ''))
    return text[:limit] + ('…' if len(text) > limit else '')


def describe(event):
    """每筆事件的一句中文說明，供表格與異常清單使用。"""
    name = event.get('event')
    bits = []
    label = event.get('label')
    if label:
        bits.append(str(label))
    if name in ('model_call_started', 'model_call_finished') and event.get('attempt'):
        bits.append(f"第 {event['attempt']} 次嘗試")
    if name == 'model_call_finished':
        bits.append(f"輸入 {int(_num(event.get('prompt_tokens'))):,}、輸出 {int(_num(event.get('output_tokens'))):,} 詞元")
        if event.get('done_reason') == 'length':
            bits.append('回覆被截斷')
    if name == 'model_retry_scheduled':
        bits.append(f"第 {event.get('retry_count', '?')} 次重試，等待 {seconds_text(event.get('delay_seconds'))}")
        hint = explain_error(event.get('reason'), event.get('http_status'))
        if hint:
            bits.append(hint)
    if name in ('model_call_error', 'stage_failed', 'engine_start_failed', 'worksheet_generation_failed',
                'review_batch_unavailable', 'image_generation_failed', 'model_unload_failed', 'analysis_fallback',
                'image_priority_probe_failed', 'image_priority_unload_failed',
                'review_batch_split', 'final_optimization_unavailable', 'image_text_fallback'):
        raw = event.get('error') or event.get('reason') or ''
        hint = explain_error(raw, event.get('http_status'))
        bits.append(hint or _first_line(raw, 80) or '原因未記錄')
    if name == 'model_response_rejected':
        bits.append(explain_error(event.get('reason')) or _first_line(event.get('reason'), 80))
    if name == 'qa_rejected':
        codes = [CODE_LABELS.get(str(code), '內容需要調整') for code in (event.get('codes') or []) if code]
        bits.append('自動檢查發現：' + ('、'.join(dict.fromkeys(codes)) or '內容需要調整') + '。已請模型照意見重寫這頁（正常修正流程）')
    if name == 'page_retry':
        bits.append('重寫原因：' + plain_reason(event.get('reason')))
    if name == 'fallback_page_created':
        bits.append('重寫後仍有問題（' + plain_reason(event.get('reason')) + '）。為避免顯示錯誤內容或照抄教材，這頁先放一張不含教材原文的待補提示頁；請老師看一下，用自己的話補寫')
    if name == 'draft_kept_for_check':
        codes = [CODE_LABELS.get(str(code), '內容需要調整') for code in (event.get('codes') or []) if code]
        bits.append('保留了寫好的內容，但「' + ('、'.join(dict.fromkeys(codes)) or '部分內容') + '」尚未解決；備註最前面已標示【待教師確認】')
    if name == 'review_rejected':
        issues = event.get('issues') or []
        bits.append(f"審核員有 {event.get('issue_count', len(issues))} 項疑問：" + _first_line(issues[0] if issues else '', 60) + '。已請模型修正後再審一次')
    if name == 'review_unresolved':
        issues = event.get('issues') or []
        bits.append('修正後審核員仍有疑問：' + _first_line(issues[0] if issues else '', 60) + '。這頁已保留並標示【待教師確認】' + ('（有疑問的圖解已移除）' if event.get('visual_dropped') else ''))
    if name == 'visual_qa':
        bits.append(f"逐頁看過成品：發現 {event.get('found', 0)} 處版面問題，自動修好 {event.get('fixed', 0)} 處"
                    + (f"，還有第 {'、'.join(map(str, event.get('pages') or []))} 頁請你看一下" if event.get('remaining') else '，目前沒有需要你處理的'))
    if name == 'visual_qa_failed':
        bits.append('這次沒能完成版面檢查，簡報本身不受影響')
    if name == 'image_generation_unavailable':
        bits.append('本機生圖服務沒有開啟（選用功能）。這份簡報改用授權素材搜尋與可編輯圖解，內容不受影響')
    if name in ('page_split', 'layout_downgraded'):
        bits.append(_first_line(event.get('reason'), 80))
    if name == 'job_event':
        bits.append(_first_line(event.get('message'), 80))
    if name in ('stage_started',) and event.get('attempt'):
        bits.append(f"第 {event['attempt']} 次執行")
    if name in ('stage_completed', 'stage_interrupted', 'stage_cancelled') and event.get('duration_seconds') is not None:
        bits.append('耗時 ' + seconds_text(event.get('duration_seconds')))
    if name == 'job_submitted':
        bits.append(str(event.get('unit', ''))[:60])
    if name in ('concurrency_decision', 'concurrency_degraded', 'concurrency_restart_failed', 'write_concurrency'):
        bits.append(_first_line(event.get('message'), 120))
    if name == 'final_optimization_skipped':
        bits.append(f"逐頁離線檢查沒有發現疑慮（共 {event.get('pages', 0)} 頁），不需要再讓模型精修，省下約半分鐘")
    if name == 'final_optimization_completed':
        bits.append(f"只精修有疑慮的 {event.get('pages_checked', event.get('pages', 0))} 頁（全部 {event.get('pages', 0)} 頁），套用 {event.get('changes', 0)} 處安全修改")
        bits.append('排版保持不變' if event.get('layout_preserved') else '需檢查排版')
        if event.get('issues'):bits.append(f"{event['issues']} 項待確認")
    return '；'.join(bit for bit in bits if bit)[:260]


class _Stats:
    """逐步累加的統計；每次只讀檔案新增的完整行。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.offset = 0
        self.head = b''
        self.events = 0
        self.bad_lines = 0
        self.last_time = None
        self.first_time = None
        self.calls_started = 0
        self.calls_finished = 0
        self.calls_failed = 0
        self.model_retries = 0
        self.rejected = 0
        self.truncated = 0
        self.gpu_wait = 0.0
        self.call_seconds = []
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.stage = {name: Counter() for name in STAGE_ORDER}
        self.pages = {}
        self.problems = deque(maxlen=MAX_PROBLEMS)
        self.levels = Counter()
        self.kinds = Counter()

    def _page(self, number):
        return self.pages.setdefault(number, Counter())

    def feed(self, event):
        name = str(event.get('event') or '')
        stage = str(event.get('stage') or '')
        when = parse_time(event.get('time'))
        self.events += 1
        if when is not None:
            self.last_time = when if self.last_time is None else max(self.last_time, when)
            self.first_time = when if self.first_time is None else min(self.first_time, when)
        bucket = self.stage.get(stage)
        pages = pages_in(event.get('label'))
        if name == 'model_call_started':
            self.calls_started += 1
            self.gpu_wait += _num(event.get('gpu_wait_seconds'))
        elif name == 'model_call_finished':
            seconds = _num(event.get('duration_seconds'))
            self.calls_finished += 1
            self.call_seconds.append(seconds)
            self.prompt_tokens += int(_num(event.get('prompt_tokens')))
            self.output_tokens += int(_num(event.get('output_tokens')))
            self.truncated += event.get('done_reason') == 'length'
            if bucket is not None:
                bucket['calls'] += 1
                bucket['call_seconds'] += seconds
            kind = 'review' if stage == 'review' else 'write'
            for number in pages:
                row = self._page(number)
                row[kind + '_calls'] += 1
                row[kind + '_seconds'] += seconds / len(pages)
        elif name == 'model_call_error':
            self.calls_failed += 1
            if bucket is not None:
                bucket['errors'] += 1
        elif name == 'model_retry_scheduled':
            self.model_retries += 1
        elif name == 'model_response_rejected':
            self.rejected += 1
        elif name == 'stage_started' and bucket is not None:
            bucket['attempts'] = max(bucket['attempts'], int(_num(event.get('attempt'), 1)))
            bucket['started'] = when or 0
            bucket['running'] = 1
        elif name == 'stage_completed' and bucket is not None:
            bucket['completed'] += 1
            bucket['seconds'] += _num(event.get('duration_seconds'))
            bucket['running'] = 0
        elif name == 'stage_failed' and bucket is not None:
            bucket['failed'] += 1
            bucket['running'] = 0
        elif name in ('stage_interrupted', 'stage_cancelled') and bucket is not None:
            bucket['running'] = 0
        elif name == 'page_retry':
            self._page(int(_num(event.get('page')))).update(retries=1)
        elif name == 'qa_rejected':
            self._page(int(_num(event.get('page')))).update(qa_rejected=1)
        elif name == 'review_rejected':
            self._page(int(_num(event.get('page')))).update(review_rejected=1)
        elif name == 'fallback_page_created':
            self._page(int(_num(event.get('page')))).update(fallback=1)
        level = LEVELS.get(name)
        if level:
            self.levels[level] += 1
            self.kinds[name] += 1
            page = int(_num(event.get('page'))) or (pages[0] if pages else 0)
            self.problems.append({
                'time': when, 'time_text': clock_text(when), 'level': level,
                'title': EVENT_LABELS.get(name, '其他事件'),
                'stage': stage, 'stage_name': STAGE_LABELS.get(stage, ''),
                'page': page or None, 'text': describe(event),
            })

    def update(self, path):
        try:
            size = path.stat().st_size
        except OSError:
            self.reset()
            return False
        try:
            with path.open('rb') as stream:
                head = stream.read(128)
                # 檔案被清除或輪替（變小，或開頭改變）時，從頭重算。
                if size < self.offset or (self.head and not head.startswith(self.head[:min(len(self.head), len(head))])):
                    self.reset()
                if not self.head:
                    self.head = head
                stream.seek(self.offset)
                data = stream.read(CHUNK_BYTES)
        except OSError:
            return False
        end = data.rfind(b'\n')
        if end < 0:
            return True  # 尚無完整新行（可能正在寫入）。
        for raw in data[:end].split(b'\n'):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw.decode('utf-8', errors='replace'))
            except ValueError:
                self.bad_lines += 1
                continue
            if isinstance(event, dict):
                self.feed(event)
        self.offset += end + 1
        return True


def _stats_for(path):
    key = str(path)
    with _LOCK:
        stats = _CACHE.get(key)
        if stats is None:
            stats = _CACHE[key] = _Stats()
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)
        found = stats.update(Path(path))
        return stats, found


def log_report(path, now=None):
    """分析一個 run.jsonl；任何錯誤都回傳可顯示的空報告，不會丟例外。"""
    now = time.time() if now is None else now
    try:
        stats, found = _stats_for(path)
        with _LOCK:
            return _build(stats, found, now)
    except Exception:  # 監控不能因分析失敗而讓整頁消失。
        return _build(_Stats(), False, now)


def job_report(folder, now=None):
    return log_report(Path(folder) / 'run.jsonl', now)


def _build(stats, found, now):
    seconds = [value for value in stats.call_seconds if value > 0]
    stages = []
    for name in STAGE_ORDER:
        row = stats.stage[name]
        if not row:
            continue
        stages.append({
            'stage': name, 'name': STAGE_LABELS[name], 'attempts': row['attempts'],
            'completed': row['completed'], 'failed': row['failed'], 'running': bool(row['running']),
            'seconds': row['seconds'], 'calls': row['calls'], 'call_seconds': row['call_seconds'],
            'errors': row['errors'],
        })
    pages = []
    for number in sorted(stats.pages):
        row = stats.pages[number]
        if number <= 0 or not row:
            continue
        pages.append({
            'page': number, 'write_calls': row['write_calls'], 'write_seconds': row['write_seconds'],
            'review_calls': row['review_calls'], 'review_seconds': row['review_seconds'],
            'retries': row['retries'], 'qa_rejected': row['qa_rejected'],
            'review_rejected': row['review_rejected'], 'fallback': row['fallback'],
        })
    problems = []
    seen = {}
    for item in list(stats.problems)[::-1]:  # 最新的在前；相同的提醒合併成一列並累計次數
        key = (item['title'], item['text'], item['stage'], item['page'])
        if key in seen:
            seen[key]['count'] += 1
            continue
        item = dict(item, count=1)
        seen[key] = item
        problems.append(item)
    return {
        'available': found, 'events': stats.events, 'bad_lines': stats.bad_lines,
        'calls': {
            'started': stats.calls_started, 'finished': stats.calls_finished,
            'failed': stats.calls_failed, 'retries': stats.model_retries,
            'rejected': stats.rejected, 'truncated': stats.truncated,
            'gpu_wait_seconds': stats.gpu_wait,
            'avg_seconds': sum(seconds) / len(seconds) if seconds else None,
            'max_seconds': max(seconds) if seconds else None,
            'prompt_tokens': stats.prompt_tokens, 'output_tokens': stats.output_tokens,
        },
        'stages': stages, 'pages': pages, 'problems': problems,
        'problem_counts': {'error': stats.levels['error'], 'warning': stats.levels['warning']},
        'fallback_pages': sorted(number for number, row in stats.pages.items() if row['fallback'] and number > 0),
        'last_event_age': None if stats.last_time is None else max(0.0, now - stats.last_time),
        'last_error': next((item for item in problems if item['level'] == 'error'), None),
    }


def recent_events(path, limit=100):
    """只讀檔尾，最新的在前；大型 log 不會整檔載入。"""
    limit = max(1, min(int(limit), 500))
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - TAIL_BYTES)
            stream.seek(start)
            data = stream.read()
    except OSError:
        return []
    lines = data.split(b'\n')
    if start:
        lines = lines[1:]  # 起點落在行中間，第一行不完整。
    rows = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw.decode('utf-8', errors='replace'))
        except ValueError:
            continue  # 最後一行可能還在寫入。
        if isinstance(event, dict):
            rows.append(event)
    return rows[-limit:][::-1]


def event_rows(events):
    rows = []
    for event in events:
        when = parse_time(event.get('time'))
        stage = str(event.get('stage') or '')
        duration = event.get('duration_seconds')
        rows.append([
            clock_text(when) if when else '—',
            EVENT_LABELS.get(str(event.get('event')), '其他事件'),
            STAGE_LABELS.get(stage, ''),
            event.get('page') or (pages_in(event.get('label')) or [''])[0],
            describe(event),
            f'{_num(duration):.1f}' if duration is not None else '',
        ])
    return rows


_MD_SPECIAL = re.compile(r'([\\`*_\[\]<>|~$#])')


def markdown_table(headers, rows):
    """產生 Markdown 表格，不經過 pandas；內容中的特殊符號一律跳脫。"""
    def cell(value):
        return _MD_SPECIAL.sub(r'\\\1', str(value).replace('\r', ' ').replace('\n', ' ')) if value != '' else ' '
    lines = ['| ' + ' | '.join(cell(h) for h in headers) + ' |',
             '|' + '|'.join(' --- ' for _ in headers) + '|']
    lines += ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]
    return '\n'.join(lines)


def stage_table(report):
    rows = []
    for item in report['stages']:
        state = '進行中' if item['running'] else '失敗' if item['failed'] and not item['completed'] else '已完成' if item['completed'] else '已中斷'
        rows.append([item['name'], state, item['attempts'] or '', seconds_text(item['seconds']) if item['seconds'] else '—',
                     item['calls'], seconds_text(item['call_seconds']) if item['call_seconds'] else '—', item['errors']])
    return markdown_table(['階段', '狀態', '執行次數', '階段耗時', '模型回覆數', '模型耗時合計', '呼叫失敗'], rows)


def page_table(report):
    rows = []
    for item in report['pages']:
        rows.append([item['page'], item['write_calls'], seconds_text(item['write_seconds']) if item['write_seconds'] else '—',
                     item['review_calls'], seconds_text(item['review_seconds']) if item['review_seconds'] else '—',
                     item['retries'], item['qa_rejected'], item['review_rejected'], '是' if item['fallback'] else ''])
    return markdown_table(['頁', '編寫回覆', '編寫耗時', '審核回覆', '審核耗時', '重寫', '品質退回', '審核退回', '改用保底'], rows)


def problem_table(problems, limit=15):
    rows = [[p['time_text'], '錯誤' if p['level'] == 'error' else '提醒',
             p['title'] + (f" ×{p['count']}" if p.get('count', 1) > 1 else ''), p['stage_name'],
             p['page'] or '', p['text']] for p in problems[:limit]]
    return markdown_table(['時間', '等級', '事件', '階段', '頁', '說明'], rows)
