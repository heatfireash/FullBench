"""
Updating the app from inside the app.

The update used to mean opening the download page. A file a browser
downloads is marked as coming from the internet, and Windows SmartScreen
checks every marked exe it's asked to run -- so everyone saw the "Windows
protected your PC" warning again on every update. The app fetching the
new version itself leaves no such mark: only a first install, from the
website, goes past SmartScreen.

How an update goes:

  1. download the new exe next to the current one, as a .part file
  2. check it: exactly the size the server listed, and the same SHA-256.
     Anything else -- a cut-off download, a proxy mangling it -- is
     thrown away and nothing is touched
  3. rename the running exe to FullBench.old.exe. Windows won't let a
     running exe be deleted or overwritten, but it will let it be renamed
  4. move the new one into the old one's place, same name, same folder --
     so Start menu shortcuts and pinned taskbar icons keep working
  5. start it, and close this one
  6. the new version deletes FullBench.old.exe when it starts

If step 4 or 5 fails, step 3 is undone, so there's always a working
FullBench.exe. Anything that can't be done this way -- running from
source, a folder Windows won't let the app write to -- falls back to the
download page, as before.
"""

import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

CHUNK = 256 * 1024


class UpdateError(Exception):
    pass


def _exe():
    return Path(sys.executable)


def can_self_update():
    """(True, "") or (False, why not)."""
    if not getattr(sys, "frozen", False):
        return False, "running from source"
    if sys.platform != "win32":
        return False, "only on Windows"
    folder = _exe().parent
    probe = folder / ".fullbench-write-test"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False, f"can't write to {folder}"
    return True, ""


def _old_path():
    exe = _exe()
    return exe.with_name(exe.stem + ".old" + exe.suffix)


def cleanup_old():
    """
    Delete what the last update left behind: the previous exe, and any
    half-finished download. Retries for a few seconds in the background,
    because right after an update the old process may still be closing
    and Windows won't delete a file that's in use.
    """
    if not getattr(sys, "frozen", False):
        return

    def run():
        folder = _exe().parent
        targets = [_old_path()] + list(folder.glob(".FullBench-*.part"))
        for _ in range(20):
            targets = [t for t in targets if t.exists()]
            if not targets:
                return
            for t in targets:
                try:
                    t.unlink()
                except OSError:
                    pass
            time.sleep(0.5)

    threading.Thread(target=run, daemon=True).start()


def download(url, sha256, size, version, progress=None, cancel=None):
    """
    Fetch the new exe beside the current one and check it. Returns its
    path. progress(done_bytes, total_bytes) is called as it goes, from
    this thread. Raises UpdateError with a readable reason on any problem,
    after removing the partial file.
    """
    if not url or not sha256:
        raise UpdateError("the server didn't say which file to fetch")
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1")
            or url.startswith("http://localhost")):
        raise UpdateError("refusing to download an update without https")
    part = _exe().parent / f".FullBench-{version}.part"
    h = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "FullBench-updater"})
        with urllib.request.urlopen(req, timeout=30) as r, \
                open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or size or 0)
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("cancelled")
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if size and done != size:
            raise UpdateError(f"download was cut short ({done:,} of "
                              f"{size:,} bytes)")
        if h.hexdigest().lower() != sha256.lower():
            raise UpdateError("the downloaded file didn't match - "
                              "nothing was changed")
        return part
    except UpdateError:
        _discard(part)
        raise
    except Exception as e:
        _discard(part)
        raise UpdateError(f"download failed: {e}")


def _discard(p):
    try:
        p.unlink()
    except OSError:
        pass


def _clean_env():
    """
    The environment for the new exe.

    A one-file PyInstaller app unpacks itself to a temp folder and points
    some environment variables at it (Tcl/Tk's library among them). A
    child started with those would try to use this process's temp folder,
    which is deleted the moment this process closes -- and the new
    version would fail to start. So they're left out, and PyInstaller is
    told to start fresh.
    """
    env = dict(os.environ)
    mine = getattr(sys, "_MEIPASS", None)
    for k in list(env):
        if k.startswith("_PYI_") or k == "_MEIPASS2" or (
                mine and mine in env[k]):
            env.pop(k, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def install_and_restart(new_file):
    """
    Put the downloaded exe in place of this one and start it. The caller
    closes the app straight after this returns. Raises UpdateError if it
    couldn't -- and in that case the current exe is still where it was.
    """
    exe, old = _exe(), _old_path()
    if old.exists():
        try:
            old.unlink()
        except OSError:
            raise UpdateError(f"can't remove {old.name} from the last update")
    try:
        os.replace(exe, old)                 # the running exe, set aside
    except OSError as e:
        _discard(Path(new_file))
        raise UpdateError(f"couldn't move the current version aside: {e}")
    try:
        os.replace(new_file, exe)
        flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS, NEW_GROUP
        subprocess.Popen([str(exe), "--updated"], cwd=str(exe.parent),
                         env=_clean_env(), creationflags=flags,
                         close_fds=True)
    except Exception as e:
        # put everything back as it was
        try:
            if exe.exists():
                os.replace(exe, Path(new_file))
            os.replace(old, exe)
        except OSError:
            pass
        _discard(Path(new_file))
        raise UpdateError(f"couldn't start the new version: {e}")
