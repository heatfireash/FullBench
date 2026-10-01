"""
Auto-copy for PTCGL.

Watches the game window for the post-match screen, then does the clicks
you'd otherwise do yourself: open Battle Log, select all, copy.
ptcgl_tracker.py picks the result up off the clipboard.

This only sends synthetic input to a window. It does not read or modify
the game process.

Install:
    pip install mss opencv-python-headless numpy pygetwindow pydirectinput

Setup:
    1. python autocopy.py --calibrate
       Finish a match, leave the result screen up, run this. It saves a
       screenshot to ~/ptcgl_calib.png and prints the window geometry.
    2. Crop the Battle Log button out of that screenshot, save it as
       battlelog_button.png next to this script.
    3. python autocopy.py

Run it alongside ptcgl_tracker.py.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import mss
import pygetwindow as gw
import pydirectinput


def _set_dpi_aware():
    """
    Tell Windows this process handles DPI itself.

    Without this, on a multi-monitor setup with different scaling per
    screen, window geometry comes back in logical pixels while the
    screen capture is in physical pixels. Detection still works but
    clicks land offset. Must run before any capture or window query.
    """
    try:
        import ctypes
    except Exception:
        return
    try:
        # -4 = PER_MONITOR_AWARE_V2, best option, Win10 1703+
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


_set_dpi_aware()

def _bundle_dir():
    """
    Where the bundled templates live.

    PyInstaller --onefile unpacks to a temp dir exposed as sys._MEIPASS;
    reading them relative to __file__ would look inside the exe and fail.
    Falls back to the script directory when running from source.
    """
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def _asset(name):
    """Prefer a file next to the exe (user re-crop) over the bundled one."""
    beside = Path(sys.executable).parent / name if getattr(sys, "frozen", False) \
        else Path(__file__).parent / name
    return beside if beside.exists() else _bundle_dir() / name


WINDOW_TITLE_HINT = "Pokemon TCG Live"
TEMPLATE = _asset("battlelog_button.png")
COPY_TEMPLATE = _asset("copy_button.png")
CONTINUE_TEMPLATE = _asset("continue_button.png")
# calibration is user data -- always beside the exe, never in the bundle
CALIB = (Path(sys.executable).parent if getattr(sys, "frozen", False)
         else Path(__file__).parent) / "calibration.json"
COOLDOWN_S = 20          # don't re-fire on the same result screen
POLL_S = 0.10            # how often to look for the result screen
# The result screen can be left and returned to -- clicking Battle Log
# and closing it again, or tabbing away. Re-arming the moment it
# disappears means a second capture of the same match. So the screen has
# to stay gone for this long before another capture is allowed, which is
# longer than any of that fiddling takes and far shorter than a match.
REARM_QUIET_S = 12

# The CONTINUE button is a solid gold bar in a fixed place. Checking a
# few thousand pixels for that colour takes ~0.3ms, against ~90ms for a
# full-frame template match, so it is used as a gate: only when the
# colour is present do we grab the whole window and match properly.
CONTINUE_COLOUR_REGION = (0.36, 0.90, 0.64, 0.99)   # x0, y0, x1, y1
CONTINUE_COLOUR_MIN = 0.12        # fraction of the strip that must be gold
# Both buttons live in the lower middle of the screen; searching only
# there cuts a match from ~90ms to ~6ms.
BUTTON_REGION = (0.28, 0.68, 0.72, 1.00)
# Area to shield from clicks while copying: the CONTINUE button plus a
# margin, in window fractions.
CONTINUE_SHIELD_REGION = (0.34, 0.885, 0.66, 1.00)


def shield_rect(win):
    """Screen-coordinate rect covering the Continue button."""
    x0, y0, x1, y1 = CONTINUE_SHIELD_REGION
    return (win.left + int(win.width * x0),
            win.top + int(win.height * y0),
            int(win.width * (x1 - x0)),
            int(win.height * (y1 - y0)))
PANEL_TIMEOUT_S = 2.5    # max wait for the battle log panel to render
CLIPBOARD_TIMEOUT_S = 2.0  # max wait for the copy to land
# The copy icon can show before the panel takes clicks, so the first click
# is sometimes ignored. If nothing has reached the clipboard this long
# after it, the icon is clicked again (still inside CLIPBOARD_TIMEOUT_S).
RECLICK_AFTER_S = 0.7
# If the automatic copy misses twice -- usually a stray click closed the
# battle log before the copy icon could be clicked -- Continue stays
# covered this long while the player copies the log by hand. After that
# it's uncovered anyway, so the game is never held up for long.
MANUAL_WAIT_S = 20

# --- scale search -------------------------------------------------------
# Full sweep spans 0.35x to 2.0x, which covers a template cropped at 4K
# being matched at 1080p (~0.5x) and the reverse (~2x), plus UI scaling.
SCALE_MIN = 0.35
SCALE_MAX = 2.00
SCALE_STEP = 1.06        # 6% apart -- fine enough not to miss a peak
SCALE_STEPS = 32
WORK_SCALE = 0.5         # match at half res; ~4x faster, same hits

MATCH_THRESHOLD = 0.78       # accept
FAST_PATH_THRESHOLD = 0.90   # good enough to skip the full sweep

# The copy control is a small icon with no text. Small templates match
# loosely, so it gets a stricter threshold and is only searched in the
# region of the panel where it actually appears -- both cut the chance
# of clicking something unrelated.
COPY_MATCH_THRESHOLD = 0.88
COPY_REGION = (0.50, 0.00, 1.00, 0.45)   # x0, y0, x1, y1 as fractions


def find_window():
    """
    The game's own window. Matching the title alone would also pick up a
    browser tab or Explorer window with the same words in it -- and then
    screenshot and click *that* -- so ownership is checked too.
    """
    try:
        import game_watch
        return game_watch.game_window(require_visible=True)
    except ImportError:
        for w in gw.getAllWindows():
            if w.title.strip().lower() == WINDOW_TITLE_HINT.lower() \
                    and w.visible:
                return w
        return None


def grab(win, region=None):
    """
    Capture the window, or just part of it.

    Grabbing a strip instead of the whole window is far cheaper, which
    matters because this runs several times a second while you play.
    """
    left, top, width, height = win.left, win.top, win.width, win.height
    if region:
        x0, y0, x1, y1 = region
        left += int(width * x0)
        top += int(height * y0)
        width = max(1, int(width * (x1 - x0)))
        height = max(1, int(height * (y1 - y0)))
    with mss.mss() as sct:
        img = np.array(sct.grab({"left": left, "top": top,
                                 "width": width, "height": height}))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def continue_colour_present(win):
    """
    Cheap gate: is the gold CONTINUE bar on screen?

    False here means we are not on a result screen and can skip the
    expensive template matching entirely.
    """
    try:
        strip = grab(win, CONTINUE_COLOUR_REGION)
    except Exception:
        return False
    if strip.size == 0:
        return False
    b = strip[:, :, 0].astype(np.int16)
    g = strip[:, :, 1].astype(np.int16)
    r = strip[:, :, 2].astype(np.int16)
    gold = (r > 190) & (g > 150) & (g < 215) & (b < 90)
    return float(gold.mean()) >= CONTINUE_COLOUR_MIN


def _scan(frame_g, template_g, scales, work_scale):
    """Best match over the given scales. Returns (centre_xy, score, scale)."""
    best = (None, 0.0, None)
    fh, fw = frame_g.shape[:2]
    for s in scales:
        t = cv2.resize(template_g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th < 8 or tw < 8 or th > fh or tw > fw:
            continue
        res = cv2.matchTemplate(frame_g, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[1]:
            # map back to full-resolution window coordinates
            cx = (loc[0] + tw / 2) / work_scale
            cy = (loc[1] + th / 2) / work_scale
            best = ((int(cx), int(cy)), score, s)
    return best


def locate(frame, template, expected_scale=None, threshold=None, region=None):
    """
    Find the button across a wide range of render sizes.

    Strategy: match in grayscale on a downscaled frame for speed. If we
    know roughly what scale to expect (from calibration window height),
    search a tight band around it first and stop when it's clearly good.
    Otherwise sweep the full range and take the single best match --
    never the first one over threshold, which at wide ranges is often
    the wrong scale.
    """
    threshold = MATCH_THRESHOLD if threshold is None else threshold

    # optionally restrict the search to part of the window
    off_x = off_y = 0
    if region:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region
        off_x, off_y = int(w * x0), int(h * y0)
        frame = frame[off_y:int(h * y1), off_x:int(w * x1)]
        if frame.size == 0:
            return None, 0.0

    work_scale = WORK_SCALE
    frame_g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    frame_g = cv2.resize(frame_g, None, fx=work_scale, fy=work_scale,
                         interpolation=cv2.INTER_AREA)
    template_g = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    template_g = cv2.resize(template_g, None, fx=work_scale, fy=work_scale,
                            interpolation=cv2.INTER_AREA)

    # fast path: narrow band around the predicted scale
    if expected_scale:
        band = [expected_scale * f for f in (0.92, 0.96, 1.0, 1.04, 1.08)]
        xy, score, s = _scan(frame_g, template_g, band, work_scale)
        if score >= max(FAST_PATH_THRESHOLD, threshold):
            return (xy[0] + off_x, xy[1] + off_y), score
        if score >= threshold:
            return (xy[0] + off_x, xy[1] + off_y), score

    # full sweep: 0.35x to 2.0x covers 4K template -> 1080p and back up
    sweep = [round(SCALE_MIN * (SCALE_STEP ** i), 4)
             for i in range(SCALE_STEPS)]
    sweep = [s for s in sweep if s <= SCALE_MAX]
    xy, score, s = _scan(frame_g, template_g, sweep, work_scale)
    if score >= threshold:
        return (xy[0] + off_x, xy[1] + off_y), score
    return None, score


class _HoldCursor:
    """
    Pin the mouse pointer to one pixel for the length of a click.

    The game reads where the pointer is when the button goes down. If the
    player is moving the mouse at that moment -- easy to do as a match
    ends -- the pointer drifts off the button between our move and our
    click, and the click lands somewhere else. Windows' ClipCursor keeps
    the pointer in a rectangle whatever the mouse does; a one-pixel
    rectangle holds it still. It needs no special permissions.

    Afterwards the pointer is set free, even if the click fails. The one
    limit put back is the game keeping the pointer inside its own window,
    if it was doing that. Any other rectangle is never restored: getting
    that wrong could trap the pointer on one screen.
    """

    def __init__(self, x, y, window=None):
        self.x, self.y = int(x), int(y)
        self.window = window           # (left, top, right, bottom)
        self.old = None
        self.held = False

    def __enter__(self):
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            old = wintypes.RECT()
            if u.GetClipCursor(ctypes.byref(old)):
                self.old = old
            pin = wintypes.RECT(self.x, self.y, self.x + 1, self.y + 1)
            self.held = bool(u.ClipCursor(ctypes.byref(pin)))
        except Exception:
            self.held = False          # not Windows, or refused: click anyway
        return self

    def __exit__(self, *exc):
        if not self.held:
            return False
        try:
            import ctypes
            u = ctypes.windll.user32
            if self._game_was_confining():
                u.ClipCursor(ctypes.byref(self.old))
            else:
                u.ClipCursor(None)
        except Exception:
            pass
        return False

    def _game_was_confining(self):
        o, w = self.old, self.window
        if o is None or w is None:
            return False
        inside = (o.left >= w[0] - 2 and o.top >= w[1] - 2 and
                  o.right <= w[2] + 2 and o.bottom <= w[3] + 2)
        return inside and o.right - o.left > 1 and o.bottom - o.top > 1


def _click(win, xy):
    """
    Click at a point in the game window, with the pointer held there for
    the whole click so a moving mouse can't pull it off the button. The
    hold is about a tenth of a second.
    """
    x, y = win.left + xy[0], win.top + xy[1]
    rect = (win.left, win.top, win.left + win.width, win.top + win.height)
    with _HoldCursor(x, y, rect):
        pydirectinput.moveTo(x, y)
        time.sleep(0.03)
        pydirectinput.click()
        # stay put a couple of frames: the game reads the pointer per frame
        time.sleep(0.05)


def _clipboard():
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _clip_seq():
    """
    Windows' clipboard counter: it goes up every time anything is copied,
    even the exact same text again. None where it isn't available.
    """
    try:
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return None


def _clip_state():
    """What's on the clipboard now, to tell a fresh copy from what was
    already there: (counter, text)."""
    return (_clip_seq(), _clipboard())


def _is_new_log(cur, before):
    """
    A battle log that was copied after the capture began.

    Being a log isn't enough: the clipboard can still hold the previous
    match's log, and if the copy click didn't take, that old log would
    look like a success -- then get thrown away as a repeat, with no
    retry and no pop-up. So something has to have been copied since the
    capture began. Windows' clipboard counter says so directly, even
    when the game copies the same text again; without it, the text has
    to differ.
    """
    if not cur or "Setup" not in cur[:400]:
        return False
    before_seq, before_text = (before if isinstance(before, tuple)
                               else (None, before))
    seq = _clip_seq()
    if seq is not None and before_seq is not None:
        return seq != before_seq
    return cur != before_text


def do_copy(win, btn_xy, copy_template=None, expected_scale=None,
            on_status=None, before=None):
    """
    Click Battle Log, then the copy icon, as fast as the UI allows.

    Speed matters: the log is gone the moment the player presses
    Continue. So instead of sleeping a fixed time for the panel to
    render, poll for the copy button every 80ms and click the instant
    it appears; and instead of assuming the copy worked, watch the
    clipboard for a battle log to show up.

    btn_xy None: the battle log is already open, so only the copy icon
    is clicked.

    Returns True if a battle log reached the clipboard.
    """
    t_start = time.time()
    if before is None:
        before = _clip_state()

    try:
        win.activate()
    except Exception:
        pass

    if btn_xy is not None:
        _click(win, btn_xy)
        if on_status:
            on_status("opening battle log")

    # poll for the copy button rather than sleeping blindly
    clicked = False
    if copy_template is not None:
        deadline = time.time() + PANEL_TIMEOUT_S
        while time.time() < deadline:
            try:
                frame = grab(win)
            except Exception:
                break
            xy, score = locate(frame, copy_template, expected_scale,
                               threshold=COPY_MATCH_THRESHOLD,
                               region=COPY_REGION)
            if xy:
                _click(win, xy)
                clicked = xy
                if on_status:
                    on_status("copying")
                break
            time.sleep(0.08)

    if not clicked and btn_xy is not None:
        # fallback: select-all in the log body
        _click(win, (win.width // 2, win.height // 2))
        pydirectinput.keyDown("ctrl"); pydirectinput.press("a"); pydirectinput.keyUp("ctrl")
        pydirectinput.keyDown("ctrl"); pydirectinput.press("c"); pydirectinput.keyUp("ctrl")
    if not clicked and btn_xy is None:
        return False, None

    # confirm: wait for the clipboard to actually change to a log
    t_click = time.time()
    deadline = t_click + CLIPBOARD_TIMEOUT_S
    reclicked = False
    while time.time() < deadline:
        cur = _clipboard()
        if _is_new_log(cur, before):
            print(f"[autocopy]   captured in {time.time()-t_start:.1f}s"
                  + (" (second click)" if reclicked else ""))
            return True, cur
        if (not reclicked and isinstance(clicked, tuple)
                and time.time() - t_click >= RECLICK_AFTER_S):
            # first click ignored: click the icon again, wherever it is now
            reclicked = True
            xy = clicked
            try:
                found, _ = locate(grab(win), copy_template, expected_scale,
                                  threshold=COPY_MATCH_THRESHOLD,
                                  region=COPY_REGION)
                xy = found or None
            except Exception:
                xy = None
            if xy:
                _click(win, xy)
        time.sleep(0.06)

    print(f"[autocopy]   copy not confirmed after "
          f"{time.time()-t_start:.1f}s")
    return False, None


def retry_copy(win, template, copy_template, expected, on_status, before):
    """
    One more go after a missed copy, while Continue is still covered.

    The usual cause is a click from the player closing the battle log
    before the copy icon could be clicked. Which state it was left in
    decides the move: if the log is open, click just the copy icon (the
    Battle Log button again would close it); if it's closed and the
    Battle Log button is showing, do the whole thing again.
    """
    try:
        frame = grab(win)
    except Exception:
        return False, None
    if copy_template is not None:
        cxy, _ = locate(frame, copy_template, expected,
                        threshold=COPY_MATCH_THRESHOLD, region=COPY_REGION)
        if cxy:
            return do_copy(win, None, copy_template, expected, on_status,
                           before)
    xy, _ = locate(frame, template, expected_scale=expected,
                   region=BUTTON_REGION)
    if xy:
        return do_copy(win, xy, copy_template, expected, on_status, before)
    return False, None


def wait_for_manual_copy(before, seconds, stop=None, skip=None):
    """
    Watch the clipboard while the player copies the log themselves.

    Returns (captured, text, why) -- why is "saved", "skipped",
    "stopped" or "timeout". The result screen being out of sight isn't
    a reason to stop: opening the battle log hides it too.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if stop is not None and stop.is_set():
            return False, None, "stopped"
        if skip is not None and skip.is_set():
            return False, None, "skipped"
        cur = _clipboard()
        if _is_new_log(cur, before):
            return True, cur, "saved"
        time.sleep(0.15)
    return False, None, "timeout"


def calibrate():
    win = find_window()
    if not win:
        print("PTCGL window not found. Is the game running and not minimised?")
        return
    frame = grab(win)
    out = Path.home() / "ptcgl_calib.png"
    cv2.imwrite(str(out), frame)

    CALIB.write_text(json.dumps({
        "window_width": win.width,
        "window_height": win.height,
    }, indent=2))

    print(f"saved {out}")
    print(f"saved {CALIB.name} (window {win.width}x{win.height})")

    # multi-monitor sanity checks
    print(f"\nwindow at left={win.left} top={win.top}")
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=1):
            print(f"  monitor {i}: {m['width']}x{m['height']} "
                  f"at ({m['left']}, {m['top']})")

    if win.left < 0 or win.top < 0:
        print("\n  note: window has negative coordinates -- it's on a monitor")
        print("  left of or above your primary. Check the PNG actually shows")
        print("  the game. If it's black or the wrong screen, move PTCGL to")
        print("  your primary monitor and re-calibrate.")

    mean = float(frame.mean())
    if mean < 3.0:
        print("\n  WARNING: captured frame is essentially black. The grab")
        print("  did not get the game window. Multi-monitor capture issue.")
    else:
        print(f"\n  capture looks valid (mean brightness {mean:.0f}).")

    print("\ncrop the Battle Log button from the PNG -> battlelog_button.png")
    print("if you later change resolution, the scale sweep should still")
    print("find it -- no need to re-crop unless the UI itself changes.")


def load_templates():
    """Returns (battlelog, copy, continue) images; battlelog is required."""
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"missing {TEMPLATE.name} next to this script")
    btn = cv2.imread(str(TEMPLATE))
    cpy = cv2.imread(str(COPY_TEMPLATE)) if COPY_TEMPLATE.exists() else None
    cont = cv2.imread(str(CONTINUE_TEMPLATE)) if CONTINUE_TEMPLATE.exists() else None
    if cpy is None:
        print(f"[autocopy] note: {COPY_TEMPLATE.name} not found -- using ctrl+A/ctrl+C")
    if cont is None:
        print(f"[autocopy] note: {CONTINUE_TEMPLATE.name} not found -- less safe,")
        print("[autocopy]       cannot confirm we're on the result screen")
    return btn, cpy, cont


def watch_screen(poll=POLL_S, stop=None, on_status=None, on_shield=None,
                 on_prompt=None, skip=None):
    """
    Watch for the result screen until `stop` is set.

    Two stages, because speed matters: the log is discarded the moment
    the player presses Continue. A colour check on a small strip runs
    every poll and costs almost nothing; only when it fires do we grab
    the full window and confirm with template matching.

    on_shield(rect, hold_s=None) covers Continue (rect None uncovers it).
    on_prompt("waiting", seconds) / ("saved") / ("missed") drives the
    "copy the log yourself" pop-up; setting `skip` ends the wait early.
    """
    template, copy_template, cont_template = load_templates()

    calib_h = None
    if CALIB.exists():
        try:
            calib_h = json.loads(CALIB.read_text()).get("window_height")
        except Exception:
            pass

    print("[autocopy] watching for the post-match screen"
          + (f" (calibrated at {calib_h}px)" if calib_h else ""))

    last_fire = 0.0
    armed = True
    gone_since = None          # when the result screen last vanished
    last_hash = None           # the match already captured
    while stop is None or not stop.is_set():
        win = find_window()
        if not win:
            time.sleep(2.0)
            continue

        # --- stage 1: is the gold CONTINUE bar there at all? ~0.3ms
        if not continue_colour_present(win):
            if not armed:
                if gone_since is None:
                    gone_since = time.time()
                elif time.time() - gone_since >= REARM_QUIET_S:
                    armed = True
                    gone_since = None
                    print("[autocopy]   re-armed")
            time.sleep(poll)
            continue
        gone_since = None

        if not armed or (time.time() - last_fire) <= COOLDOWN_S:
            time.sleep(poll)
            continue

        # --- stage 2: confirm with template matching, in the region
        #     where these buttons actually live
        t_seen = time.time()
        try:
            frame = grab(win)
        except Exception:
            time.sleep(poll)
            continue

        expected = (win.height / calib_h) if calib_h else None
        xy, score = locate(frame, template, expected_scale=expected,
                           region=BUTTON_REGION)
        if not xy:
            time.sleep(poll)
            continue

        if cont_template is not None:
            cxy, _ = locate(frame, cont_template, expected_scale=expected,
                            region=BUTTON_REGION)
            if cxy is None:
                time.sleep(poll)
                continue

        # Cover the Continue button before doing anything else: the
        # whole point is that it is blocked during the copy, not after.
        before = _clip_state()
        if on_shield:
            on_shield(shield_rect(win))
        if on_status:
            on_status("match over - capturing, don't press Continue")
        print(f"[autocopy] result screen confirmed in "
              f"{(time.time()-t_seen)*1000:.0f}ms (log btn {score:.2f})")
        why = None
        try:
            ok, text = do_copy(win, xy, copy_template, expected, on_status,
                               before)
            stopped = stop is not None and stop.is_set()
            if not ok and not stopped:
                # Continue stays covered, and the cover's clock restarts
                print("[autocopy]   copy missed, trying once more")
                if on_shield:
                    on_shield(shield_rect(win))
                ok, text = retry_copy(win, template, copy_template, expected,
                                      on_status, before)
            if not ok and not stopped and MANUAL_WAIT_S > 0:
                # Still nothing: ask the player to copy it, and keep
                # Continue covered while they do -- for a while.
                print("[autocopy]   asking for the log to be copied by hand")
                if skip is not None:
                    skip.clear()
                if on_shield:
                    on_shield(shield_rect(win), MANUAL_WAIT_S + 2)
                if on_prompt:
                    on_prompt("waiting", MANUAL_WAIT_S)
                if on_status:
                    on_status("copy the battle log")
                ok, text, why = wait_for_manual_copy(before, MANUAL_WAIT_S,
                                                     stop, skip)
                print(f"[autocopy]   manual copy: {why}")
        finally:
            # always drop the shield, even if the copy raised
            if on_shield:
                on_shield(None)
            if on_prompt and why is not None:
                on_prompt("saved" if ok else "missed")
        last_fire = time.time()
        armed = False

        if ok and text:
            h = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
            if h == last_hash:
                # Same match as last time: the screen was revisited rather
                # than a new game finishing. The tracker would reject the
                # duplicate anyway, but say so rather than looking like a
                # fresh capture.
                print("[autocopy]   same match as before, ignoring")
                ok = None
            else:
                last_hash = h

        if on_status:
            on_status("captured" if ok else None)
        if ok is False:
            print("[autocopy] MISSED -- the log was not captured. If you "
                  "pressed Continue, that match is gone; PTCGL does not "
                  "keep it.")

        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--poll", type=float, default=POLL_S)
    args = ap.parse_args()
    if args.calibrate:
        calibrate()
        return
    print("ctrl-c to stop.\n")
    try:
        watch_screen(args.poll)
    except FileNotFoundError as e:
        print(e)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
