"""
Settings, and registering the app to start with Windows (or, on a Mac,
when you log in).

Settings live in a JSON file beside the exe (or beside the scripts when
running from source), so a user can delete the folder and leave nothing
behind.

Windows startup uses the per-user Run key:
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
That needs no administrator rights, only affects this user, and is
visible in Task Manager's Startup tab so it can be turned off there too.
Nothing is written to the registry unless the user ticks the box.

On a Mac it's a login item: a small file in ~/Library/LaunchAgents that
opens Full Bench when you log in. No admin rights either, and it shows
in System Settings under General > Login Items.
"""

import json
import plistlib
import subprocess
import sys
from pathlib import Path

import app_paths

APP_KEY = "FullBench"

DEFAULTS = {
    "start_with_windows": False,
    "auto_track_on_game_launch": True,
    "stop_tracking_on_game_exit": True,
    "start_minimised": False,
    "minimise_to_tray": False,   # Windows: hide by the clock, keep recording
    "tray_told": False,          # the "still running" balloon was shown
    "block_continue": True,
    "ignore_no_attack": True,
    "developer_mode": False,
    "cloud_token": "",     # device token, never the password
    "cloud_email": "",
    "cloud_auto_sync": True,
    "match_toast": True,   # pop-up when a match is recorded
    "hide_email": False,   # show "signed in" instead of the address
}


def _base_dir():
    # beside the exe on Windows, Application Support in a Mac app
    return app_paths.user_dir()


SETTINGS_PATH = _base_dir() / "settings.json"
MAC = sys.platform == "darwin"
LOGIN_LABEL = "gg.fullbench.app"
LOGIN_PLIST = (Path.home() / "Library" / "LaunchAgents"
               / f"{LOGIN_LABEL}.plist")


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


def _mac_app_path():
    """The Full Bench.app this is running from, or None from source."""
    if not getattr(sys, "frozen", False):
        return None
    for p in Path(sys.executable).parents:
        if p.suffix == ".app":
            return p
    return None


def _mac_command():
    app = _mac_app_path()
    if app:
        return ["/usr/bin/open", "-a", str(app)]
    return [sys.executable, str(Path(__file__).parent / "ptcgl_gui.py")]


def _mac_set_startup(enable):
    try:
        if enable:
            LOGIN_PLIST.parent.mkdir(parents=True, exist_ok=True)
            with open(LOGIN_PLIST, "wb") as f:
                plistlib.dump({"Label": LOGIN_LABEL,
                               "ProgramArguments": _mac_command(),
                               "RunAtLoad": True,
                               "ProcessType": "Interactive"}, f)
            return True, "will start when you log in"
        if LOGIN_PLIST.exists():
            # stop launchd tracking it too, so nothing lingers
            subprocess.run(["launchctl", "remove", LOGIN_LABEL],
                           capture_output=True, timeout=5)
            LOGIN_PLIST.unlink()
        return True, "will not start when you log in"
    except Exception as e:
        return False, f"couldn't change the login item: {e}"


def startup_enabled():
    """True if we're registered to run at login."""
    if MAC:
        return LOGIN_PLIST.exists()
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
    if MAC:
        return _mac_set_startup(enable)
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
