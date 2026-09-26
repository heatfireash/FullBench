"""
Parse a decklist copied out of Pokemon TCG Live.

PTCGL's export looks like this:

    Pokemon: 9
    2 Drilbur PAL 55
    1 Genesect ex MEE 103

    Trainer: 33
    4 Arven OBF 186

    Energy: 18
    9 Basic {M} Energy SVE 8

    Total Cards: 60

Quirks worth knowing, all handled here:
  * the Pokemon header may be spelled "Pokemon" or "Pokemon" with the
    accent, and some exports use "Pokemon:" with no count
  * energy lines carry a type in braces -- "Basic {M} Energy"
  * set code and collector number are optional; older exports and hand
    written lists often omit them
  * section headers can be missing entirely if someone pasted only part
    of the list, so a line is parsed on its own merits rather than
    relying on which section it sits under
"""

import re
import unicodedata

SECTION_RE = re.compile(
    r"^\s*(?P<name>Pok[eé]mon|Trainer|Energy)\s*:?\s*(?P<n>\d+)?\s*$",
    re.I)
TOTAL_RE = re.compile(r"^\s*Total\s+Cards?\s*:?\s*(?P<n>\d+)\s*$", re.I)
# "4 Arven OBF 186"  /  "2 Drilbur PAL 55"  /  "9 Basic {M} Energy SVE 8"
# /  "3 Ultra Ball"  (no set/number)
CARD_RE = re.compile(
    r"^\s*(?P<count>\d+)\s+"
    r"(?P<name>.+?)"
    r"(?:\s+(?P<set>[A-Z][A-Z0-9-]{1,5})\s+(?P<num>\d+[a-z]?))?"
    r"\s*$")


def _clean(text):
    return unicodedata.normalize("NFC", text or "").replace("\r\n", "\n")


def parse_decklist(text):
    """
    Returns a dict:
        ok          whether this looks like a decklist at all
        cards       [{count, name, set, number, section}]
        counts      {"Pokemon": n, "Trainer": n, "Energy": n}
        total       total cards found
        declared    total the list claims, if it says
        problems    list of human-readable warnings (never fatal)
    """
    t = _clean(text)
    if not t.strip():
        return {"ok": False, "cards": [], "counts": {}, "total": 0,
                "declared": None, "problems": ["empty"]}

    section = None
    cards = []
    counts = {}
    declared = None
    problems = []

    for raw in t.split("\n"):
        line = raw.strip()
        if not line:
            continue

        m = TOTAL_RE.match(line)
        if m:
            declared = int(m.group("n"))
            continue

        m = SECTION_RE.match(line)
        if m:
            name = m.group("name")
            section = ("Pokemon" if name.lower().startswith("pok")
                       else name.title())
            if m.group("n"):
                counts[section] = int(m.group("n"))
            continue

        m = CARD_RE.match(line)
        if not m:
            problems.append(f"could not read: {line[:60]}")
            continue

        name = m.group("name").strip()
        # an energy line names itself, so the section isn't needed
        sec = section
        if sec is None:
            sec = "Energy" if re.search(r"\bEnergy\b", name) else "Unknown"
        cards.append({
            "count": int(m.group("count")),
            "name": name,
            "set": m.group("set"),
            "number": m.group("num"),
            "section": sec,
        })

    total = sum(c["count"] for c in cards)
    if declared is not None and declared != total:
        problems.append(f"list says {declared} cards, found {total}")
    for sec, claimed in counts.items():
        got = sum(c["count"] for c in cards if c["section"] == sec)
        if got != claimed:
            problems.append(f"{sec}: header says {claimed}, found {got}")

    return {
        "ok": len(cards) >= 5,
        "cards": cards,
        "counts": counts,
        "total": total,
        "declared": declared,
        "problems": problems,
    }


def looks_like_decklist(text):
    """Cheap check, so a decklist is never mistaken for a battle log."""
    if not text or len(text) < 40:
        return False
    t = _clean(text)
    if "Setup" in t and "'s Turn" in t:
        return False                       # that's a battle log
    d = parse_decklist(t)
    return d["ok"] and d["total"] >= 20


def as_counts(parsed):
    """{name: count}, for comparing a list against the cards seen in play."""
    out = {}
    for c in parsed["cards"]:
        out[c["name"]] = out.get(c["name"], 0) + c["count"]
    return out


def format_list(parsed):
    """Tidy text for display, grouped by section."""
    order = ["Pokemon", "Trainer", "Energy", "Unknown"]
    lines = []
    for sec in order:
        rows = [c for c in parsed["cards"] if c["section"] == sec]
        if not rows:
            continue
        n = sum(c["count"] for c in rows)
        lines.append(f"{sec}: {n}")
        for c in sorted(rows, key=lambda c: (-c["count"], c["name"])):
            tail = ""
            if c["set"] and c["number"]:
                tail = f"  {c['set']} {c['number']}"
            lines.append(f"  {c['count']}x {c['name']}{tail}")
        lines.append("")
    lines.append(f"Total: {parsed['total']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    d = parse_decklist(sys.stdin.read())
    print(json.dumps({k: v for k, v in d.items() if k != "cards"}, indent=2))
    print(format_list(d))
