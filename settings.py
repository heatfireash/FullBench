"""
Settings, and registering the app to start with Windows.

Settings live in a JSON file beside the exe (or beside the scripts when
running from source), so a user can delete the folder and leave nothing
behind.

Windows startup uses the per-user Run key:
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
That needs no administrator rights, only affects this user, and is
visible in Task Manager's Startup tab so it can be turned off there too.
Nothing is written to the registry unless the user ticks the box.
"""

import json
import sys
from pathlib import Path

APP_KEY = "FullBench"

DEFAULTS = {
    "start_with_windows": False,
    "auto_track_on_game_launch": True,
    "stop_tracking_on_game_exit": True,
    "start_minimised": False,
    "block_continue": True,
    "ignore_no_attack": True,
    "developer_mode": False,
    "cloud_token": "",     # device token, never the password
    "cloud_email": "",
    "cloud_auto_sync": True,
}


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


SETTINGS_PATH = _base_dir() / "settings.json"


def load():
    s = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def save(s):
    try:
        SETTINGS_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# ------------------------------------------------------- windows startup

def _launch_command():
    """The command Windows should run at login."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # from source: pythonw avoids a console window
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else exe
    script = Path(__file__).parent / "ptcgl_gui.py"
    return f'"{runner}" "{script}"'


def startup_enabled():
    """True if we're registered to run at login."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, APP_KEY)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup(enable):
    """
    Add or remove the login entry. Returns (ok, message).

    Non-Windows platforms report cleanly instead of raising.
    """
    try:
        import winreg
    except ImportError:
        return False, "only available on Windows"

    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        if enable:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                winreg.SetValueEx(k, APP_KEY, 0, winreg.REG_SZ,
                                  _launch_command())
            return True, "will start with Windows"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, APP_KEY)
            except FileNotFoundError:
                pass
        return True, "will not start with Windows"
    except PermissionError:
        return False, "permission denied writing to the registry"
    except OSError as e:
        return False, f"registry error: {e}"
