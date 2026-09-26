"""
Does PTCGL keep your decks on disk?

If it does, Full Bench could read the deck you actually selected rather
than working it out from the cards that happened to come out. That only
concerns your own deck, which you are entitled to know.

    py find_decks.py

Reports every file under the PTCGL folders that looks like it might hold
deck data, and shows enough of each one to tell.
"""

import json
import os
import re
from pathlib import Path

ROOTS = [
    Path(os.environ.get("LOCALAPPDATA", "")).parent / "LocalLow" / "pokemon",
    Path.home() / "AppData" / "LocalLow" / "pokemon",
    Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None,
    Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else None,
]

# Card names look like this in almost any representation PTCGL might use.
CARD_HINT = re.compile(
    r"\b(SVI|PAL|OBF|PAR|TEF|TWM|SFA|SCR|SSP|PRE|JTG|DRI|BLK|WHT|MEE|ME1|"
    r"ME2|SVE|CRZ|BRS|LOR|SIT)\b|\bdeckList\b|\bcardCount\b|\bdeckId\b",
    re.I)
DECK_WORDS = ("deck", "collection", "roster")


def looks_interesting(path):
    n = path.name.lower()
    return any(w in n for w in DECK_WORDS) or path.suffix.lower() == ".json"


def describe(path):
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"unreadable ({type(e).__name__})", None
    hit = bool(CARD_HINT.search(raw))
    try:
        data = json.loads(raw)
    except Exception:
        return ("contains card-like text" if hit else "not JSON"), None
    return ("JSON, contains card-like text" if hit else "JSON"), data


def keys_of(data, depth=0):
    if isinstance(data, dict):
        return list(data)[:12]
    if isinstance(data, list) and data:
        return [f"list[{len(data)}] of " + type(data[0]).__name__]
    return []


def main():
    seen = set()
    found = []
    for root in ROOTS:
        if not root or not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p in seen:
                continue
            if "bundleCache" in str(p) or "\\Unity\\" in str(p):
                continue
            if p.stat().st_size > 8_000_000:
                continue
            if not looks_interesting(p):
                continue
            seen.add(p)
            found.append(p)

    if not found:
        print("No candidate files found. Either PTCGL is not installed here,")
        print("or it keeps decks only on its servers.")
        return

    print(f"{len(found)} candidate file(s):\n")
    promising = []
    for p in sorted(found, key=lambda x: -x.stat().st_size)[:40]:
        note, data = describe(p)
        size = p.stat().st_size
        print(f"  {str(p).replace(str(Path.home()), '~'):<78}")
        print(f"      {size:>9,} bytes  {note}")
        if data is not None:
            k = keys_of(data)
            if k:
                print(f"      keys: {', '.join(str(x) for x in k)}")
        if "card-like" in note:
            promising.append(p)
        print()

    if promising:
        print("=" * 70)
        print("These contain text that looks like card or deck data:")
        for p in promising:
            print("   ", str(p).replace(str(Path.home()), "~"))
        print("\nOpen one and see whether it holds a full 60-card list. If it")
        print("does, Full Bench can read your selected deck directly.")
    else:
        print("=" * 70)
        print("Nothing holds card data. PTCGL keeps decks on its servers, so")
        print("paste your list into the app instead — Settings shows how, and")
        print("matches are then named from your own list rather than guessed.")


if __name__ == "__main__":
    main()
