"""
Query and maintain the PTCGL match database.

    py ptcgl_stats.py                 overall summary
    py ptcgl_stats.py --decks         win rate by your deck label
    py ptcgl_stats.py --matchups      win rate vs opponent archetype
    py ptcgl_stats.py --recent 20     last N matches
    py ptcgl_stats.py --unparsed      rows with missing fields
    py ptcgl_stats.py --reparse       rebuild every row from saved raw logs
    py ptcgl_stats.py --export csv    dump to ptcgl_matches.csv

--reparse matters: the parser will keep improving as more log variants
turn up (concessions, deckouts, ties, non-English clients). Because the
raw text is kept, every past match can be re-derived rather than lost.
"""

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from ptcgl_parse import parse, guess_archetype

DB_PATH = Path.home() / "ptcgl_matches.db"


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        from ptcgl_tracker import migrate
        migrate(c)
    except Exception:
        pass
    return c


def _rate(w, total):
    return f"{w}/{total}  {100.0 * w / total:5.1f}%" if total else "  no data"


NOT_EXCLUDED = "COALESCE(excluded,'') = ''"


def summary(c):
    rows = c.execute(f"SELECT * FROM matches WHERE {NOT_EXCLUDED}").fetchall()
    ign = c.execute("SELECT COUNT(*) n FROM matches WHERE "
                    "COALESCE(excluded,'') <> ''").fetchone()["n"]
    if ign:
        print(f"({ign} match(es) ignored - no attacks made)\n")
    if not rows:
        print("no matches recorded yet.")
        return
    n = len(rows)
    wins = sum(1 for r in rows if r["result"] == "win")
    losses = sum(1 for r in rows if r["result"] == "loss")
    unknown = n - wins - losses

    print(f"matches recorded : {n}")
    print(f"record           : {_rate(wins, wins + losses)}")
    if unknown:
        print(f"  ({unknown} with an undetermined result -- see --unparsed)")

    # play / draw split: the stat most likely to actually change decisions
    for label, val in (("on the play", 1), ("on the draw", 0)):
        sub = [r for r in rows if r["went_first"] == val
               and r["result"] in ("win", "loss")]
        w = sum(1 for r in sub if r["result"] == "win")
        print(f"{label:17}: {_rate(w, len(sub))}")

    turns = [r["turns"] for r in rows if r["turns"]]
    if turns:
        print(f"median turns     : {sorted(turns)[len(turns) // 2]}")

    pz = [(r["player_prizes_taken"], r["opponent_prizes_taken"]) for r in rows
          if r["player_prizes_taken"] is not None
          and r["opponent_prizes_taken"] is not None]
    if pz:
        avg = sum(a - b for a, b in pz) / len(pz)
        print(f"avg prize diff   : {avg:+.2f}")


def by_column(c, col, title):
    rows = c.execute(
        f"SELECT {col} AS k, result FROM matches "
        f"WHERE {NOT_EXCLUDED} AND result IN ('win','loss')").fetchall()
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        k = r["k"] or "(unlabelled)"
        agg[k][0] += 1
        if r["result"] == "win":
            agg[k][1] += 1
    if not agg:
        print("no decided matches yet.")
        return
    print(f"{title:<32}{'record':>16}")
    print("-" * 48)
    for k, (total, w) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        print(f"{str(k)[:31]:<32}{_rate(w, total):>16}")


def recent(c, n):
    rows = c.execute(
        f"SELECT captured_at, result, opponent, opponent_archetype, turns, "
        f"went_first, player_prizes_taken, opponent_prizes_taken "
        f"FROM matches WHERE {NOT_EXCLUDED} ORDER BY id DESC LIMIT ?",
        (n,)).fetchall()
    for r in rows:
        first = {1: "play", 0: "draw"}.get(r["went_first"], "  ? ")
        print(f"{r['captured_at'][:16]}  {str(r['result'] or '?'):>7}  "
              f"{first}  T{str(r['turns'] or '?'):>2}  "
              f"{r['player_prizes_taken']}-{r['opponent_prizes_taken']}  "
              f"vs {r['opponent'] or '?'} "
              f"({r['opponent_archetype'] or 'unknown'})")


def unparsed(c):
    rows = c.execute(
        "SELECT id, captured_at, raw_path, result, went_first, turns "
        "FROM matches WHERE result IS NULL OR went_first IS NULL "
        "OR turns IS NULL OR opponent IS NULL").fetchall()
    if not rows:
        print("every row parsed cleanly.")
        return
    print(f"{len(rows)} row(s) with gaps -- these are the log variants the")
    print("parser does not handle yet. Worth sending one to improve it.\n")
    for r in rows:
        missing = [k for k in ("result", "went_first", "turns") if r[k] is None]
        print(f"  id={r['id']}  {r['captured_at'][:16]}  "
              f"missing: {', '.join(missing)}")
        print(f"    {r['raw_path']}")


def _mons(d, side):
    try:
        import cluster
        return cluster.pokemon_from_parse(d, side)
    except Exception:
        return {}


def _name(cards, fallback):
    """Definition first, local guess second."""
    try:
        import archetypes
        named, _, _ = archetypes.identify(cards)
        return named or fallback
    except Exception:
        return fallback


def unclassified(c):
    """
    Which decks you meet that archetypes.json does not name yet.

    Grouped by the headline Pokemon seen, most common first, so the
    definitions worth writing next are obvious.
    """
    try:
        import archetypes
    except ImportError:
        print("archetypes.py not found")
        return
    defs = archetypes.load()
    if not defs:
        print("no definitions loaded - is archetypes.json present?")
        return

    rows = []
    for r in c.execute("SELECT deck_label, player_cards, opponent_archetype, "
                       "opponent_cards FROM matches").fetchall():
        for label, col in ((r["deck_label"], r["player_cards"]),
                           (r["opponent_archetype"], r["opponent_cards"])):
            try:
                rows.append((label, json.loads(col or "{}")))
            except Exception:
                pass

    buckets = archetypes.unmatched_summary(rows, defs)
    if not buckets:
        print(f"every deck matched a definition ({len(defs)} loaded).")
        return
    print(f"{len(buckets)} unrecognised deck(s). Add these to "
          f"archetypes.json:\n")
    for mons, info in buckets[:25]:
        seen = ", ".join(mons) if mons else "(no notable Pokemon seen)"
        print(f"  {info['count']:>3}x  {seen}")
        if info["labels"]:
            print(f"        currently filed as: "
                  f"{', '.join(sorted(info['labels'])[:3])}")
    print("\nAfter editing archetypes.json, run --reparse to apply it "
          "to matches already recorded.")


def reparse(c):
    """
    Rebuild every row from its saved log.

    Two passes: the first re-derives each match on its own, the second
    lets the deck matcher consolidate names now that every match is
    up to date -- a deck named badly from a short game gets folded into
    the properly named one.
    """
    rows = c.execute("SELECT id, raw_path, player FROM matches").fetchall()
    changed = missing = 0
    for r in rows:
        p = Path(r["raw_path"]) if r["raw_path"] else None
        if not p or not p.exists():
            missing += 1
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        d = parse(text, r["player"])
        if not d.get("parse_ok"):
            continue
        c.execute(
            "UPDATE matches SET player=?, opponent=?, result=?, win_reason=?, "
            "went_first=?, turns=?, player_prizes_taken=?, "
            "opponent_prizes_taken=?, player_cards=?, opponent_cards=?, "
            "opponent_archetype=?, deck_label=CASE WHEN deck_edited=1 THEN deck_label ELSE ? END, " 
            "player_moves=?, opponent_moves=?, "
            "player_mulligans=?, opponent_mulligans=?, "
            "player_mulligan_draws=?, opponent_mulligan_draws=?, "
            "player_damage=?, opponent_damage=?, "
            "player_mons=?, opponent_mons=? "
            "WHERE id=?",
            (d["player"], d["opponent"], d["result"], d["win_reason"],
             None if d["went_first"] is None else int(d["went_first"]),
             d["turns"], d["player_prizes_taken"], d["opponent_prizes_taken"],
             json.dumps(d["player_cards"], ensure_ascii=False, sort_keys=True),
             json.dumps(d["opponent_cards"], ensure_ascii=False, sort_keys=True),
             _name(d["opponent_cards"],
                   guess_archetype(d["opponent_cards"], d["opponent_moves"],
                                   d["opponent_pokemon_damage"],
                                   d["opponent_evolutions"],
                                   d.get("opponent_ability_uses"))),
             _name(d["player_cards"],
                   guess_archetype(d["player_cards"], d["player_moves"],
                                   d["player_pokemon_damage"],
                                   d["player_evolutions"],
                                   d.get("player_ability_uses"))),
             json.dumps(d["player_moves"], ensure_ascii=False),
             json.dumps(d["opponent_moves"], ensure_ascii=False),
             d["player_mulligans"], d["opponent_mulligans"],
             d["player_mulligan_draws"], d["opponent_mulligan_draws"],
             d["player_damage"], d["opponent_damage"],
             json.dumps(_mons(d, "mine")), json.dumps(_mons(d, "theirs")),
             r["id"]))
        changed += 1
    c.commit()

    # second pass: name every deck from the clusters of Pokemon seen,
    # now that every match has been re-derived
    try:
        from ptcgl_tracker import relabel_from_clusters
        n = relabel_from_clusters(c, verbose=False)
        if n:
            print(f"renamed {n} deck name(s) from clustering")
    except Exception as e:
        print(f"(clustering skipped: {e})")

    print(f"re-parsed {changed} row(s)"
          + (f", {missing} raw log(s) missing from disk" if missing else ""))


def export_csv(c):
    rows = c.execute("SELECT * FROM matches ORDER BY id").fetchall()
    if not rows:
        print("nothing to export.")
        return
    out = Path.home() / "ptcgl_matches.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys())
        for r in rows:
            w.writerow(list(r))
    print(f"wrote {len(rows)} row(s) -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", action="store_true")
    ap.add_argument("--matchups", action="store_true")
    ap.add_argument("--recent", type=int, metavar="N")
    ap.add_argument("--unparsed", action="store_true")
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--unclassified", action="store_true",
                    help="decks with no archetype definition yet")
    ap.add_argument("--merge-decks", action="store_true",
                    help="re-run deck naming from clusters of Pokemon seen")
    ap.add_argument("--export", choices=["csv"])
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"no database at {DB_PATH} -- run the tracker first.")
        return

    c = conn()
    if args.merge_decks:
        from ptcgl_tracker import relabel_from_clusters
        before = {r["deck_label"] for r in
                  c.execute("SELECT DISTINCT deck_label FROM matches")}
        n = relabel_from_clusters(c, verbose=False)
        after = {r["deck_label"] for r in
                 c.execute("SELECT DISTINCT deck_label FROM matches")}
        print(f"\n{len(before)} deck name(s) -> {len(after)}, "
              f"{n} name(s) changed")
    elif args.reparse:
        reparse(c)
    elif args.decks:
        by_column(c, "deck_label", "your deck")
    elif args.matchups:
        by_column(c, "opponent_archetype", "vs archetype")
    elif args.recent:
        recent(c, args.recent)
    elif args.unclassified:
        unclassified(c)
    elif args.unparsed:
        unparsed(c)
    elif args.export:
        export_csv(c)
    else:
        summary(c)


if __name__ == "__main__":
    main()
