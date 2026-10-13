"""在 Forge 啟動前停用不相容的 xformers，避免 Windows DLL 錯誤視窗阻塞。
用法：python -u forge_boot.py <launch.py> <Forge 參數>。"""
import os
import runpy
import sys

SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000


def quiet_windows_errors():
    try:
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
        return True
    except (AttributeError, OSError, ImportError):
        return False  # not Windows


def hide_xformers():
    sys.modules['xformers'] = None
    sys.modules['xformers.ops'] = None


def main(argv):
    if not argv:
        raise SystemExit('usage: forge_boot.py <launch.py> [forge arguments...]')
    launcher = os.path.abspath(argv[0])
    quiet_windows_errors()
    hide_xformers()
    os.chdir(os.path.dirname(launcher))
    sys.path.insert(0, os.path.dirname(launcher))
    sys.argv = [launcher] + list(argv[1:])
    runpy.run_path(launcher, run_name='__main__')


if __name__ == '__main__':
    main(sys.argv[1:])