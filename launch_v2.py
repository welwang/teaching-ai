"""Launch the Windows-native controller without resetting a live session."""
import os,sys,time,subprocess,webbrowser
from pathlib import Path
import requests
from filelock import FileLock
from workflow_v2.engine import ensure_server
from workflow_v2 import strata
from workflow_v2.store import atomic
ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8502'


def healthy():
    try:
        response=requests.get(URL+'/_stcore/health',timeout=2)
        return response.ok
    except requests.RequestException:return False


def start_image_service():
    """Start the optional local image service (Forge) in the background; never blocks or fails the launch."""
    try:
        from workflow_v2 import local_images
        print('本機生圖：' + local_images.start_in_background()['message'])
    except Exception as exc:  # noqa: BLE001 - the optional image service must never stop the launch
        print('本機生圖：略過（' + str(exc)[:80] + '）')


def main(no_browser=False):
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    with FileLock(str(logs/'web-start.lock'),timeout=60):
        if not healthy():
            if not strata.is_strata(strata.settings().get('preferred_model','')):
                ensure_server()
            env=os.environ.copy();env['PYTHONUTF8']='1'
            from workflow_v2.runlog import rotate
            for name in ('web-v2.out.log','web-v2.err.log'):rotate(logs/name)
            with (logs/'web-v2.out.log').open('a',encoding='utf-8') as out, \
                 (logs/'web-v2.err.log').open('a',encoding='utf-8') as err:
                p=subprocess.Popen([sys.executable,'-m','streamlit','run','app_v2.py',
                    '--server.address','127.0.0.1','--server.port','8502','--server.headless','true',
                    '--browser.gatherUsageStats','false','--server.fileWatcherType','auto'],
                    cwd=ROOT,env=env,stdout=out,stderr=err,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (logs/'web-v2.pid').write_text(str(p.pid),encoding='utf-8')
            try:
                for _ in range(30):
                    if p.poll() is not None:break
                    if healthy():
                        atomic(ROOT/'data/workflow-v2/session-start.json',{'started':time.time()})
                        break
                    time.sleep(1)
                else:raise RuntimeError('新版網頁啟動超時，請查看 logs/web-v2.err.log')
                if not healthy():raise RuntimeError('新版網頁啟動失敗，請查看 logs/web-v2.err.log')
            except Exception:
                if p.poll() is None:
                    from workflow_v2.worker import stop_tree
                    stop_tree(p)
                (logs/'web-v2.pid').unlink(missing_ok=True)
                raise
    start_image_service()
    if not no_browser:webbrowser.open(URL)
    print(URL)


if __name__=='__main__':main('--no-browser' in sys.argv)
