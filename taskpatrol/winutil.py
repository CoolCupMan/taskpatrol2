"""Small Windows helpers. Every function is a safe no-op on other platforms."""

import os
import subprocess
import sys
from pathlib import Path

from taskpatrol import APP_ID, APP_NAME, MUTEX_NAME, __version__

IS_WINDOWS = sys.platform == "win32"

# Hides the console window that would otherwise flash for child processes.
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

_mutex_handle = None


def init_process():
    """Set the per-version taskbar identity and DPI awareness. Call before Tk starts."""
    global _mutex_handle
    if not IS_WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    # Lets the installer/uninstaller of this exact version detect that it is running.
    try:
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    except (AttributeError, OSError):
        pass


def is_admin():
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_as_admin():
    """Start a new elevated copy of the app. Returns True if the UAC prompt was accepted."""
    if not IS_WINDOWS:
        return False
    import ctypes

    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe, params = sys.executable, subprocess.list2cmdline(["-m", "taskpatrol", *sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def data_dir():
    """Per-version folder for logs, so parallel versions never share files."""
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / APP_NAME / __version__
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(name):
    """Locate a bundled file both from source and inside the PyInstaller exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def open_folder(path, select=False):
    path = Path(path)
    if IS_WINDOWS:
        if select:
            subprocess.Popen(["explorer", "/select,", str(path)], creationflags=NO_WINDOW)
        else:
            os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", *(["-R"] if select else []), str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if select else path)])
