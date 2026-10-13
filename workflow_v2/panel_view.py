"""控制台 HTML 元件；動態文字在輸出前跳脫。"""
import time
from html import escape

from .console_state import (TRACK_NAMES, current_page, gpu_numbers, hms, overall_eta, overall_percent, speed_per_second,
                            stage_track, status_text)

GRADE_NAMES = {4: '國小四年級', 5: '國小五年級', 6: '國小六年級', 7: '國中一年級', 8: '國中二年級', 9: '國中三年級'}
LEVELS = ('ok', 'info', 'warn', 'error')
LEVEL_WORD = {'ok': '待命', 'info': '排隊中', 'warn': '注意', 'error': '需要處理'}
SERVICE_STATE = {'ok': '正常', 'warn': '注意', 'error': '異常', 'off': '未使用'}
SERVICE_KEYS = ('worker', 'model', 'image', 'disk')
WAITING = ('pending', 'repairing', 'staging', 'awaiting_outline', 'paused')
BUSY = ('pending', 'repairing', 'running', 'rendering', 'reviewing', 'staging')
# manifest buckets: what the teacher filters by
BUCKET_OF = {'done': 'done', 'failed': 'attention', 'paused': 'attention', 'pausing': 'attention', 'awaiting_outline': 'attention'}
BUCKETS = {'all': '全部', 'live': '進行中', 'done': '已完成', 'attention': '需處理'}
NAME = '教材簡報工作室'
GAUGE_R = 52
GAUGE_ARC = 0.75 * 2 * 3.141592653589793 * GAUGE_R   # 270 degrees
TICK_GAP = 0.75 * 2 * 3.141592653589793 * (GAUGE_R + 7) / 10 - 0.8   # eleven ticks: 0 %, 10 % … 100 %


def e(value):
    # "$" would start a math span inside st.markdown, so it is written as an entity.
    return escape(str(value if value is not None else ''), quote=True).replace('$', '&#36;')


def gauge_html(label, value, unit, percent=None):
    """A thin 270-degree dial: ticks every 10 %, the arc and a tip dot sweep to `percent`, the number counts to `value`.

    The arc length, the tip angle and the number are CSS custom properties, so a new value glides from the old one
    (the page updates the same nodes in place every second)."""
    known = value is not None
    fill = 0.0 if percent is None else max(0.0, min(100.0, float(percent)))
    angle = 270 * fill / 100
    if known and isinstance(value, (int, float)):
        reading = f'<span class="lx-num" style="--n:{int(round(value))}"></span><small>{e(unit)}</small>'
    else:
        reading = e(value) + (f'<small>{e(unit)}</small>' if known and unit else '') if known else '—'
    tip = '' if not known else (f'<g class="lx-tip" style="transform:rotate({angle:.1f}deg)"><circle cx="{64 + GAUGE_R}" cy="64" r="3.2"/></g>')
    return (f'<figure class="lx-gauge{" lx-off" if not known else ""}" role="img" aria-label="{e(label)} {e(value) + e(unit) if known else "無資料"}">'
            '<svg viewBox="0 0 128 128" aria-hidden="true"><g transform="rotate(135 64 64)">'
            f'<circle class="lx-ticks" cx="64" cy="64" r="{GAUGE_R + 7}" stroke-dasharray="0.8 {TICK_GAP:.2f}"/>'
            f'<circle class="lx-track" cx="64" cy="64" r="{GAUGE_R}" stroke-dasharray="{GAUGE_ARC:.1f} 999"/>'
            f'<circle class="lx-fill" cx="64" cy="64" r="{GAUGE_R}" style="stroke-dasharray:{GAUGE_ARC * fill / 100:.1f} 999"/>'
            f'{tip}</g></svg><b class="lx-read">{reading}</b><figcaption>{e(label)}</figcaption></figure>')


def timeline_html(job):
    """Seven stages on one line: finished ones solid, the current one carries the marker."""
    track = stage_track(job)
    items = ''.join(f'<li class="{item["state"]}"' + (' aria-current="step"' if item['state'] == 'active' else '')
                    + f'><i></i><span>{e(item["name"])}</span></li>' for item in track)
    label = f'製作流程：第 {job["stage_number"]}／{job["stage_count"]} 步' if job and job.get('stage_number') else '製作流程'
    return f'<div class="lx-line"><ol aria-label="{e(label)}">{items}</ol></div>'


def mission_name(job):
    if not job:
        return '目前沒有進行中的任務'
    grade = GRADE_NAMES.get(job.get('grade'), '')
    return '　'.join(part for part in (f'{grade}{job.get("subject") or ""}', job.get('unit') or '') if part)


def band_html(head, state, clock='', queue=(), latest=None, notes=()):
    """Status line, two dials around the T+ clock, the stage timeline and one line of news."""
    level = head.get('level') if head.get('level') in LEVELS else 'info'
    job = state.get('job')
    live = bool(job) and level == 'ok'
    gpu = gpu_numbers(state)
    waiting = sum(row.get('status') in WAITING for row in queue or ())
    title, hint = head.get('title') or '', head.get('hint') or ''
    if not job and title == '一切正常，目前沒有進行中的工作':
        title, hint = '待命中', '按右上角「新任務」選好單元，就會開始製作。'
    if job:
        percent = overall_percent(job)
        if level == 'ok':
            page = current_page(job)
            total = job.get('stage_total') if job.get('stage_unit') == '頁' else None
            stage = TRACK_NAMES.get(job.get('stage')) or job.get('stage_name') or '製作'
            title = f'{stage}　第 {page}／{total} 頁' if page and total else f'{stage}中'
            eta = overall_eta(job, percent)
            hint = f'預計還要 {hms(eta)}' if eta is not None else '正在估算剩餘時間'
        mark, reading = 'T+', hms(job.get('elapsed_seconds'))
        dial = gauge_html('完成度', percent, '%', percent)
    else:
        mark, reading = 'T−', '00:00:00'
        dial = gauge_html('完成度', None, '%')
    load = gauge_html('顯卡負載', gpu['util'] if gpu else None, '%', gpu['util'] if gpu else None)
    word = '製作中' if live else LEVEL_WORD[level]
    side = f'另有 {waiting} 份排隊' if waiting and job else ''
    classes = ' '.join(filter(None, ('lx', 'lx-' + level, 'lx-live' if live else '', '' if job else 'lx-idle')))
    out = [f'<section class="{classes}" role="status" aria-live="polite">',
           f'<header class="lx-top"><span class="lx-state"><i class="dot{" live" if live else ""}"></i>{e(word)}</span>'
           f'<span class="lx-mission">{e(mission_name(job))}</span>'
           + (f'<span class="lx-side">{e(side)}</span>' if side else '')
           + (f'<time class="lx-time" aria-label="現在時間 {e(clock)}">{e(clock)}</time>' if clock else '') + '</header>',
           '<div class="lx-deck">', dial,
           f'<div class="lx-center"><p class="lx-clock"><span>{mark}</span>{e(reading)}</p><p class="lx-head">{e(title)}</p>'
           + (f'<p class="lx-sub">{e(hint)}</p>' if hint else '') + '</div>', load, '</div>', timeline_html(job)]
    foot = []
    if notes:
        more = f'（另有 {len(notes) - 1} 項，見「遙測詳情」）' if len(notes) > 1 else ''
        foot.append(f'<p class="lx-note"><i class="dot"></i><span>{e(notes[0])}{e(more)}</span></p>')
    if latest:
        event = '：'.join(str(value) for value in (latest.get('label'), latest.get('text')) if value)
        foot.append(f'<p class="lx-event"><time>{e(latest.get("time"))}</time><span>{e(event)}</span></p>')
    if foot:
        out.append('<footer class="lx-foot">' + ''.join(foot) + '</footer>')
    out.append('</section>')
    return ''.join(out)


def unavailable_html(seconds, clock=''):
    return ('<section class="lx lx-warn lx-idle" role="status"><header class="lx-top"><span class="lx-state"><i class="dot"></i>注意</span>'
            f'<span class="lx-mission"></span><time class="lx-time">{e(clock)}</time></header><div class="lx-deck lx-solo"><div class="lx-center">'
            f'<p class="lx-head">暫時讀不到進度</p><p class="lx-sub">可能正在寫入資料，{int(seconds)} 秒後會自動再試，不用做任何事。</p></div></div></section>')


def facts_html(job, state):
    """Numbers the band above does not already show (it shows completion, page, elapsed, remaining, graphics load)."""
    rows = []
    if job:
        rate = speed_per_second(job)
        rows.append(('生成速度', f'{round(rate)} 詞元／秒' if rate else '—'))
        tokens = (job.get('tokens') or {}).get('total_tokens')
        rows.append(('已用詞元', f'{int(tokens):,}' if tokens else '—'))
        rows.append(('目前模型', job.get('model') or '—'))
    gpu = gpu_numbers(state)
    rows.append(('顯存使用', f'{gpu["used_gb"]:.1f}／{gpu["total_gb"]:.0f} 吉位元組' if gpu else '無法讀取'))
    return '<dl class="pn-facts">' + ''.join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in rows) + '</dl>'


def feed_html(feed, limit=8):
    if not feed:
        return '<p class="pn-quiet">還沒有事件；開始製作後會即時出現在這裡。</p>'
    items = []
    for item in feed[:limit]:
        tag = item['level'] if item['level'] in ('warning', 'error') else ''
        page = f"第 {item['page']} 頁　" if item.get('page') else ''
        label = f'<em class="{tag}">{e(item["label"])}</em>' if tag else ''
        items.append(f'<li><time>{e(item["time"])}</time>{label}<span>{e(page + item["text"])}</span></li>')
    return '<ul class="pn-log">' + ''.join(items) + '</ul>'


def services_html(health):
    rows = {row['key']: row for row in (health or [])}
    cells = []
    for key in SERVICE_KEYS:
        row = rows.get(key)
        if row:
            state = row['state'] if row['state'] in SERVICE_STATE else 'off'
            cells.append(f'<li class="{state}"><i class="dot"></i><b>{e(row["name"])}</b><span>{e(SERVICE_STATE[state])}</span>'
                         f'<small>{e(row["detail"])}</small></li>')
    return '<ul class="pn-svc">' + ''.join(cells) + '</ul>' if cells else '<p class="pn-quiet">暫時讀不到服務狀態。</p>'


def health_html(rows):
    """Full service check (系統 dialog)."""
    cells = []
    for row in rows:
        state = row['state'] if row['state'] in SERVICE_STATE else 'off'
        cells.append(f'<li class="{state}"><i class="dot"></i><b>{e(row["name"])}</b><span>{e(SERVICE_STATE[state])}</span>'
                     f'<small>{e(row["detail"])}</small></li>')
    return '<ul class="pn-svc">' + ''.join(cells) + '</ul>'


def details_html(state, feed, health, notes=()):
    """Everything the band leaves out: more numbers, all notes, services, earlier events (the newest is in the band)."""
    job = state.get('job')
    left = ['<section><h4>數據</h4>' + facts_html(job, state) + '</section>']
    if len(notes) > 1:
        left.append('<section><h4>需要留意</h4><ul class="pn-log">' + ''.join(f'<li><span>{e(n)}</span></li>' for n in notes) + '</ul></section>')
    left.append('<section><h4>更早的事件</h4>' + (feed_html(feed[1:]) if len(feed) > 1 else '<p class="pn-quiet">沒有更早的事件。</p>') + '</section>')
    right = ['<section><h4>電腦與服務</h4>' + services_html(health) + '</section>']
    return '<div class="pn-details"><div>' + ''.join(left) + '</div><div>' + ''.join(right) + '</div></div>'


def grade_name(grade):
    return GRADE_NAMES.get(grade, '')


def job_title(request):
    return request.get('unit') or '未命名教材'


def job_meta(request):
    return '　'.join(x for x in (grade_name(request.get('grade')) + (request.get('subject') or ''), request.get('semester') or '',
                                 f'{int(request["slide_count"])} 頁' if request.get('slide_count') else '') if x)


def bucket(status):
    return BUCKET_OF.get(status, 'live')


def counts(rows):
    found = {key: 0 for key in BUCKETS}
    found['all'] = len(rows)
    for row in rows:
        found[bucket(row['status'])] += 1
    return found


def matches(row, request, query='', which='all'):
    if which not in (None, 'all') and bucket(row['status']) != which:
        return False
    haystack = ' '.join((job_title(request), job_meta(request), status_text(row['status']))).lower()
    return all(word.lower() in haystack for word in (query or '').split())


def when(ts, now=None):
    """今天 14:30 / 昨天 09:05 / 10月2日."""
    if not ts:
        return ''
    now = now or time.time()
    then, today, yesterday = time.localtime(ts), time.localtime(now), time.localtime(now - 86400)
    clock = time.strftime('%H:%M', then)
    if (then.tm_year, then.tm_yday) == (today.tm_year, today.tm_yday):
        return f'今天 {clock}'
    if (then.tm_year, then.tm_yday) == (yesterday.tm_year, yesterday.tm_yday):
        return f'昨天 {clock}'
    return f'{then.tm_mon}月{then.tm_mday}日'


def card_html(row, request, stage_name, saved, cover=None, now=None, elapsed_seconds=None):
    """One deck as a card: cover (first page, or the subject's first character), name, class, state, date or progress."""
    mark = bucket(row['status'])
    total = int(request.get('slide_count') or 0)
    art = (f'<img src="{cover}" alt="" loading="lazy">' if cover
           else f'<b aria-hidden="true">{e((request.get("subject") or "教")[:1])}</b>')
    if row['status'] == 'done':
        foot = f'<time>{e(when(row.get("updated") or row.get("created"), now))}</time>'
        meter = ''
    else:
        percent = min(100, saved * 100 // total) if total else 0
        foot = f'<span>{e(stage_name)}　{saved}／{total} 頁</span>'
        meter = (f'<i class="pn-meter{" live" if row["status"] in ("running", "rendering", "reviewing", "repairing") else ""}" '
                 f'role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent}" aria-label="已寫好 {percent}%">'
                 f'<b style="width:{percent}%"></b></i>') if row['status'] in BUSY else ''
    timing_label = '製作總時長' if row['status'] == 'done' else '製作已累計'
    timing_value = hms(elapsed_seconds) if elapsed_seconds is not None else '—'
    timing_note = '累計各階段執行時間，不含排隊及大綱確認等待' if elapsed_seconds is not None else '沒有製作時間紀錄'
    timing = (f'<p class="pn-ctime" title="{e(timing_note)}"><span>{timing_label}</span>'
              f'<b>{e(timing_value)}</b></p>')
    return (f'<article class="pn-card {mark}"><div class="pn-cover">{art}</div><div class="pn-cbody">'
            f'<b class="pn-cname" title="{e(job_title(request))}">{e(job_title(request))}</b><small>{e(job_meta(request))}</small>'
            f'<p class="pn-cfoot"><span class="pn-mark"><i class="dot"></i>{e(status_text(row["status"]))}</span>{foot}</p>{timing}{meter}</div></article>')


def thumbs_html(items, total):
    cells = ''.join(f'<figure><img src="{uri}" alt="第 {n} 頁" loading="lazy"><figcaption>{n}</figcaption></figure>' for n, uri in items)
    more = f'<p class="pn-quiet">顯示前 {len(items)} 頁，共 {total} 頁。</p>' if total > len(items) else ''
    return f'<div class="pn-thumbs">{cells}</div>{more}'
