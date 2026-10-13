"""Logo of the 教材AI system: one source image, a few sizes, used in the console bar, the browser tab,
the installer and (only when switched on) the slide cover. Files live in assets/brand."""
import base64
from functools import lru_cache
from pathlib import Path

from .store import ROOT

BRAND = ROOT / 'assets' / 'brand'
FILES = {'original': 'logo-original.png', 512: 'logo-512.png', 192: 'logo-192.png', 64: 'logo-64.png',
         48: 'logo-48.png', 'ico': 'favicon.ico'}
SLIDE_MODES = ('off', 'cover')


def logo_path(key=512):
    path = BRAND / FILES[key]
    return path if path.is_file() else None


@lru_cache(maxsize=8)
def _uri(key, stamp):
    return 'data:image/png;base64,' + base64.b64encode((BRAND / FILES[key]).read_bytes()).decode('ascii')


def data_uri(key=48):
    """Inline PNG for the console bar ('' when the file is missing, so the bar simply has no logo)."""
    path = logo_path(key)
    if not path:
        return ''
    try:
        return _uri(key, path.stat().st_mtime_ns)
    except OSError:
        return ''


def page_icon():
    """Browser-tab icon for st.set_page_config (None lets Streamlit use its default)."""
    path = logo_path(192)
    if not path:
        return None
    try:
        from PIL import Image
        image = Image.open(path)
        image.load()
        return image
    except Exception:
        return None


def slide_logo_mode(config=None):
    """'off' (default) or 'cover' = one small logo at the bottom-left of the cover slide only."""
    if config is None:
        try:
            import yaml
            config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        except Exception:
            config = {}
    value = str(config.get('slide_logo', 'off') if isinstance(config, dict) else 'off').strip().lower()
    return value if value in SLIDE_MODES else 'off'
