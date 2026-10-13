"""Small preview pictures for the 我的教材 cards: the cover as a thumbnail and a strip of page thumbnails.

Thumbnails are made once from the PNG previews of a job and cached next to them (thumbs/), so the page stays light.
"""
import base64
import io
from pathlib import Path


def previews(folder):
    return sorted((Path(folder) / 'previews').glob('*.png'))


def _uri(path):
    return 'data:image/jpeg;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii')


def _make(source, target, width):
    from PIL import Image
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert('RGB')
        image.thumbnail((width, width * 9 // 16 + 1))
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=80, optimize=True)
    target.write_bytes(buffer.getvalue())


def _cached(source, target, width):
    try:
        if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
            _make(source, target, width)
        return _uri(target)
    except (OSError, ValueError):
        return None


def cover_uri(folder, width=480):
    """Data URI of the first page's thumbnail, or None when the job has no preview pictures yet."""
    pages = previews(folder)
    return _cached(pages[0], Path(folder) / 'thumbs' / 'cover.jpg', width) if pages else None


def page_thumbs(folder, limit=12, width=320):
    """[(page number, data URI)] for the first `limit` pages."""
    result = []
    for number, source in enumerate(previews(folder)[:limit], 1):
        uri = _cached(source, Path(folder) / 'thumbs' / f'{number:03d}.jpg', width)
        if uri:
            result.append((number, uri))
    return result