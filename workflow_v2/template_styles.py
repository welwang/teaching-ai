"""依年級和科目產生配色、字級與對比設定。"""
DESIGN_VERSION = 13

# Subject character: (primary, accent, pale tint, warm paper background)
SUBJECTS = {
    '數學': ('0B6B73', 'C25B0A', 'E3F1F1', 'F7F3E9'),
    '國語': ('8A2F3C', '9A6200', 'F6E7E4', 'FBF5EA'),
    '英語': ('34459C', 'B8345A', 'E7EAF8', 'F6F7FC'),
}
NEUTRAL = ('0B6B73', 'C25B0A', 'E3F1F1', 'F7F3E9')

# Age band: type scale, how saturated the colours are, how white the paper is.
BANDS = {
    'low':    {'title_max': 46, 'body_bonus': 2, 'calm': 0.00, 'paper': 0.00},
    'mid':    {'title_max': 44, 'body_bonus': 2, 'calm': 0.00, 'paper': 0.00},
    'high':   {'title_max': 40, 'body_bonus': 0, 'calm': 0.08, 'paper': 0.35},
    'junior': {'title_max': 36, 'body_bonus': 0, 'calm': 0.16, 'paper': 0.65},
}
# 國中（7-9 年級）採用「任務控制」風格：乾淨白底、近黑文字、單一藍色重點色、細分隔線；封面與章節頁用近黑底。
# 國小三個年齡層不使用這組設定。
MISSION = dict(look='mission', rev=2,  # rev: raise when the mission geometry changes so cached masters are rebuilt
               background='FFFFFF', pale='F3F5F7', primary='0F141A', accent='0A5EA8', ink='0B0D10',
               muted='4F5B67', hairline='D9DEE4', dark='0B0D10', dark_ink='FFFFFF', dark_muted='C5CDD6',
               dark_accent='7FB8FF', dark_line='2A323C')
INK = '1A202C'
FONT = 'Microsoft JhengHei'
MIN_TEXT_CONTRAST = 4.5


def _rgb(color):
    return [int(color[i:i + 2], 16) for i in (0, 2, 4)]


def blend(first, second, weight):
    a, b = _rgb(first), _rgb(second)
    return ''.join(f'{round(a[i] * (1 - weight) + b[i] * weight):02X}' for i in range(3))


def luminance(color):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first, second):
    hi, lo = sorted((luminance(first), luminance(second)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(color, against, ratio=MIN_TEXT_CONTRAST):
    """Darken color step by step until it reads on every colour in `against`."""
    against = [against] if isinstance(against, str) else list(against)
    for step in range(41):
        candidate = blend(color, '000000', step * 0.025)
        if all(contrast(candidate, other) >= ratio for other in against):
            return candidate
    return '000000'


def band_name(grade):
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        return 'high'
    return 'low' if grade <= 2 else 'mid' if grade <= 4 else 'high' if grade <= 6 else 'junior'


def style_for(grade=None, subject=None):
    """The complete deck style for a grade and subject (pure function, no I/O)."""
    key = band_name(6 if grade is None else grade)
    band = BANDS[key]
    primary, accent, pale, paper = SUBJECTS.get(subject, NEUTRAL)
    gray = '56606E'
    primary = blend(primary, gray, band['calm'])
    accent = blend(accent, gray, band['calm'])
    background = blend(paper, 'FFFFFF', band['paper'])
    pale = blend(pale, 'FFFFFF', band['paper'] * 0.5)
    # Every colour that carries text must be readable on paper, on white cards and under white chip labels.
    primary = ensure_contrast(primary, [background, 'FFFFFF', pale])
    accent = ensure_contrast(accent, [background, 'FFFFFF', pale])
    names = {'數學': 'math', '國語': 'chinese', '英語': 'english'}
    default = grade is None and subject is None
    result = {'id': 'default' if default else f"{names.get(subject, 'general')}-{key}",
              'grade': 6 if grade is None else int(grade), 'subject': subject or '數學', 'band': key,
              'style': 'story', 'primary': primary, 'background': background, 'pale': pale,
              'accent': accent, 'ink': INK, 'font': FONT,
              'title_max': band['title_max'], 'body_bonus': band['body_bonus']}
    if key == 'junior':
        result.update(MISSION, style='diagram', title_max=40)
    return result


DEFAULT_THEME = style_for()


def theme(template=None, grade=None, subject=None):
    """Style for a deck. Legacy template ids are ignored; grade/subject choose the palette."""
    return style_for(grade, subject)