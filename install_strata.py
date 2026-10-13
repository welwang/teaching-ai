"""Install the article's pinned Windows runtime, independently from the app venv.

Model files live under models/strata and are excluded from application packages.
Rerunning resumes incomplete downloads. This script never changes saved jobs.
"""
import hashlib, importlib.util, io, json, os, subprocess, sys, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime/strata'
VERSION = 'v0.1.30'
COMMIT = '30ec18ec7094550fcc594fd948220d511d80464e'
MODEL_REVISION = 'ed59f92082b1e93c0e96d60a8b11aab089b52f09'


def download(url, target, what=None):
    """Validated resumable transfer with small buffers and visible progress."""
    import requests
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = target.with_name(target.name + '.done')
    if target.is_file() and marker.is_file():
        return
    if not url.startswith(('http://', 'https://')):
        import shutil
        shutil.copyfile(url.removeprefix('file://'), target)
        marker.write_text('copied', encoding='utf-8')
        return
    part = target.with_name(target.name + '.part')
    for attempt in range(8):
        offset = part.stat().st_size if part.exists() else 0
        try:
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with requests.get(url, headers=headers, stream=True, timeout=(30, 60)) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    content_range = response.headers.get('Content-Range', '')
                    if not content_range.startswith(f'bytes {offset}-'):
                        raise ValueError('Server returned an incorrect download range')
                    total = int(content_range.split('/')[-1])
                else:
                    offset = 0
                    total = int(response.headers.get('Content-Length', 0))
                last = 0
                with part.open('ab' if offset else 'wb') as stream:
                    for block in response.iter_content(256 * 1024):
                        if not block:
                            continue
                        stream.write(block)
                        offset += len(block)
                        if time.monotonic() - last > 5:
                            last = time.monotonic()
                            print(f'{what or target.name}: {offset/1e9:.3f}/{total/1e9:.3f} GB', flush=True)
                if not total or offset != total:
                    raise ValueError(f'Download incomplete: {offset}/{total}')
                part.replace(target)
                marker.write_text(json.dumps({'bytes': total, 'url': url}), encoding='utf-8')
                return
        except (requests.RequestException, ValueError) as exc:
            print(f'Download retry {attempt+1}/8: {exc}', flush=True)
            if attempt == 7:
                raise
            time.sleep(min(30, 2 ** attempt))


def main():
    os.environ['PYTHONUTF8'] = '1'
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (ROOT / 'logs').mkdir(exist_ok=True)
    (ROOT / 'logs/strata-installer.pid').write_text(str(os.getpid()), encoding='utf-8')
    source_marker = RUNTIME / 'teaching-ai-source.json'
    if not source_marker.exists():
        import requests
        response = requests.get(f'https://github.com/Niko1221/Strata/archive/{COMMIT}.zip', timeout=120)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            prefix = archive.namelist()[0]
            for item in archive.infolist():
                path = (RUNTIME / Path(item.filename).relative_to(prefix)).resolve()
                if not path.is_relative_to(RUNTIME.resolve()):
                    raise ValueError('Unsafe source archive path')
                if not item.is_dir():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.read(item))
        source_marker.write_text(json.dumps({'version': VERSION, 'commit': COMMIT,
            'archive_sha256': hashlib.sha256(response.content).hexdigest()}), encoding='utf-8')
    python = RUNTIME / '.venv/Scripts/python.exe'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(RUNTIME / '.venv')], check=True)
    if '--worker' not in sys.argv:
        subprocess.run([str(python), '-m', 'pip', 'install', 'requests'], check=True)
        return subprocess.call([str(python), str(Path(__file__).resolve()), '--worker'])
    spec = importlib.util.spec_from_file_location('strata_setup', RUNTIME / 'setup.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    # Pin the model snapshot as well as the engine. The model's meaning and
    # weights must not silently change on the next installation.
    setup.FAMILIES['qwen']['hf'] = setup.FAMILIES['qwen']['hf'].replace('/resolve/main/', f'/resolve/{MODEL_REVISION}/')
    setup.download = download
    sys.argv = [str(RUNTIME / 'setup.py'), '--family', 'qwen', '--model', 'IQ3_S',
        '--context', '131072', '--kv', 'int8', '--vision', 'no',
        '--experimental-speed-projection', 'off', '--draft-vocab', 'cjk',
        '--low-ram', 'resident', '--port', '8088', '--host', '127.0.0.1',
        '--data-dir', str(ROOT / 'models/strata'), '--prebuilt',
        f'https://github.com/Niko1221/Strata/releases/download/{VERSION}/', '--yes', '--no-start']
    code = setup.main()
    if code == 0:
        lock = subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True)
        (RUNTIME / 'installed-requirements.txt').write_text(lock, encoding='utf-8')
        (RUNTIME / 'teaching-ai-installed.json').write_text(json.dumps({
            'version': VERSION, 'commit': COMMIT, 'model_revision': MODEL_REVISION,
            'model': 'IQ3_S', 'installed_at': time.time()}, indent=2), encoding='utf-8')
        print('Strata installed. Select Strata in the teaching AI model menu.', flush=True)
    return code


if __name__ == '__main__':
    # Only the orchestrator owns the lock: its isolated worker inherits no
    # lock and cannot deadlock itself. A second UI click cannot overwrite files.
    if '--worker' in sys.argv:
        raise SystemExit(main())
    from filelock import FileLock
    (ROOT / 'logs').mkdir(exist_ok=True)
    with FileLock(str(ROOT / 'logs/strata-install.lock'), timeout=0):
        raise SystemExit(main())
