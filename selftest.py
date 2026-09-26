"""
Self-test for autocopy templates.

Run this with PTCGL showing the post-match result screen. It checks that
the Battle Log button is found on the live screen, and reports the match
score and where it would click -- without clicking anything.

    py selftest.py

Safe to run any time: it never sends input to the game.
"""

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import autocopy as ac


def check_template(path: Path, label: str):
    if not path.exists():
        print(f"  {label}: MISSING ({path.name})")
        return None
    img = cv2.imread(str(path))
    if img is None:
        print(f"  {label}: unreadable -- not a valid PNG?")
        return None
    h, w = img.shape[:2]
    note = ""
    if w < 60 or h < 20:
        note = "  <-- suspiciously small, did the crop get downscaled?"
    print(f"  {label}: {w}x{h}{note}")
    return img


def main():
    print("templates:")
    btn = check_template(ac.TEMPLATE, "battle log button")
    cpy = check_template(ac.COPY_TEMPLATE, "copy button      ")
    if btn is None:
        print("\ncannot continue without battlelog_button.png")
        return

    win = ac.find_window()
    if not win:
        print("\nPTCGL window not found. Is the game running, not minimised?")
        return
    print(f"\nwindow: {win.width}x{win.height} at ({win.left}, {win.top})")

    calib_h = None
    if ac.CALIB.exists():
        import json
        calib_h = json.loads(ac.CALIB.read_text()).get("window_height")
    expected = (win.height / calib_h) if calib_h else None
    if expected:
        print(f"predicted scale: {expected:.3f}  (calibrated at {calib_h}px tall)")

    frame = ac.grab(win)
    mean = float(frame.mean())
    print(f"capture mean brightness: {mean:.0f}"
          + ("   <-- BLACK, capture failed" if mean < 3 else "   ok"))

    xy, score = ac.locate(frame, btn, expected_scale=expected)
    print(f"\nbattle log button: score={score:.2f} "
          f"(threshold {ac.MATCH_THRESHOLD})")
    if xy:
        print(f"  FOUND at window ({xy[0]}, {xy[1]}) "
              f"-> screen ({win.left + xy[0]}, {win.top + xy[1]})")
        out = Path.home() / "ptcgl_selftest.png"
        marked = frame.copy()
        cv2.circle(marked, xy, 28, (0, 0, 255), 4)
        cv2.imwrite(str(out), marked)
        print(f"  marked screenshot saved -> {out}")
        print("  open it and confirm the circle is on the button.")
    else:
        print("  NOT FOUND. Re-crop the template from a fresh calibrate,")
        print("  or lower MATCH_THRESHOLD in autocopy.py and retry.")

    if cpy is not None:
        cxy, cscore = ac.locate(frame, cpy, expected_scale=expected)
        print(f"\ncopy button: score={cscore:.2f} "
              f"({'found' if cxy else 'not on this screen'})")
        print("  (expected: not found here -- it only appears after the")
        print("   battle log panel is open)")


if __name__ == "__main__":
    main()
