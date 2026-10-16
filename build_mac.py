"""
Build Full Bench for macOS.

    python3 build_mac.py

Run it on a Mac. Produces:

    dist/Full Bench.app                the app
    dist/FullBench-<version>-mac.dmg   the app in a disk image, with an
                                       Applications shortcut to drag it to

It's built for the kind of Mac it's built on (Apple silicon or Intel).

Setup, once. Use Python 3.13 from python.org, called by name: macOS's
own python3 is 3.9, too old for pyobjc (pip then tries to build it from
source and fails), and its Tk draws the app badly.

    python3.13 -m venv ~/fullbench-venv
    source ~/fullbench-venv/bin/activate
    python -m pip install --upgrade pip
    pip install pyinstaller pyperclip opencv-python-headless numpy pillow \\
        certifi pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \\
        pyobjc-framework-ScreenCaptureKit pyobjc-framework-CoreMedia \\
        pyobjc-framework-ApplicationServices pyobjc-framework-libdispatch

The app is signed "ad hoc" (no Apple Developer account), which is fine
on your own Mac. Two things follow from that:

  * macOS ties Screen Recording and Accessibility to the exact build. A
    new build can show as allowed and still be refused, with no error.
    After installing one, reset both and allow them again:
        tccutil reset ScreenCapture gg.fullbench.app
        tccutil reset Accessibility gg.fullbench.app
  * Someone who downloads it gets "Apple could not verify Full Bench".
    They can open it from System Settings > Privacy & Security > Open
    Anyway. Getting rid of that needs an Apple Developer account ($99 a
    year) to sign and notarize it: set FULLBENCH_SIGN_ID to your
    "Developer ID Application: ..." name and it's signed with that
    instead (notarizing is a separate step, not done here).
"""

import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
APP_NAME = "Full Bench"
BUNDLE_ID = "gg.fullbench.app"
MIN_MACOS = "12.3"           # ScreenCaptureKit's first version

REQUIRED = ["ptcgl_gui.py", "ptcgl_tracker.py", "ptcgl_parse.py", "overlay.py",
            "autocopy.py", "ptcgl_stats.py", "settings.py", "game_watch.py",
            "version.py", "cloud.py", "archetypes.py", "archetypes.json",
            "cluster.py", "updater.py", "evolutions.py", "app_paths.py",
            "look.py", "mac_platform.py", "welcome.py",
            "battlelog_button.png", "copy_button.png", "continue_button.png",
            "icon.ico", "logo_small.png",
            "gate_replays.png", "gate_stats.png", "gate_devices.png", "gate_meta.png"]

# module -> pip package. PyInstaller only bundles what's installed in the
# Python that runs it, so a missing one would build fine and then fail
# when the app opens.
NEEDED = {
    "PyInstaller": "pyinstaller",
    "pyperclip": "pyperclip",
    "cv2": "opencv-python-headless",
    "numpy": "numpy",
    "PIL": "pillow",
    "certifi": "certifi",       # HTTPS: see cloud.tls_context
    "objc": "pyobjc-core",
    "AppKit": "pyobjc-framework-Cocoa",
    "Quartz": "pyobjc-framework-Quartz",
    "ScreenCaptureKit": "pyobjc-framework-ScreenCaptureKit",
    "CoreMedia": "pyobjc-framework-CoreMedia",
    "ApplicationServices": "pyobjc-framework-ApplicationServices",
    "dispatch": "pyobjc-framework-libdispatch",
}

OUR_MODULES = ["ptcgl_tracker", "ptcgl_parse", "autocopy", "ptcgl_stats",
               "overlay", "settings", "game_watch", "version", "cloud",
               "archetypes", "cluster", "updater", "evolutions", "app_paths",
               "look", "mac_platform", "welcome"]
DATA = ["battlelog_button.png", "copy_button.png", "continue_button.png",
        "logo_small.png", "icon.ico", "archetypes.json",
        "gate_replays.png", "gate_stats.png", "gate_devices.png", "gate_meta.png"]


def version():
    m = re.search(r'^VERSION = "([^"]+)"', (HERE / "version.py").read_text(),
                  re.M)
    return m.group(1) if m else "0.0.0"


def check():
    if sys.platform != "darwin":
        print("Run this on a Mac. (build.py makes the Windows exe.)")
        return False
    if sys.version_info < (3, 10):
        print(f"This is Python {sys.version.split()[0]} ({sys.executable}).")
        print("The Mac packages need 3.10 or newer: install Python 3.13 from")
        print("python.org and make the venv with python3.13 (see the top of")
        print("this file).")
        return False
    missing = [f for f in REQUIRED if not (HERE / f).exists()]
    if missing:
        print("missing files:", ", ".join(missing))
        return False
    pkgs = []
    for mod, pkg in NEEDED.items():
        try:
            __import__(mod)
        except ImportError:
            pkgs.append(pkg)
    venv = Path.home() / "fullbench-venv" / "bin" / "python3"
    if pkgs and sys.prefix == sys.base_prefix and venv.exists():
        print("This is Python outside the venv, which doesn't have the")
        print("packages. Turn the venv on first, then build again:\n")
        print("   source ~/fullbench-venv/bin/activate")
        print("   python3 build_mac.py")
        return False
    if pkgs:
        print("These aren't installed in this Python, so they'd be left out")
        print("of the app and it would fail when opened:\n")
        print("   " + " ".join(pkgs))
        print(f'\n   "{sys.executable}" -m pip install ' + " ".join(pkgs))
        return False
    try:
        import tkinter
        tk_version = float(tkinter.Tcl().eval("info tclversion"))
    except Exception as e:
        print(f"This Python has no working Tk ({e}). Use Python from "
              "python.org, or `brew install python-tk`.")
        return False
    if tk_version < 8.6:
        print(f"This Python has Tk {tk_version}, which draws the app badly "
              "on macOS. Use Python from python.org.")
        return False
    return True


def icon():
    """icon.icns if it's there, else made from the biggest icon.ico frame."""
    icns = HERE / "icon.icns"
    if icns.exists():
        return icns
    from PIL import Image
    out = HERE / "build" / "FullBench.icns"
    out.parent.mkdir(exist_ok=True)
    im = Image.open(HERE / "icon.ico")
    im.size = max(im.info.get("sizes", [im.size]))
    im.load()
    im = im.convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    im.save(out)
    return out


def pyinstaller(icns):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--name", APP_NAME, "--windowed", "--onedir",
            "--osx-bundle-identifier", BUNDLE_ID,
            "--icon", str(icns)]
    for f in DATA:
        args += ["--add-data", f"{f}:."]
    for mod in OUR_MODULES:
        args += ["--hidden-import", mod]
    for mod in ("pyperclip", "cv2", "numpy", "objc", "Foundation", "AppKit",
                "Quartz", "HIServices", "certifi"):
        args += ["--hidden-import", mod]
    # these load their compiled parts at run time, which PyInstaller can't
    # see by reading the code, so everything in them is brought along
    for pkg in ("ScreenCaptureKit", "CoreMedia", "ApplicationServices",
                "dispatch"):
        args += ["--collect-all", pkg]
    # the Windows-only packages, in case they're installed here too
    for mod in ("pygetwindow", "pydirectinput", "mss"):
        args += ["--exclude-module", mod]
    # OpenCV's own loader trips over itself inside a built Mac app; this
    # loads its compiled module directly instead (see the file)
    args += ["--runtime-hook", str(HERE / "pyi_rth_cv2.py")]
    args.append("ptcgl_gui.py")
    print(" ".join(args), "\n")
    return subprocess.run(args, cwd=HERE).returncode


def finish_plist(app, ver):
    plist = app / "Contents" / "Info.plist"
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info.update({
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": ver,
        "CFBundleVersion": ver,
        "LSMinimumSystemVersion": MIN_MACOS,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "Full Bench · fullbench.gg",
        # a menu-bar app: no Dock icon, and the only kind macOS lets put
        # the cover and pop-ups over a game played full screen
        "LSUIElement": True,
    })
    with open(plist, "wb") as f:
        plistlib.dump(info, f)


def sign(app):
    """Changing Info.plist breaks PyInstaller's signature, so sign again:
    ad hoc ("-"), or with a Developer ID if FULLBENCH_SIGN_ID is set."""
    ident = os.environ.get("FULLBENCH_SIGN_ID", "-")
    args = ["codesign", "--force", "--deep", "--sign", ident]
    if ident != "-":
        args += ["--options", "runtime", "--timestamp"]
    r = subprocess.run(args + [str(app)])
    if r.returncode == 0:
        subprocess.run(["codesign", "--verify", "--verbose=1", str(app)])
    return r.returncode


def dmg(app, ver):
    out = HERE / "dist" / f"FullBench-{ver}-mac.dmg"
    stage = HERE / "build" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copytree(app, stage / app.name, symlinks=True)
    (stage / "Applications").symlink_to("/Applications")
    if out.exists():
        out.unlink()
    r = subprocess.run(["hdiutil", "create", "-volname", APP_NAME,
                        "-srcfolder", str(stage), "-ov", "-format", "UDZO",
                        str(out)])
    return out if r.returncode == 0 else None


def smoke_test(app):
    """
    Start the built app just long enough to load OpenCV and the rest of
    what the screen watcher needs, with no window. A package that didn't
    make it into the app (or came in broken) shows up here, not later as
    "auto-copy off" after a match.
    """
    exe = app / "Contents" / "MacOS" / APP_NAME
    env = dict(os.environ, FULLBENCH_SELFCHECK="1")
    try:
        r = subprocess.run([str(exe)], env=env, capture_output=True,
                           text=True, timeout=90)
    except Exception as e:
        print(f"\ncouldn't start the built app to check it: {e}")
        return False
    lines = [l for l in (r.stdout + r.stderr).splitlines()
             if l.startswith("selfcheck")]
    msg = lines[-1] if lines else (r.stdout + r.stderr).strip()[-400:]
    print(f"\nchecking the built app: {msg}")
    if r.returncode == 0 and "selfcheck ok" in msg:
        return True
    print("\nTHE BUILT APP CAN'T LOAD WHAT IT NEEDS -- don't use this build.")
    if "cv2" in msg or "OpenCV" in msg:
        try:
            import cv2
            have = cv2.__version__
        except Exception:
            have = "?"
        print(f"OpenCV {have} isn't being packaged properly. Check that only")
        print("one OpenCV is installed (pip list | grep -i opencv: just")
        print("opencv-python-headless), update the build tools, and build")
        print("again:")
        print("   pip uninstall -y opencv-python opencv-contrib-python")
        print("   pip install -U pyinstaller pyinstaller-hooks-contrib")
    return False


def main():
    if not check():
        return 1
    ver = version()
    print(f"building {APP_NAME} {ver} for macOS ({os.uname().machine})\n")
    for d in ("build", "dist"):
        shutil.rmtree(HERE / d, ignore_errors=True)
    if pyinstaller(icon()) != 0:
        return 1
    app = HERE / "dist" / f"{APP_NAME}.app"
    if not app.exists():
        print("PyInstaller finished but there's no app in dist/")
        return 1
    finish_plist(app, ver)
    if sign(app) != 0:
        print("signing failed")
        return 1
    if not smoke_test(app):
        return 1
    out = dmg(app, ver)
    print(f"\nbuilt: {app}")
    if out:
        print(f"       {out}")
    print("\nOpen it from dist/, or drag it to Applications from the .dmg.")
    print("The first time you press Start tracking, macOS asks for Screen")
    print("Recording and Accessibility; Full Bench shows what each is for.")
    print("\nReplacing an earlier build? macOS may refuse it while still")
    print("showing it as allowed. Reset both first, then allow them again:")
    print(f"   tccutil reset ScreenCapture {BUNDLE_ID}")
    print(f"   tccutil reset Accessibility {BUNDLE_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
