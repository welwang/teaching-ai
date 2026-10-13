"""控制台配色、字級與動畫設定。"""
import json
from pathlib import Path

from .store import DATA, atomic

THEME_ORDER = ('白色', '任務控制（深色）', '米色', '淡綠', '暮紫灰')
THEME_NOTES = {'白色': '航太白', '任務控制（深色）': '軌道黑', '米色': '暖紙米', '淡綠': '霧森綠', '暮紫灰': '暮紫灰'}
THEMES = {'白色': {'mode': 'light',
        'bg': '#ffffff',
        'raise_': '#f7f8fa',
        'line': '#dce1e7',
        'strong': '#535d69',
        'fg': '#101318',
        'muted': '#282b2f',
        'accent': '#101318',
        'ink': '#ffffff',
        'ok': '#17734f',
        'warn': '#835500',
        'err': '#b42318'},
 '任務控制（深色）': {'mode': 'dark',
              'bg': '#080a0d',
              'raise_': '#11151b',
              'line': '#303844',
              'strong': '#a0aab8',
              'fg': '#f1f3f6',
              'muted': '#dadcdf',
              'accent': '#f1f3f6',
              'ink': '#080a0d',
              'ok': '#75d6ab',
              'warn': '#edc078',
              'err': '#ff9c93'},
 '米色': {'mode': 'light',
        'bg': '#f1e3c9',
        'raise_': '#faf2e4',
        'line': '#d3bea1',
        'strong': '#62594d',
        'fg': '#342d25',
        'muted': '#473f35',
        'accent': '#4c4033',
        'ink': '#fffaf3',
        'ok': '#2b694c',
        'warn': '#805614',
        'err': '#a82a1f'},
 '淡綠': {'mode': 'light',
        'bg': '#d6e5db',
        'raise_': '#edf4ed',
        'line': '#b2cab9',
        'strong': '#526051',
        'fg': '#243429',
        'muted': '#36463b',
        'accent': '#374d3d',
        'ink': '#ffffff',
        'ok': '#256746',
        'warn': '#805614',
        'err': '#ad2a1f'},
 '暮紫灰': {'mode': 'light',
         'bg': '#e5dbef',
         'raise_': '#f4eef9',
         'line': '#c9b7da',
         'strong': '#61556e',
         'fg': '#352d3e',
         'muted': '#473e50',
         'accent': '#534460',
         'ink': '#ffffff',
         'ok': '#28664a',
         'warn': '#805614',
         'err': '#a52b24'}}
LEGACY_THEMES = {
    '夜間': '任務控制（深色）', '黑夜': '任務控制（深色）', '深空藍': '任務控制（深色）',
    '石墨': '任務控制（深色）', '白天': '白色', '紙張': '米色', '月岩灰': '白色',
    '燕麥米': '米色', '霧玫瑰': '暮紫灰', '海鹽藍': '淡綠', '柔霧灰': '白色',
    '淡藍': '白色', '午夜藍': '任務控制（深色）', '石墨黑': '任務控制（深色）',
    '酒紅黑': '任務控制（深色）', '森林墨': '任務控制（深色）', '香檳白': '米色',
    '極光': '任務控制（深色）', '高對比': '任務控制（深色）',
}
DEFAULT_THEME = '白色'
TEXT_SIZES = {'小': 100, '中': 112.5, '大': 125, '特大': 150}   # percent of the 16 px browser default
DEFAULT_SIZE = '中'
PREFS = 'ui-prefs.json'
FONT = '"Bahnschrift","DIN Alternate","D-DIN","Segoe UI","Microsoft JhengHei UI","Noto Sans TC","PingFang TC",system-ui,sans-serif'


def normalize_theme(name):
    name = LEGACY_THEMES.get(name, name)
    return name if name in THEMES else DEFAULT_THEME


def _path(path=None):
    return Path(path or DATA / PREFS)


def load_prefs(path=None):
    """{'theme','size','calm'}; anything unknown (including names from the old console) falls back to the default."""
    try:
        raw = json.loads(_path(path).read_text(encoding='utf-8'))
        raw = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        raw = {}
    return {'theme': normalize_theme(raw.get('theme')),
            'size': raw.get('font') if raw.get('font') in TEXT_SIZES else DEFAULT_SIZE,
            'calm': bool(raw.get('calm'))}


def save_prefs(theme, size, calm, path=None):
    if theme not in THEMES or size not in TEXT_SIZES:
        raise ValueError('沒有這個顯示設定')
    target = _path(path)
    try:
        current = json.loads(target.read_text(encoding='utf-8'))
        current = current if isinstance(current, dict) else {}
    except (OSError, ValueError):
        current = {}
    current.update(theme=theme, font=size, calm=bool(calm))
    atomic(target, current)


def css(theme=DEFAULT_THEME, size=DEFAULT_SIZE, calm=False):
    t = THEMES[normalize_theme(theme)]
    tokens = ';'.join(f'--{k.rstrip("_")}:{v}' for k, v in t.items() if k != 'mode')
    root = (f'html{{font-size:{TEXT_SIZES.get(size, TEXT_SIZES[DEFAULT_SIZE]):g}%!important}}'
            f':root,.stApp{{{tokens};--font:{FONT};color-scheme:{t["mode"]}}}')
    still = '*,*::before,*::after{animation:none!important;transition:none!important}' if calm else ''
    return '<style id="pn-style">' + root + SHEET + still + '</style>'


SHEET = r'''
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--bg)!important;color:var(--fg)}
.stApp{font-family:var(--font);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.stApp :is(p,div,label,li,dt,dd,b,small,time,figcaption,h1,h2,h3,h4,input,textarea,button,table,th,td,summary):not([data-testid="stIconMaterial"]){font-family:var(--font)!important}
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],[data-testid="stAppDeployButton"],[data-testid="stMainMenu"]{display:none!important}
[data-testid="stMainBlockContainer"]{max-width:1240px!important;width:100%;box-sizing:border-box;margin:0 auto;padding:0 var(--edge) 4rem!important}
:root,.stApp{--edge:clamp(1rem,3vw,2rem);--glide:.6s cubic-bezier(.4,0,.2,1);--settle:.24s ease-out}
[data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"]{gap:0}
.stApp p,.stApp li,.stApp label,.stApp span,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp [data-testid="stMarkdownContainer"]{color:var(--fg)}
.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stCaptionContainer"] *,.stApp [data-testid="stWidgetLabel"] p{color:var(--muted)!important}
.stApp a{color:var(--fg)}
.stApp .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--strong);flex:none}
.stApp button{font-family:var(--font)!important}
.stApp .stButton>button,.stApp .stDownloadButton>button,.stApp [data-testid="stFormSubmitButton"]>button,.stApp [data-testid="stPopover"]>div>button{
  border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--fg);min-height:2.5rem;padding:0 1.2rem;letter-spacing:.08em;box-shadow:none;transition:border-color .15s,background .15s,color .15s}
.stApp button [data-testid="stMarkdownContainer"],.stApp button p,.stApp button span{color:inherit!important}
.stApp button p{font-size:1rem!important;margin:0!important}
.stApp .stButton>button:hover,.stApp .stDownloadButton>button:hover,.stApp [data-testid="stPopover"]>div>button:hover{border-color:var(--fg);color:var(--fg);background:transparent}
.stApp button[kind="primary"],.stApp button[data-testid="stBaseButton-primary"],.stApp [data-testid="stFormSubmitButton"]>button[kind="primary"]{background:var(--accent)!important;color:var(--ink)!important;border-color:var(--accent)!important}
.stApp button[kind="primary"]:hover,.stApp button[data-testid="stBaseButton-primary"]:hover{filter:brightness(1.12)}
.stApp button:disabled{opacity:.35}
.stApp button:focus-visible,.stApp input:focus-visible,.stApp textarea:focus-visible,.stApp summary:focus-visible,.stApp [role="radio"]:focus-visible{outline:2px solid var(--accent)!important;outline-offset:3px}
.stApp [data-testid="stTextInputRootElement"],.stApp [data-testid="stNumberInputContainer"],.stApp [data-testid="stTextAreaRootElement"],.stApp [data-baseweb="input"],.stApp [data-baseweb="select"]>div,.stApp [data-baseweb="textarea"]{background:var(--raise)!important;border:1px solid var(--line)!important;border-radius:12px!important;min-height:44px}
.stApp [data-baseweb="base-input"]{background:transparent!important;border:0!important;border-radius:12px!important}
.stApp [data-baseweb="select"]>div:hover,.stApp [data-testid="stTextInputRootElement"]:focus-within,.stApp [data-baseweb="input"]:focus-within{border-bottom-color:var(--fg)!important}
.stApp input,.stApp textarea{color:var(--fg)!important;-webkit-text-fill-color:var(--fg);background:transparent!important}
.stApp [data-baseweb="select"] *{color:var(--fg)}
.stApp [data-testid="stSelectbox"] .react-aria-ComboBox [role="group"]{background:var(--raise)!important;border:1px solid var(--line)!important;border-radius:12px!important;min-height:44px}
.stApp [data-testid="stSelectbox"] .react-aria-ComboBox button{color:var(--fg)!important;background:transparent!important}
.stApp [data-testid="stSelectbox"] .react-aria-ComboBox [role="group"]:focus-within{border-color:var(--accent)!important}
.react-aria-Popover,.react-aria-ListBox{background:var(--raise)!important;color:var(--fg)!important;border-color:var(--line)!important}
[role="listbox"] [role="option"]{background:var(--raise)!important;color:var(--fg)!important}
[role="listbox"] [role="option"][data-focused],[role="listbox"] [role="option"][aria-selected="true"]{background:var(--line)!important;color:var(--fg)!important}
div[data-baseweb="popover"] ul,div[data-baseweb="popover"] [role="listbox"],div[data-baseweb="menu"]{background:var(--raise)!important;border:1px solid var(--line);border-radius:8px!important}
div[data-baseweb="popover"] li,div[data-baseweb="popover"] li *{color:var(--fg)!important}
div[data-baseweb="popover"] li:hover,div[data-baseweb="popover"] li[aria-selected="true"]{background:var(--line)!important}
[data-testid="stPopoverBody"]{background:var(--raise)!important;border:1px solid var(--line)!important;border-radius:12px!important}
[data-testid="stFileUploaderDropzone"]{background:transparent;border:1px dashed var(--strong);border-radius:8px}
[data-testid="stFileUploaderDropzone"] *{color:var(--muted)}
[data-testid="stFileUploaderDropzoneInstructions"] span,[data-testid="stFileUploaderDropzoneInstructions"] small{display:none}
[data-testid="stFileUploaderDropzoneInstructions"]::before{content:"把檔案拖到這裡（PDF、Word、Markdown、文字檔）";font-size:1rem}
[data-testid="stFileUploaderDropzone"] button{font-size:0!important}
[data-testid="stFileUploaderDropzone"] button::after{content:"選擇檔案";font-size:1rem}
.stApp [data-testid="stButtonGroup"] [role="radiogroup"]{gap:.4rem;flex-wrap:wrap}
.stApp [data-testid="stButtonGroup"] button{border-radius:999px!important;border:1px solid var(--line)!important;background:transparent!important;color:var(--muted)!important;min-height:2.25rem;padding:0 1rem!important}
.stApp [data-testid="stButtonGroup"] button:hover{color:var(--fg)!important;border-color:var(--strong)!important}
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"]{background:var(--accent)!important;color:var(--ink)!important;border-color:var(--accent)!important}
.stApp [data-testid="stButtonGroup"] button *{color:inherit!important}
.stApp [data-testid="stExpander"]{border:0;border-top:1px solid var(--line);border-radius:0;background:transparent}
.stApp [data-testid="stExpander"] summary{padding:.9rem 0;min-height:3rem}
.stApp [data-testid="stExpander"] summary:hover{background:transparent}
.stApp [data-testid="stExpander"] summary p{letter-spacing:.12em;color:var(--muted)}
.stApp [data-testid="stExpander"] summary:hover p{color:var(--fg)}
.stApp [data-testid="stAlert"]{background:transparent;border:0;border-left:2px solid var(--strong);border-radius:0;padding:.25rem 0 .25rem 1rem}
.stApp [data-testid="stAlert"] *{color:var(--fg)}
.stApp [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){border-left-color:var(--warn)}
.stApp [data-testid="stAlert"]:has([data-testid="stAlertContentError"]){border-left-color:var(--err)}
.stApp [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){border-left-color:var(--ok)}
.stApp [data-testid="stProgress"]>div>div{height:6px!important;border-radius:999px;background:var(--line);overflow:hidden}
.stApp [data-testid="stProgress"]>div>div>div{border-radius:999px;background:var(--accent);transition:width var(--glide)}
.stApp [data-testid="stCode"],.stApp pre{background:var(--raise)!important;border:1px solid var(--line);border-radius:8px}
.stApp pre *,.stApp code{color:var(--fg)}
.stApp table{border-collapse:collapse;font-size:1rem}.stApp th,.stApp td{border:0!important;border-top:1px solid var(--line)!important;padding:.4rem .6rem!important}
.stApp th{color:var(--muted)!important;font-weight:400}
.stApp [data-testid="stImage"] img{border:1px solid var(--line)}
.stApp [data-testid="stForm"]{border:0;padding:0}
div[role="dialog"]{width:min(1500px,96vw)!important;max-width:96vw!important;background:var(--bg)!important;border:1px solid var(--line)!important;border-radius:16px!important;color:var(--fg)}
div[role="dialog"] h2{font-weight:400!important;letter-spacing:.12em!important}
div[role="dialog"] button[aria-label="Close"] svg{color:var(--fg)!important;fill:var(--fg)}
.stApp [data-testid="stTabs"] [role="tablist"]{gap:1.5rem;border-bottom:1px solid var(--line)}
.stApp [data-testid="stTabs"] [data-baseweb="tab-highlight"]{background:var(--accent);height:2px}
.stApp [data-testid="stTabs"] [data-baseweb="tab-border"]{display:none}
.stApp [data-testid="stTabs"] button[role="tab"]{padding:.6rem 0;letter-spacing:.12em}
.stApp [data-testid="stTabs"] button[role="tab"] p{color:var(--muted)}
.stApp [data-testid="stTabs"] button[role="tab"][aria-selected="true"] p{color:var(--fg)}
.st-key-pn-head{flex-direction:row!important;align-items:center;gap:.75rem;padding:1rem var(--edge);margin:0 calc(var(--edge)*-1);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;background:var(--bg)}
.st-key-pn-head>div:first-child{flex:1 1 auto;min-width:0}
.st-key-pn-head>div:not(:first-child){flex:0 0 auto;width:auto!important}
.stApp .pn-brand{display:flex;align-items:center;gap:.75rem;margin:0;font-size:1rem;font-weight:400;letter-spacing:.12em;white-space:nowrap}
.stApp .pn-brand img{width:22px;height:22px;border-radius:6px;filter:grayscale(1)}
.stApp .lx{font-variant-numeric:tabular-nums}
.stApp .lx-top{display:flex;align-items:center;gap:1.5rem;padding:1rem 0 0;font-size:1rem;letter-spacing:.08em;color:var(--muted);white-space:nowrap}
.stApp .lx-state{display:inline-flex;align-items:center;gap:.6rem;color:var(--fg)}
.stApp .lx .dot.live{background:var(--ok)}
.stApp .lx-warn .lx-state{color:var(--warn)}.stApp .lx-warn .lx-state .dot{background:var(--warn)}
.stApp .lx-error .lx-state{color:var(--err)}.stApp .lx-error .lx-state .dot{background:var(--err)}
.stApp .lx-mission{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;letter-spacing:.08em}
.stApp .lx-time{color:var(--fg);letter-spacing:.12em}
.stApp .lx{display:flex;flex-direction:column;min-height:min(40vh,28rem)}
.stApp .lx-idle{min-height:0}
.stApp .lx-deck{flex:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2.4fr) minmax(0,1fr);align-items:center;gap:2rem;padding:2rem 0 1.5rem}
.stApp .lx-gauge{position:relative;margin:0 auto;width:clamp(8rem,12vw,10rem);display:grid;justify-items:center}
.stApp .lx-gauge svg{display:block;width:100%;height:auto}
.stApp .lx-gauge circle{fill:none;stroke-width:2.5}
.stApp .lx-ticks{stroke:var(--strong);stroke-width:4!important;opacity:.55}
.stApp .lx-track{stroke:var(--line)}
.stApp .lx-fill{stroke:var(--accent);stroke-linecap:round;transition:stroke-dasharray var(--glide)}
.stApp .lx-tip{transform-box:view-box;transform-origin:64px 64px;transition:transform var(--glide)}
.stApp .lx-tip circle{fill:var(--accent)!important;stroke:var(--bg)!important;stroke-width:1.5!important}
.stApp .lx-off .lx-ticks{opacity:.3}
@property --n{syntax:'<integer>';inherits:false;initial-value:0}
.stApp .lx-num{counter-reset:n var(--n);transition:--n var(--glide)}
.stApp .lx-num::after{content:counter(n)}
.stApp .lx-read{position:absolute;inset:34% 0 auto;text-align:center;font-weight:300;font-size:clamp(1.8rem,3.4vw,3.4rem);line-height:1}
.stApp .lx-read small{font-size:.45em;color:var(--muted);margin-left:2px}
.stApp .lx-gauge figcaption{margin-top:-1.4rem;font-size:1rem;letter-spacing:.1em;color:var(--muted)}
.stApp .lx-center{text-align:center;min-width:0}
.stApp .lx-clock{margin:0!important;font-weight:300;font-size:clamp(3rem,6vw,6.5rem)!important;line-height:1;letter-spacing:.04em;white-space:nowrap}
.stApp .lx-clock span{font-size:.34em;letter-spacing:.1em;color:var(--muted);margin-right:.35em;vertical-align:.6em}
.stApp .lx-idle .lx-clock{color:var(--strong)}
.stApp .lx-head,.stApp .lx-sub{max-width:40ch;text-wrap:balance}
.stApp .lx-head{margin:1.5rem auto 0!important;font-size:clamp(1.1rem,1.5vw,1.5rem)!important;letter-spacing:.1em;line-height:1.5}
.stApp .lx-sub{margin:.5rem auto 0!important;font-size:clamp(1rem,1.1vw,1.15rem)!important;color:var(--muted)!important;letter-spacing:.06em;line-height:1.6}
.stApp .lx-warn .lx-head{color:var(--warn)}.stApp .lx-error .lx-head{color:var(--err)}
.stApp .lx-solo{grid-template-columns:minmax(0,1fr);padding:3rem 0}
.stApp .lx-line{padding:1rem 0 2.5rem}
.stApp .lx-line ol{position:relative;list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}
.stApp .lx-line li{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;gap:.6rem;min-width:0;font-size:1rem;letter-spacing:.1em;color:var(--muted);text-align:center}
.stApp .lx-line li:not(:last-child)::before,.stApp .lx-line li:not(:last-child)::after{content:"";position:absolute;top:10.5px;left:calc(50% + 11.5px);height:3px;pointer-events:none}
.stApp .lx-line li:not(:last-child)::before{width:calc(100% - 23px);background:var(--strong);opacity:.45}
.stApp .lx-line li:not(:last-child)::after{width:calc(100% - 23px);background:var(--accent);transform:scaleX(0);transform-origin:left center;transition:transform var(--glide)}
.stApp .lx-line li.done:not(:last-child)::after{transform:scaleX(1)}
.stApp .lx-line i{position:relative;z-index:1;flex:none;width:24px;height:24px;border-radius:50%;box-sizing:border-box;border:1px solid var(--strong);background:var(--bg);transition:background-color var(--settle),border-color var(--settle)}
.stApp .lx-line li.done{color:var(--fg)}
.stApp .lx-line li.done i{background:var(--accent);border-color:var(--accent)}
.stApp .lx-line li.active{color:var(--fg)}
.stApp .lx-line li.active span{background:var(--raise);border:1px solid var(--line);border-radius:999px;padding:.2rem .65rem;margin-top:-.2rem}
.stApp .lx-line li.active i{border:2px solid var(--accent)}
.stApp .lx-line li.active i::after{content:"";position:absolute;inset:2px;border:4px solid var(--accent);border-radius:50%;box-sizing:border-box;pointer-events:none}
.stApp .lx-idle .lx-line{opacity:.5}
.stApp .lx-foot{display:grid;gap:.35rem;padding:.9rem 0;border-top:1px solid var(--line);font-size:1rem}
.stApp .lx-foot p{margin:0!important;display:flex;gap:1rem;align-items:baseline;min-width:0;line-height:1.6}
.stApp .lx-foot span{min-width:0;overflow-wrap:anywhere}
.stApp .lx-event time{flex:none;color:var(--muted);letter-spacing:.08em}
.stApp .lx-note .dot{background:var(--warn);align-self:center}
@media (prefers-reduced-motion:no-preference){
@keyframes pn-pulse{0%,100%{opacity:1}50%{opacity:.55}}
.stApp .lx-live .lx-line li.active i::after{animation:pn-pulse 2.4s ease-in-out infinite;will-change:opacity}
.stApp .lx-live .lx-state .dot{animation:pn-pulse 2.4s ease-in-out infinite}
@keyframes pn-sheen{0%{transform:translateX(0);opacity:0}15%,85%{opacity:.14}100%{transform:translateX(400%);opacity:0}}
.stApp .pn-meter.live b::after{content:"";position:absolute;inset:0 auto 0 -35%;width:35%;border-radius:999px;background:var(--ink);animation:pn-sheen 3.2s linear infinite;pointer-events:none}
}
.st-key-pn-ops{flex-direction:row!important;align-items:center;gap:.75rem;padding:.25rem 0 1rem}
.st-key-pn-ops>div{width:auto!important;flex:0 0 auto}
.st-key-pn-detail-scroll{overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--strong) transparent;padding-right:.5rem}
.st-key-pn-detail-scroll::-webkit-scrollbar{width:8px}.st-key-pn-detail-scroll::-webkit-scrollbar-thumb{background:var(--strong);border-radius:8px}
.st-key-pn-detail-scroll::-webkit-scrollbar-track{background:transparent}
.stApp .pn-details{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,22rem),1fr));gap:1rem 3rem;padding:0 0 1.5rem}
.stApp .pn-details section+section{margin-top:1.5rem}
.stApp .pn-details h4,.stApp .pn-sect{margin:0 0 .5rem;padding:0;font-size:1rem;font-weight:400;letter-spacing:.1em;color:var(--muted)!important}
.stApp .pn-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr));gap:0 1.5rem;margin:0}
.stApp .pn-facts>div{border-top:1px solid var(--line);padding:.65rem 0}
.stApp .pn-facts dt{font-size:1rem;color:var(--muted);letter-spacing:.08em}
.stApp .pn-facts dd{margin:.25rem 0 0;font-size:1.3rem;font-weight:300;letter-spacing:.03em}
.stApp .pn-log,.stApp .pn-svc{list-style:none;margin:0;padding:0}
.stApp .pn-log li{display:flex;gap:1rem;align-items:baseline;padding:.5rem 0;border-top:1px solid var(--line);font-size:1rem;line-height:1.55;min-width:0}
.stApp .pn-log time{flex:none;color:var(--muted);letter-spacing:.06em}
.stApp .pn-log span{flex:1;min-width:0;overflow-wrap:anywhere}
.stApp .pn-log em{flex:none;font-style:normal;color:var(--muted)}.stApp .pn-log em.warning{color:var(--warn)}.stApp .pn-log em.error{color:var(--err)}
.stApp .pn-svc li{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.2rem .7rem;padding:.6rem 0;border-top:1px solid var(--line)}
.stApp .pn-svc b{font-weight:400;letter-spacing:.06em}
.stApp .pn-svc li>span{letter-spacing:.1em;color:var(--muted)}
.stApp .pn-svc small{grid-column:2/-1;color:var(--muted);line-height:1.5;font-size:1rem}
.stApp .pn-svc .ok .dot{background:var(--ok)}.stApp .pn-svc .warn .dot{background:var(--warn)}.stApp .pn-svc .error .dot{background:var(--err)}
.stApp .pn-svc .warn>span{color:var(--warn)}.stApp .pn-svc .error>span{color:var(--err)}
.stApp .pn-quiet{margin:0;padding:.5rem 0;color:var(--muted)!important;border-top:1px solid var(--line)}
.stApp [data-testid="stTabs"]{margin-top:2.5rem}
.stApp [data-testid="stTabs"] button[role="tab"] p{font-size:1.1rem!important}
.stApp [data-testid="stTabPanel"]{padding-top:1.75rem}
.stApp .pn-step{display:flex;align-items:center;gap:.8rem;margin:1.75rem 0 .75rem!important;font-size:1.15rem!important;letter-spacing:.06em}
.stApp .pn-step i{display:grid;place-items:center;width:2rem;height:2rem;border-radius:50%;border:1px solid var(--accent);color:var(--accent);font-style:normal;font-size:1rem}
.stApp [data-testid="stColumn"]:has(.pn-step)>div>div:first-child .pn-step{margin-top:0!important}
.st-key-pn-bar{flex-direction:row!important;align-items:center;flex-wrap:wrap;gap:1rem 1.5rem;padding:0 0 1.5rem}
.st-key-pn-bar>div{width:auto!important;flex:0 0 auto}
.st-key-pn-bar>div:has(input){flex:1 1 16rem;min-width:12rem}
.st-key-pn-cards{display:grid!important;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:1.25rem!important}
[class*="st-key-card-"]{position:relative;border:1px solid var(--line);border-radius:14px;overflow:hidden;gap:0!important;background:var(--raise);
  transition:border-color .2s,transform .2s,box-shadow .2s}
[class*="st-key-card-"]:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:none}
[class*="st-key-card-"]:has(button:focus-visible){outline:2px solid var(--accent);outline-offset:3px}
[class*="st-key-card-"] [class*="st-key-open-"]{position:absolute!important;inset:0;z-index:3;margin:0!important;width:100%!important}
[class*="st-key-card-"] [class*="st-key-open-"] .stButton,[class*="st-key-card-"] [class*="st-key-open-"] button{width:100%!important;height:100%!important;margin:0}
[class*="st-key-card-"] [class*="st-key-open-"] button{opacity:0;cursor:pointer;border-radius:14px}
.stApp .pn-card{display:grid}
.stApp .pn-cover{aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden;background:var(--bg);border-bottom:1px solid var(--line)}
.stApp .pn-cover img{width:100%;height:100%;object-fit:cover;display:block}
.stApp .pn-cover b{font-size:3rem;font-weight:300;color:var(--muted)}
.stApp .pn-cbody{display:grid;gap:.3rem;padding:1rem 1rem 1.1rem;min-width:0}
.stApp .pn-cname{font-weight:500;font-size:1.1rem;line-height:1.45;letter-spacing:.03em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.stApp .pn-cbody small{color:var(--muted);font-size:1rem}
.stApp .pn-cfoot{display:flex;justify-content:space-between;align-items:center;gap:.5rem;margin:.35rem 0 0!important;color:var(--muted)}
.stApp .pn-ctime{display:flex;justify-content:space-between;align-items:baseline;gap:.5rem;flex-wrap:wrap;margin:.3rem 0 0!important;color:var(--muted);font-size:1rem}
.stApp .pn-ctime b{color:var(--fg);font-weight:400;font-variant-numeric:tabular-nums;letter-spacing:.05em}
.stApp .pn-mark{display:inline-flex;align-items:center;gap:.5rem;letter-spacing:.06em;color:var(--fg);white-space:nowrap}
.stApp .pn-card.live .dot{background:var(--ok)}.stApp .pn-card.done .dot{background:var(--accent)}.stApp .pn-card.attention .dot{background:var(--warn)}
.stApp .pn-card.attention .pn-mark{color:var(--warn)}
.stApp .pn-meter{display:block;width:100%;height:6px;border-radius:999px;background:var(--line);margin-top:.65rem;overflow:hidden}
.stApp .pn-meter b{position:relative;display:block;height:100%;border-radius:999px;background:var(--accent);transition:width var(--glide);overflow:hidden}
.stApp .pn-meter.live b{background:var(--accent)}
.stApp .pn-empty{padding:3rem 0;text-align:center;color:var(--muted)!important;margin:0}
.stApp .pn-dhead{margin:0 0 1rem}
.stApp .pn-dhead b{display:block;font-size:1.35rem;font-weight:400;letter-spacing:.08em}
.stApp .pn-dhead small{display:block;margin-top:.3rem;color:var(--muted);letter-spacing:.06em}
.stApp .pn-dhead .dot{margin-right:.5rem}
.stApp .pn-dhead.live .dot{background:var(--ok)}.stApp .pn-dhead.done .dot{background:var(--accent)}.stApp .pn-dhead.attention .dot{background:var(--warn)}
.stApp .pn-thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(9rem,1fr));gap:.75rem;margin:.5rem 0}
.stApp .pn-thumbs figure{margin:0;display:grid;gap:.3rem}
.stApp .pn-thumbs img{width:100%;aspect-ratio:16/9;object-fit:cover;border:1px solid var(--line);display:block}
.stApp .pn-thumbs figcaption{font-size:1rem;color:var(--muted);text-align:center}
.stApp .pn-brief{display:grid;grid-template-columns:auto minmax(0,1fr);gap:.4rem 1.25rem;margin:0;padding:1rem 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.stApp .pn-brief dt{color:var(--muted);letter-spacing:.1em}
.stApp .pn-brief dd{margin:0;overflow-wrap:anywhere}
.st-key-pn-acts{flex-direction:row!important;flex-wrap:wrap;gap:.6rem;padding:0 0 1.25rem;border-bottom:1px solid var(--line);margin-bottom:1.25rem}
.st-key-pn-acts>div{width:auto!important;flex:0 0 auto}
.st-key-pn-acts>div:last-child{margin-left:auto}
.st-key-pn-acts>div:last-child button:hover{border-color:var(--err)!important;color:var(--err)!important}
[class*="st-key-pn-nav-"]{flex-direction:row!important;justify-content:center;align-items:center;gap:.6rem;padding-top:.75rem}
[class*="st-key-pn-nav-"]>div{width:auto!important;flex:0 0 auto}
[class*="st-key-pn-nav-"] [data-testid="stNumberInput"]{width:5.5rem}
.stApp .pn-of{margin:0!important;color:var(--muted)}
div[role="dialog"] [data-testid="stImage"] img{border-radius:8px;box-shadow:0 18px 50px -30px rgba(0,0,0,.6)}
@media (max-width:760px){
[data-testid="stMainBlockContainer"]{padding:0 1rem 3rem}
.stApp .pn-brand span{display:none}
.stApp .lx-top{gap:1rem;letter-spacing:.06em}
.stApp .lx-mission,.stApp .lx-side{display:none}
.stApp .lx-time{margin-left:auto}
.stApp .lx{min-height:0}
.stApp .lx-deck{grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem .5rem;padding-top:1.5rem}
.stApp .lx-center{grid-column:1/-1;order:-1}
.stApp .lx-gauge{width:clamp(7rem,38vw,9rem)}
.stApp .lx-line li span{display:none}
.stApp .lx-line li.active span{display:block;white-space:nowrap}
.stApp .lx-line li:first-child.active span{align-self:flex-start}
.stApp .lx-line li:last-child.active span{align-self:flex-end}
.st-key-pn-cards{grid-template-columns:minmax(0,1fr)}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
'''
