"""
Full Bench -- command-line entry point.

Runs the clipboard watcher and the screen watcher in one process.

    py ptcgl.py                  run everything
    py ptcgl.py --deck "Mega Excadrill"
    py ptcgl.py --no-autocopy    clipboard only (you copy manually)
    py ptcgl.py --calibrate      capture a screenshot for template cropping
    py ptcgl.py --stats          quick summary, then exit

Ctrl-C stops it cleanly.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default=None,
                    help="your PTCGL name (auto-detected from logs if omitted)")
    ap.add_argument("--deck", default=None,
                    help="label for the deck you're playing this session")
    ap.add_argument("--no-autocopy", action="store_true",
                    help="don't drive the game window; only watch clipboard")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.calibrate:
        import autocopy
        autocopy.calibrate()
        return

    if args.stats:
        import ptcgl_stats
        sys.argv = [sys.argv[0]]
        ptcgl_stats.main()
        return

    import ptcgl_tracker
    stop = threading.Event()
    threads = []

    t = threading.Thread(
        target=ptcgl_tracker.watch_clipboard,
        kwargs=dict(me=args.me, deck=args.deck, stop=stop),
        name="tracker", daemon=True)
    threads.append(t)

    if not args.no_autocopy:
        try:
            import autocopy
            autocopy.load_templates()      # fail early if a template is missing
            t2 = threading.Thread(
                target=autocopy.watch_screen,
                kwargs=dict(stop=stop),
                name="autocopy", daemon=True)
            threads.append(t2)
        except FileNotFoundError as e:
            print(f"[autocopy] disabled: {e}")
            print("[autocopy] run  py ptcgl.py --calibrate  to make one,")
            print("[autocopy] or use --no-autocopy to silence this.")
        except ImportError as e:
            print(f"[autocopy] disabled, missing package: {e.name}")
            print("[autocopy] pip install mss opencv-python-headless numpy pygetwindow pydirectinput")

    for t in threads:
        t.start()

    deck = f"  deck={args.deck!r}" if args.deck else "  (no deck label -- use --deck)"
    print(f"\nrunning {len(threads)} watcher(s).{deck}")
    print("ctrl-c to stop.\n")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopping...")
        stop.set()
        for t in threads:
            t.join(timeout=3)


if __name__ == "__main__":
    main()
