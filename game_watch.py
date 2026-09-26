"""
Detect whether Pokemon TCG Live is running.

Two detection methods, tried in order:

  1. A visible window whose title matches -- cheap, and it also tells us
     the game is actually up rather than still loading.
  2. The process list via tasklist -- catches the case where the window
     is minimised or the title differs.

Method 2 shells out, so it runs at most every few seconds. Method 1 is
used for the fast path.

watch() calls on_start() when the game appears and on_stop() when it
goes away, and nothing at all while the state is unchanged.
"""

import subprocess
import sys
import time

TITLE_HINTS = ("pokemon tcg live", "pokémon tcg live")
PROC_HINTS = ("pokemon tcg live.exe", "pokemontcglive.exe")

_CREATE_NO_WINDOW = 0x08000000      # keep tasklist from flashing a console


def _by_window():
    try:
        import pygetwindow as gw
    except ImportError:
        return None                  # unknown, fall through to process check
    try:
        for w in gw.getAllWindows():
            t = (w.title or "").lower()
            if any(h in t for h in TITLE_HINTS):
                return True
        return False
    except Exception:
        return None


def _by_process():
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=8,
            creationflags=_CREATE_NO_WINDOW).stdout.lower()
    except Exception:
        return None
    return any(h in out for h in PROC_HINTS)


def is_running(use_process=True):
    """True / False, or False if neither method could tell."""
    w = _by_window()
    if w:
        return True
    if not use_process:
        return bool(w)
    p = _by_process()
    if p is not None:
        return p
    return bool(w)


def watch(on_start=None, on_stop=None, stop=None, poll=3.0,
          process_every=4):
    """
    Poll until `stop` is set, firing callbacks on transitions only.

    The window check runs every poll; the heavier process check runs
    every `process_every` polls, so a minimised game is still noticed
    without shelling out constantly.
    """
    running = None
    i = 0
    while stop is None or not stop.is_set():
        i += 1
        now = is_running(use_process=(i % process_every == 0))
        if running is None:
            running = now
            if now and on_start:
                on_start()
        elif now != running:
            running = now
            if now and on_start:
                on_start()
            elif not now and on_stop:
                on_stop()
        time.sleep(poll)


if __name__ == "__main__":
    print("window check :", _by_window())
    print("process check:", _by_process())
    print("running      :", is_running())
