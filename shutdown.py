"""Stop generation services; optionally stop this workspace's control UI."""
import sys
from pathlib import Path
from urllib.parse import urlparse

import psutil
import yaml

from workflow_v2.engine import _owned as ollama_owned, listener as ollama_listener
from workflow_v2.store import ROOT, Store
from workflow_v2.worker import pause


def _stop_tree(process):
    """Stop children first so a stage cannot continue after its worker exits."""
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for child in reversed(descendants):
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        process.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    _, alive = psutil.wait_procs(descendants + [process], timeout=8)
    for remaining in alive:
        try:
            remaining.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(alive, timeout=4)


def _owned_worker(process):
    try:
        command = process.cmdline()
        return (process.pid != psutil.Process().pid
                and Path(process.cwd()).resolve() == ROOT.resolve()
                and any(command[i:i + 2] == ['-m', 'workflow_v2.worker']
                        for i in range(len(command) - 1)))
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def _owned_ui(process):
    try:
        command = process.cmdline()
        return (process.pid != psutil.Process().pid
                and Path(process.cwd()).resolve() == ROOT.resolve()
                and any(command[i:i + 3] == ['-m', 'streamlit', 'run']
                        for i in range(len(command) - 2))
                and 'app_v2.py' in command)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def _owned_image_process(process, python, launcher, port):
    try:
        command = process.cmdline()
        cwd = Path(process.cwd())
        scripts = [(cwd / arg).resolve() for arg in command[1:]
                   if Path(arg).name.lower() == 'launch.py']
        return (Path(process.exe()).resolve() == python.resolve()
                and launcher.resolve() in scripts and '--api' in command
                and '--port' in command and command[command.index('--port') + 1] == str(port))
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, IndexError):
        return False


def stop_generation_services(include_ui=False):
    pause()
    for process in psutil.process_iter(['pid']):
        if _owned_worker(process):
            _stop_tree(process)
    remaining = [p.pid for p in psutil.process_iter(['pid']) if _owned_worker(p)]
    if remaining:
        raise RuntimeError('工作程序仍在執行：' + ', '.join(map(str, remaining)))

    # An interrupted stage can retry from its saved checkpoint after resume.
    Store().recover()

    from workflow_v2.strata import owned_process as strata_process, PID_FILE as strata_pid
    owner = strata_process()
    if owner is not None:
        _stop_tree(owner)
        if strata_process() is not None:
            raise RuntimeError('本系統的 Strata 模型服務尚未停止')
        strata_pid.unlink(missing_ok=True)

    owner = ollama_listener()
    if owner is not None and ollama_owned(owner):
        _stop_tree(owner)

    config = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
    python = Path(config.get('image_generation_python', ''))
    launcher = Path(config.get('image_generation_launcher', ''))
    port = urlparse(config.get('image_generation_url', '')).port or 7860
    image_markers = (ROOT / 'data/workflow-v2/image-service.pid', ROOT / 'logs/forge-api.pid')
    if python.is_file() and launcher.is_file():
        for marker in image_markers:
            if not marker.is_file():
                continue
            try:
                process = psutil.Process(int(marker.read_text(encoding='utf-8').strip()))
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if _owned_image_process(process, python, launcher, port):
                _stop_tree(process)
                marker.unlink(missing_ok=True)
                try:  # stopped on purpose: the next start must not count this as a failed start
                    from workflow_v2.local_images import mark_stopped_by_us
                    mark_stopped_by_us()
                except Exception:
                    pass

        for marker in image_markers:
            if not marker.is_file():
                continue
            try:
                process = psutil.Process(int(marker.read_text(encoding='utf-8').strip()))
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if _owned_image_process(process, python, launcher, port):
                raise RuntimeError('本系統的生圖服務尚未停止')
    owner = ollama_listener()
    if owner is not None and ollama_owned(owner):
        raise RuntimeError('本系統的模型服務尚未停止')
    if include_ui:
        for process in psutil.process_iter(['pid']):
            if _owned_ui(process):
                _stop_tree(process)


if __name__ == '__main__':
    try:
        stop_generation_services(include_ui='--include-ui' in sys.argv[1:])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
