"""年級對應的文字密度、互動與教學規則。"""

BANDS = {
    'low': {
        'label': '國小低年級', 'grades': (1, 2),
        'tone': '像說故事與遊戲指令：句子很短，用「我們一起」「看看」「說說看」，一句只做一件事。',
        'body_target': (20, 40), 'body_max': 70, 'heading_max': 14, 'bullets_max': 3,
        'interaction': '每頁一個動作：指一指、數一數、跟我說、選一選；先示範再模仿，全班齊聲回答。',
        'notes': '備註寫逐句口白、肢體動作與鼓勵語；每頁停頓 10 至 20 秒。',
        'think_seconds': (10, 20),
    },
    'mid': {
        'label': '國小中年級', 'grades': (3, 4),
        'tone': '親切的課堂口吻：短句、實物與圖示，新詞先用白話解釋再命名。',
        'body_target': (40, 60), 'body_max': 90, 'heading_max': 18, 'bullets_max': 3,
        'interaction': '先觀察再口述：看圖說發現、配對、二選一並說理由；示範後立刻模仿一題。',
        'notes': '備註寫口白重點、預期學生答案與追問；每頁停頓 15 至 30 秒。',
        'think_seconds': (15, 30),
    },
    'high': {
        'label': '國小高年級', 'grades': (5, 6),
        'tone': '清楚穩定、不幼稚：先給例子再給規則，要求說出為什麼與如何檢查。',
        'body_target': (50, 90), 'body_max': 120, 'heading_max': 22, 'bullets_max': 4,
        'interaction': '比較方法、補完關鍵步驟、說明依據；練習含一次自我檢查。',
        'notes': '備註寫講解秒數、提問與追問、常見錯誤及處理；每頁停頓 20 至 40 秒。',
        'think_seconds': (20, 40),
    },
    'junior': {
        'label': '國中', 'grades': (7, 8, 9),
        'tone': '自然、尊重、不說教；由例子導向規則，新術語連結熟悉經驗再操作。',
        'body_target': (70, 120), 'body_max': 160, 'heading_max': 26, 'bullets_max': 5,
        'interaction': '讓學生解釋推理、比較策略、判斷與反例；小組討論後再全班回報。',
        'notes': '備註寫講解秒數、探究問題、預期迷思與評量標準；每頁停頓 30 至 60 秒。',
        'think_seconds': (30, 60),
    },
}


def band_key(grade):
    """Grades 1-2 low, 3-4 mid, 5-6 high, 7-9 junior high; anything else is rejected."""
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        raise ValueError('年級必須是整數')
    for key, band in BANDS.items():
        if min(band['grades']) <= grade <= max(band['grades']):
            return key
    raise ValueError('年級必須介於 1 到 9')


def band_for(grade):
    return BANDS[band_key(grade)]


def band_label(grade):
    return band_for(grade)['label']


def length_rule(grade):
    """Short prompt sentence replacing the old fixed 80/110-character target."""
    band = band_for(grade)
    low, high = band['body_target']
    return (f"{band['label']}：每頁投影正文以 {low} 至 {high} 字為目標、最多 {band['body_max']} 字，"
            f"列點不超過 {band['bullets_max']} 項，標題不超過 {band['heading_max']} 字；"
            '作答必要的題幹、文本線索與完整算式不計入刪減，長篇解析放備註。')


def tone_rule(grade):
    band = band_for(grade)
    return f"語氣（{band['label']}）：{band['tone']}"


def interaction_rule(grade):
    band = band_for(grade)
    return f"互動（{band['label']}）：{band['interaction']}教師備註：{band['notes']}"


def projected_text(slide):
    """All student-visible text of a slide except heading/subheading/notes."""
    body = slide.get('body') or {}
    parts = list(body.get('bullets') or [])
    for column in body.get('columns') or []:
        parts.append(column.get('header') or '')
        parts.extend(column.get('points') or [])
    parts.extend([body.get('question') or '', body.get('answer') or ''])
    for module in slide.get('modules') or []:
        parts.extend([module.get('keyword') or '', module.get('description') or ''])
    parts.extend([slide.get('key_sentence') or '', slide.get('reading_context') or ''])
    return ''.join(''.join(str(p).split()) for p in parts)


def density_findings(slide, grade):
    """Return (code, message) tuples; never raises on malformed slides."""
    band = band_for(grade)
    found = []
    try:
        text = projected_text(slide)
        heading = ''.join(str(slide.get('heading') or '').split())
        layout = slide.get('layout_id')
    except (AttributeError, TypeError):
        return [('malformed', '投影片資料格式異常')]
    # Practice pages must carry the whole question; only count them against the hard cap.
    limit = band['body_max'] * (2 if layout in ('Question', 'quiz_qa', 'Steps') else 1)
    if len(text) > limit:
        found.append(('too_long', f"{band['label']}建議正文不超過 {band['body_max']} 字，這頁有 {len(text)} 字"))
    if len(heading) > band['heading_max'] + 12:
        found.append(('heading_long', f'標題 {len(heading)} 字，過長'))
    return found