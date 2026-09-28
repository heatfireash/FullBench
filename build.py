"""
Build FullBench.exe

    pip install pyinstaller
    py build.py

Produces dist\\FullBench.exe -- a single file, no Python needed on the
target machine. The three button templates are bundled inside it.

Note: single-file exes unpack to a temp dir at launch, so the first start
takes a few seconds. Use --onedir below if you'd rather have a folder that
starts instantly.
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ONEFILE = True          # set False for a faster-starting folder build

REQUIRED = ["ptcgl_gui.py", "ptcgl_tracker.py", "ptcgl_parse.py", "overlay.py",
            "autocopy.py", "ptcgl_stats.py",
            "settings.py", "game_watch.py", "version.py",
            "cloud.py", "archetypes.py", "archetypes.json", "cluster.py",
            "battlelog_button.png", "copy_button.png", "continue_button.png",
            "icon.ico", "logo_small.png"]


def main():
    missing = [f for f in REQUIRED if not (HERE / f).exists()]
    if "icon.ico" in missing or "logo_small.png" in missing:
        print("generating logo first...")
        subprocess.run([sys.executable, "make_logo.py"], cwd=HERE)
        missing = [f for f in REQUIRED if not (HERE / f).exists()]
    if missing:
        print("missing files:", ", ".join(missing))
        return 1

    try:
        import PyInstaller  # noqa
    except ImportError:
        print("pip install pyinstaller")
        return 1

    # PyInstaller only bundles modules it can actually import at build
    # time. --hidden-import tells it where to look; it does NOT install
    # anything. So a missing package here produces an exe that builds
    # fine and then fails on launch asking the user to pip install it.
    # Check up front instead.
    NEEDED = {
        "pyperclip": "pyperclip",          # clipboard watcher -- required
        # headless: identical API, without the GUI libraries this app
        # never touches. Roughly 30 MB smaller in the packaged exe.
        "cv2": "opencv-python-headless",   # template matching
        "numpy": "numpy",
        "mss": "mss",                      # screen capture
        "pygetwindow": "pygetwindow",
        "pydirectinput": "pydirectinput",
        "PIL": "pillow",                   # logo generation
    }
    missing = []
    for mod, pkg in NEEDED.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("These packages are not installed in this Python, so they")
        print("would be left out of the exe and it would fail on launch:\n")
        print("   " + " ".join(missing))
        print("\nInstall them into THIS interpreter and build again:\n")
        print(f'   "{sys.executable}" -m pip install ' + " ".join(missing))
        return 1
    print(f"dependencies OK (building with {sys.executable})\n")

    for d in ("build", "dist"):
        shutil.rmtree(HERE / d, ignore_errors=True)

    sep = ";" if sys.platform == "win32" else ":"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "FullBench",
        "--windowed",                     # no console window
        "--onefile" if ONEFILE else "--onedir",
    ]
    # templates must travel with the exe
    for png in ("battlelog_button.png", "copy_button.png",
                "continue_button.png", "logo_small.png", "icon.ico",
                "archetypes.json"):
        args += ["--add-data", f"{png}{sep}."]
    # our own modules, imported dynamically at runtime
    for mod in ("ptcgl_tracker", "ptcgl_parse", "autocopy", "ptcgl_stats",
                "overlay", "settings", "game_watch", "version",
                "cloud", "archetypes", "cluster"):
        args += ["--hidden-import", mod]
    for mod in ("pyperclip", "cv2", "numpy", "mss",
                "pygetwindow", "pydirectinput"):
        args += ["--hidden-import", mod]
    args += ["--icon", "icon.ico"]
    args.append("ptcgl_gui.py")

    print(" ".join(args), "\n")
    r = subprocess.run(args, cwd=HERE)
    if r.returncode == 0:
        exe = HERE / "dist" / ("FullBench.exe" if sys.platform == "win32"
                               else "FullBench")
        print(f"\nbuilt: {exe}")
        print("Windows SmartScreen will warn on first run -- the exe isn't")
        print("code-signed. 'More info' -> 'Run anyway'. Signing needs a")
        print("certificate (~$100+/yr) and is worth it only if you distribute.")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
