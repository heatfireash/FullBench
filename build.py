"""
Build FullBench.exe (for the Mac app, see build_mac.py)

    pip install pyinstaller
    py build.py

Produces dist\\FullBench.exe -- a single file, no Python needed on the
target machine. The three button templates are bundled inside it.

Note: single-file exes unpack to a temp dir at launch, so the first start
takes a few seconds. Use --onedir below if you'd rather have a folder that
starts instantly.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ONEFILE = True          # set False for a faster-starting folder build

REQUIRED = ["ptcgl_gui.py", "ptcgl_tracker.py", "ptcgl_parse.py", "overlay.py",
            "autocopy.py", "ptcgl_stats.py",
            "settings.py", "game_watch.py", "version.py",
            "cloud.py", "archetypes.py", "archetypes.json", "cluster.py",
            "updater.py", "evolutions.py", "app_paths.py", "look.py",
            "battlelog_button.png", "copy_button.png", "continue_button.png",
            "icon.ico", "logo_small.png", "welcome.py",
            "gate_replays.png", "gate_stats.png", "gate_devices.png", "gate_meta.png"]


# ------------------------------------------------------------ signing
#
# FullBench.exe is signed with Azure Artifact Signing when signing.json
# sits next to this file:
#
#   {"Endpoint": "https://eus.codesigning.azure.net",
#    "CodeSigningAccountName": "<signing account name>",
#    "CertificateProfileName": "<certificate profile name>"}
#
# None of that is secret: what lets you sign is your Azure login (run
# "az login" once on this PC) and the Certificate Profile Signer role.
# Needs the Artifact Signing Client Tools:
#   winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
# If signtool or the dlib is somewhere unusual, add "SignTool" and "Dlib"
# with their full paths to signing.json.

TIMESTAMP = "http://timestamp.acs.microsoft.com"
# DefaultAzureCredential tries these before the Azure CLI login. On a
# home PC they all fail, some of them slowly, so skip straight to it.
SKIP_CREDENTIALS = ["EnvironmentCredential", "WorkloadIdentityCredential",
                    "ManagedIdentityCredential", "SharedTokenCacheCredential",
                    "VisualStudioCredential", "VisualStudioCodeCredential"]


def _find(name, extra=()):
    """The newest copy of `name` in the usual install places, x64 first.
    The signing client tools put the dlib in a folder of their own with
    no x64 in its path, so any copy that isn't x86 or ARM counts."""
    roots = [Path(p) for p in extra if p]
    for var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]))
    hits = []
    for root in roots:
        if root.is_file() and root.name.lower() == name.lower():
            return root
        for sub in ("Microsoft", "Windows Kits", "Microsoft SDKs"):
            base = root / sub
            if base.is_dir():
                try:
                    hits += list(base.rglob(name))
                except OSError:
                    pass
    def arch(h):
        parts = [p.lower() for p in h.parts]
        if "x64" in parts:
            return 2
        if any(p in ("x86", "arm", "arm64") for p in parts):
            return 0
        return 1
    hits = [h for h in hits if arch(h) > 0]
    if not hits:
        return None
    # x64 over no-architecture, then the newest version folder
    return sorted(hits, key=lambda h: (arch(h), str(h)))[-1]


def sign(exe):
    """Sign and check the exe. Returns True if it's signed, False if it
    wasn't (with the reason printed). A failed signing never leaves a
    half-signed file looking finished."""
    cfg_path = HERE / "signing.json"
    if not cfg_path.exists():
        print("\nnot signed: no signing.json (see the top of sign() in "
              "build.py)")
        return False
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    need = ("Endpoint", "CodeSigningAccountName", "CertificateProfileName")
    if any(not cfg.get(k) for k in need):
        print("\nnot signed: signing.json needs " + ", ".join(need))
        return False

    signtool = _find("signtool.exe", [cfg.get("SignTool")])
    dlib = _find("Azure.CodeSigning.Dlib.dll", [cfg.get("Dlib")])
    if not signtool or not dlib:
        print("\nnot signed: couldn't find "
              + " or ".join(n for n, p in (("signtool.exe", signtool),
                                           ("Azure.CodeSigning.Dlib.dll", dlib))
                            if not p))
        print("install the client tools:\n"
              "   winget install -e --id Microsoft.Azure.ArtifactSigningClientTools\n"
              "or put their full paths in signing.json as SignTool and Dlib")
        return False

    meta = {k: cfg[k] for k in need}
    meta["ExcludeCredentials"] = SKIP_CREDENTIALS
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "metadata.json"
        md.write_text(json.dumps(meta), encoding="utf-8")
        print(f"\nsigning with {signtool}")
        r = subprocess.run([str(signtool), "sign", "/v", "/fd", "SHA256",
                            "/tr", TIMESTAMP, "/td", "SHA256",
                            "/dlib", str(dlib), "/dmdf", str(md), str(exe)])
    if r.returncode != 0:
        print("\nSIGNING FAILED. The usual causes:\n"
              "  - not logged in: run  az login\n"
              "  - missing the Artifact Signing Certificate Profile Signer role\n"
              "  - the Endpoint's region doesn't match the account's (403)")
        return False
    v = subprocess.run([str(signtool), "verify", "/pa", str(exe)])
    if v.returncode != 0:
        print("\nSIGNED, BUT THE SIGNATURE DIDN'T CHECK OUT -- don't ship this")
        return False
    print("\nsigned and verified")
    return True


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
                "archetypes.json", "gate_replays.png", "gate_stats.png", "gate_devices.png", "gate_meta.png"):
        args += ["--add-data", f"{png}{sep}."]
    # our own modules, imported dynamically at runtime
    for mod in ("ptcgl_tracker", "ptcgl_parse", "autocopy", "ptcgl_stats",
                "overlay", "settings", "game_watch", "version",
                "cloud", "archetypes", "cluster", "updater", "evolutions",
                "app_paths", "look", "welcome"):
        args += ["--hidden-import", mod]
    # the Mac half of the app has no business in the Windows exe
    args += ["--exclude-module", "mac_platform"]
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
        if sys.platform == "win32":
            signed = sign(exe)
            if not signed and (HERE / "signing.json").exists():
                # signing was meant to happen: don't hand back an exe that
                # could be released unsigned by mistake
                bad = exe.with_name("FullBench-UNSIGNED.exe")
                exe.replace(bad)
                print(f"renamed to {bad.name} so it isn't released by mistake")
                return 1
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
