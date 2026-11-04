"""
Where the app keeps its own small files: settings.json,
calibration.json, and any re-cropped button picture or archetypes.json
a user puts there to override the bundled one.

  Windows app   beside FullBench.exe, as always
  Mac app       ~/Library/Application Support/Full Bench -- a Mac app
                can't write inside itself (it's signed, and macOS may
                run it from a read-only copy until it's moved to
                Applications)
  from source   beside the scripts

The match database and raw logs aren't here: they stay in the home
folder on both systems (~/ptcgl_matches.db, ~/ptcgl_logs).
"""

import sys
from pathlib import Path


def user_dir():
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            d = Path.home() / "Library" / "Application Support" / "Full Bench"
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            return d
        return Path(sys.executable).parent
    return Path(__file__).parent
