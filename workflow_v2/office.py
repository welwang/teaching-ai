"""One bounded LibreOffice conversion with a disposable profile and child cleanup."""
import os,shutil,subprocess,tempfile
from pathlib import Path
from filelock import FileLock
from .store import ROOT,DATA


def executable():
    candidates=[ROOT/'runtime/libreoffice/program/soffice.com']
    for key in ('ProgramFiles','ProgramFiles(x86)'):
        if os.getenv(key):candidates.append(Path(os.environ[key])/'LibreOffice/program/soffice.com')
    on_path=shutil.which('soffice.com') or shutil.which('soffice')
    if on_path:candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file():return candidate
    raise RuntimeError('LibreOffice 未安裝，請安裝 Windows 版後再製作 PDF 預覽')

def convert(source,folder,format='pdf',timeout=120):
    if format not in ('pdf','pptx'):raise ValueError('不支援的轉檔格式')
    sources=[Path(item).resolve() for item in source] if isinstance(source,(list,tuple)) else [Path(source).resolve()]
    if not sources or any(not item.is_file() for item in sources):raise ValueError('找不到轉檔來源')
    folder=Path(folder).resolve()
    exe=executable()
    folder.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    with FileLock(str(DATA/'libreoffice.lock'),timeout=180), \
         tempfile.TemporaryDirectory(prefix='office-',dir=folder) as profile:
        command=[str(exe),'-env:UserInstallation='+Path(profile).as_uri(),
                 '--headless','--convert-to',format,'--outdir',str(folder),*[str(item) for item in sources]]
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            stdout,stderr=process.communicate(timeout=timeout)
        except BaseException:
            from .worker import stop_tree
            stop_tree(process)
            raise
        return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)


def convert_pdf(source,folder,timeout=120):
    return convert(source,folder,timeout=timeout)
