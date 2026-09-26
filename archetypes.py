"""
Naming decks from a definition list.

The battle log shows only the cards that were actually played, so a deck
has to be recognised from a partial view — often four or five Pokemon out
of sixty cards, and sometimes almost nothing if the game ended early.

So definitions are built the way a player identifies a deck across the
table: one or two cards that give it away. A definition matches when
every card in `requires` was seen. `signals` do not gate the match, they
break ties between definitions that both fit.

This matters more than it looks. Local guessing produces a different
name on every machine — the same deck might be filed as "Mega Excadrill
ex / Metang" here, "Metang / Genesect ex" there, and "Drilbur" after a
short game. Nothing can be aggregated across users until everyone agrees
on the name, and that agreement has to live in a shared list rather than
in each client's heuristics.

The definitions are data, in archetypes.json, so the list can be updated
when a set drops without shipping new code.
"""

import json
import unicodedata
from pathlib import Path

import sys

HERE = Path(__file__).parent


def _defs_path():
    """
    Prefer a file beside the exe over the bundled one.

    That way the definitions can be updated without a rebuild — drop a
    new archetypes.json next to FullBench.exe and it wins.
    """
    beside = (Path(sys.executable).parent if getattr(sys, "frozen", False)
              else HERE) / "archetypes.json"
    if beside.exists():
        return beside
    return Path(getattr(sys, "_MEIPASS", HERE)) / "archetypes.json"


DEFS_PATH = _defs_path()

_cache = {"mtime": None, "defs": []}


def _norm(name):
    n = unicodedata.normalize("NFKD", name or "")
    n = n.encode("ascii", "ignore").decode().lower()
    return " ".join(n.split())


def load(path=None):
    """Read the definitions, re-reading if the file changed on disk."""
    p = Path(path) if path else DEFS_PATH
    if not p.exists():
        return []
    mtime = p.stat().st_mtime
    if _cache["mtime"] == mtime and not path:
        return _cache["defs"]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    defs = []
    for d in raw.get("archetypes", []):
        defs.append({
            "name": d["name"],
            "requires": [_norm(c) for c in d.get("requires", [])],
            "requires_any": [_norm(c) for c in d.get("requires_any", [])],
            "signals": [_norm(c) for c in d.get("signals", [])],
            "excludes": [_norm(c) for c in d.get("excludes", [])],
            "priority": d.get("priority", 0),
        })
    if not path:
        _cache.update(mtime=mtime, defs=defs)
    return defs


def identify(cards, defs=None):
    """
    Name a deck from the cards seen in play.

    Returns (name, confidence, why). confidence is:
      "certain"   one definition matched
      "likely"    several matched; the most specific one was taken
      None        nothing matched, so the caller should fall back

    A definition with more required cards wins over a looser one, since
    "Charizard ex + Pidgeot" is a more specific claim than "Charizard ex"
    on its own.
    """
    defs = defs if defs is not None else load()
    if not defs or not cards:
        return None, None, "no definitions"

    seen = {_norm(c) for c in cards}
    hits = []
    for d in defs:
        if not d["requires"] and not d["requires_any"]:
            continue
        if not all(r in seen for r in d["requires"]):
            continue
        # `requires_any` exists because a deck's headline Pokemon is not
        # always played. A Team Rocket's deck is still a Team Rocket's
        # deck in a game where Mewtwo never hit the board -- but the
        # supporter and the other owned Pokemon did. Any one of them
        # identifies it.
        any_hits = [r for r in d["requires_any"] if r in seen]
        if d["requires_any"] and not any_hits:
            continue
        if any(x in seen for x in d["excludes"]):
            continue
        sig = sum(1 for x in d["signals"] if x in seen)
        # a definition asking for more specific evidence outranks a
        # looser one; several `requires_any` hits beat a single one
        weight = len(d["requires"]) + min(len(any_hits), 3) * 0.5
        hits.append((weight, d["priority"], sig, d["name"]))

    if not hits:
        return None, None, "no definition matched"

    hits.sort(reverse=True)
    best = hits[0]
    if len(hits) == 1:
        return best[3], "certain", f"matched on {best[0]:g} signature card(s)"
    # several fit: the most specific wins, but say so
    others = ", ".join(h[3] for h in hits[1:3])
    return best[3], "likely", f"also fit: {others}"


def unmatched_summary(rows, defs=None):
    """
    Group unrecognised decks by the Pokemon seen, so it is obvious which
    definitions are worth writing next.

    `rows` is an iterable of (label, cards_dict).
    """
    defs = defs if defs is not None else load()
    buckets = {}
    for label, cards in rows:
        name, conf, _ = identify(cards, defs)
        if name:
            continue
        mons = tuple(sorted(
            c for c in cards
            if " ex" in c or c.startswith("Mega ") or c.startswith("Iron ")
            or c.endswith(" V") or c.endswith(" VMAX")))
        key = mons[:4] or (label or "unknown",)
        b = buckets.setdefault(key, {"count": 0, "labels": set()})
        b["count"] += 1
        if label:
            b["labels"].add(label)
    return sorted(buckets.items(), key=lambda kv: -kv[1]["count"])


def names(defs=None):
    return sorted(d["name"] for d in (defs if defs is not None else load()))
