"""
Detect whether Pokemon TCG Live is running.

The game is recognised by its window, and a window only counts if it
really is the game's:

  * its title, with accents stripped, contains "pokemon tcg live", AND
  * it is owned by the game's exe, or is a Unity game window

The title alone is not enough. A browser tab on a PTCGL deck site, a
YouTube video, a Discord channel or an Explorer window open on the
install folder all carry the same words, and used to make the app think
the game was running -- and start tracking -- with the game closed.

The state only changes after two readings in a row agree, so a single
odd reading (a window mid-close, a slow process lookup) cannot flip
tracking on and off.

watch() calls on_start() when the game appears and on_stop() when it
goes away, and nothing at all while the state is unchanged.
last_match describes the window that was recognised, for the log.
"""

import os
import subprocess
import sys
import time
import unicodedata

TITLE_HINT = "pokemon tcg live"
PROC_HINTS = ("pokemon tcg live.exe", "pokemontcglive.exe")
UNITY_CLASS = "UnityWndClass"
# Programs that are never the game, whatever their window says.
NOT_GAME = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe",
            "brave.exe", "explorer.exe", "discord.exe", "obs64.exe",
            "notepad.exe", "code.exe", "fullbench.exe", "python.exe",
            "pythonw.exe", "steam.exe")

_CREATE_NO_WINDOW = 0x08000000      # keep tasklist from flashing a console

last_match = ""                      # human-readable, for the app's log


def _norm(text):
    """'Pokémon TCG Live' -> 'pokemon tcg live'."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


# ------------------------------------------------------ window ownership

def _win32():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD)
    return ctypes, wintypes, user32, kernel32


_W = _win32()


def window_class(hwnd):
    if not _W or not hwnd:
        return ""
    ctypes, wintypes, user32, _ = _W
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    except Exception:
        return ""
    return buf.value


def window_exe(hwnd):
    """File name of the program that owns the window, lower case."""
    if not _W or not hwnd:
        return ""
    ctypes, wintypes, user32, kernel32 = _W
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd),
                                        ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # query limited
        if not h:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf,
                                                   ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def is_game_window(title, cls, exe):
    """
    The decision, kept free of Windows calls so it can be tested.

    title  the window title
    cls    its window class ("" if unknown)
    exe    owning program's file name ("" if unknown)
    """
    if TITLE_HINT not in _norm(title):
        return False
    exe = (exe or "").lower()
    if exe in NOT_GAME:
        return False
    if exe and any(exe == p for p in PROC_HINTS):
        return True
    if cls == UNITY_CLASS:
        return True
    # Nothing to confirm it with (not Windows, or the lookups failed):
    # accept only a title that is exactly the game's, never one with a
    # page name or " - Google Chrome" around it.
    if not cls and not exe:
        return _norm(title).strip() == TITLE_HINT
    return False


def game_window(require_visible=False):
    """The game's pygetwindow window, or None. Also used by autocopy."""
    global last_match
    try:
        import pygetwindow as gw
        wins = gw.getAllWindows()
    except Exception:
        return None
    for w in wins:
        title = w.title or ""
        if TITLE_HINT not in _norm(title):
            continue                     # cheap filter before any lookups
        if require_visible and not getattr(w, "visible", True):
            continue
        hwnd = getattr(w, "_hWnd", None)
        cls, exe = window_class(hwnd), window_exe(hwnd)
        if is_game_window(title, cls, exe):
            last_match = f"'{title}' ({exe or '?'}, {cls or '?'})"
            return w
    return None


# ------------------------------------------------------------ detection

def _by_window():
    try:
        import pygetwindow  # noqa: F401
    except ImportError:
        return None                      # can't tell this way
    return game_window() is not None


def _by_process():
    """Fallback only, for when windows cannot be listed at all."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=8,
            creationflags=_CREATE_NO_WINDOW).stdout.lower()
    except Exception:
        return None
    return any(f'"{h}"' in out for h in PROC_HINTS)


def is_running():
    """
    One reading. The window check decides whenever it can; the process
    list is consulted only when windows can't be listed, so the two can
    never take turns and disagree.
    """
    global last_match
    w = _by_window()
    if w is not None:
        return w
    p = _by_process()
    if p:
        last_match = "game process found (window check unavailable)"
    return bool(p)


def watch(on_start=None, on_stop=None, stop=None, poll=3.0, confirm=2):
    """
    Poll until `stop` is set, firing callbacks on transitions only.

    A change must be seen `confirm` times in a row before it counts.
    """
    running = None
    streak = 0
    while stop is None or not stop.is_set():
        now = is_running()
        if running is None:
            running = now
            if now and on_start:
                on_start()
        elif now != running:
            streak += 1
            if streak >= confirm:
                running, streak = now, 0
                if now and on_start:
                    on_start()
                elif not now and on_stop:
                    on_stop()
        else:
            streak = 0
        time.sleep(poll)


if __name__ == "__main__":
    # py game_watch.py  -- lists every window that mentions the game and
    # says which one, if any, counts as the game.
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if TITLE_HINT in _norm(w.title):
                h = getattr(w, "_hWnd", None)
                c, e = window_class(h), window_exe(h)
                verdict = "GAME" if is_game_window(w.title, c, e) else "ignored"
                print(f"{verdict:8} '{w.title}'  exe={e or '?'}  class={c or '?'}")
    except ImportError:
        print("pygetwindow not installed")
    print("running:", is_running(), "|", last_match or "-")
