"""
PTCGL stat tracker.

Watches the clipboard for Pokemon TCG Live battle logs, parses them,
and stores one row per match in SQLite.

Install:
    pip install pyperclip

Run:
    python ptcgl_tracker.py --me "YourPTCGLName"

Leave it running in the background. Every battle log that hits the
clipboard gets parsed and filed. Duplicates are ignored.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pyperclip

DB_PATH = Path.home() / "ptcgl_matches.db"
RAW_DIR = Path.home() / "ptcgl_logs"
REJECT_DIR = RAW_DIR / "rejected"

# ---------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY,
    log_hash        TEXT UNIQUE NOT NULL,
    captured_at     TEXT NOT NULL,
    player          TEXT,
    opponent        TEXT,
    result          TEXT,           -- win / loss / unknown
    win_reason      TEXT,           -- prizes / concede / deckout / unknown
    went_first      INTEGER,        -- 1 yes, 0 no, NULL unknown
    turns           INTEGER,
    player_prizes_taken   INTEGER,
    opponent_prizes_taken INTEGER,
    player_cards    TEXT,           -- json: {card: count_seen}
    opponent_cards  TEXT,
    deck_label      TEXT,           -- auto-detected; manual entry overrides
    opponent_archetype TEXT,        -- guessed from cards seen
    player_mulligans      INTEGER,
    opponent_mulligans    INTEGER,
    player_mulligan_draws   INTEGER,  -- cards you drew off their mulligans
    opponent_mulligan_draws INTEGER,
    excluded        TEXT,           -- why this match doesn't count, or NULL
    player_mons     TEXT,           -- {pokemon: damage} seen, for clustering
    opponent_mons   TEXT,
    deck_edited     INTEGER DEFAULT 0,  -- 1 = named by hand, don't overwrite
    player_moves    TEXT,           -- json: {pokemon: [attacks seen]}
    opponent_moves  TEXT,           -- used to identify which print was played
    player_damage   INTEGER,
    opponent_damage INTEGER,
    raw_path        TEXT
);
CREATE TABLE IF NOT EXISTS deck_versions (
    id          INTEGER PRIMARY KEY,
    deck_label  TEXT NOT NULL,
    version     INTEGER NOT NULL,       -- 1, 2, 3 ... per deck
    created_at  TEXT NOT NULL,
    list_text   TEXT NOT NULL,          -- exactly what was pasted
    cards_json  TEXT,                   -- {name: count}
    total       INTEGER,
    note        TEXT,
    UNIQUE(deck_label, version)
);
CREATE INDEX IF NOT EXISTS idx_dv ON deck_versions(deck_label, version);
CREATE INDEX IF NOT EXISTS idx_opponent ON matches(opponent);
CREATE INDEX IF NOT EXISTS idx_deck ON matches(deck_label);
"""


# Every column the current code expects, with its type. CREATE TABLE IF
# NOT EXISTS does nothing to a table that already exists, so a database
# made by an older build is missing whatever was added since. Rather than
# make people delete their match history, add what's missing on open.
EXPECTED_COLUMNS = {
    "log_hash": "TEXT", "captured_at": "TEXT",
    "player": "TEXT", "opponent": "TEXT",
    "result": "TEXT", "win_reason": "TEXT",
    "went_first": "INTEGER", "turns": "INTEGER",
    "player_prizes_taken": "INTEGER", "opponent_prizes_taken": "INTEGER",
    "player_cards": "TEXT", "opponent_cards": "TEXT",
    "deck_label": "TEXT", "opponent_archetype": "TEXT",
    "player_mulligans": "INTEGER", "opponent_mulligans": "INTEGER",
    "player_mulligan_draws": "INTEGER", "opponent_mulligan_draws": "INTEGER",
    "player_moves": "TEXT", "opponent_moves": "TEXT",
    "deck_edited": "INTEGER",
    "excluded": "TEXT",
    "player_mons": "TEXT",
    "opponent_mons": "TEXT",
    "deck_version": "INTEGER",   # which list was in use for this match
    "player_damage": "INTEGER", "opponent_damage": "INTEGER",
    "raw_path": "TEXT",
}


def migrate(conn, verbose=True):
    """Add any columns this version expects but the file doesn't have."""
    conn.executescript(SCHEMA)          # creates deck_versions if absent
    cur = conn.execute("PRAGMA table_info(matches)")
    have = {r[1] for r in cur.fetchall()}
    if not have:
        return []                      # fresh database, SCHEMA covered it
    added = []
    for col, typ in EXPECTED_COLUMNS.items():
        if col not in have:
            # ALTER TABLE ADD COLUMN is safe and cheap; existing rows get
            # NULL, which the stats layer already treats as "unknown".
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {typ}")
            added.append(col)
    if added:
        conn.commit()
        if verbose:
            print(f"[tracker] database upgraded: added {len(added)} column(s) "
                  f"({', '.join(added)})")
            print("[tracker] run  py ptcgl_stats.py --reparse  to fill them "
                  "in from your saved logs")
    return added


def open_db(verbose=True):
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    migrate(conn, verbose)
    conn.execute("PRAGMA user_version = 2")
    return conn


# ---------------------------------------------------------------- parse

from ptcgl_parse import (looks_like_battle_log, parse, guess_archetype,
                         validate)


# ------------------------------------------------------- deck matching

# Cards in almost every deck. They say nothing about which deck this is,
# so they are ignored when comparing.
GENERIC = {
    "Basic Metal Energy", "Basic Fire Energy", "Basic Water Energy",
    "Basic Grass Energy", "Basic Lightning Energy", "Basic Psychic Energy",
    "Basic Fighting Energy", "Basic Darkness Energy", "Basic Fairy Energy",
    "Ultra Ball", "Nest Ball", "Rare Candy", "Switch", "Super Rod",
    "Professor's Research", "Iono", "Boss's Orders", "Arven",
    "Earthen Vessel", "Night Stretcher", "Buddy-Buddy Poffin",
    "Poke Pad", "Pok\u00e9 Pad", "Pok\u00e9gear 3.0",
}

# A Pokemon identifies a deck far more strongly than a trainer does:
# two unrelated decks share Ultra Ball, they do not share Ceruledge ex.
W_POKEMON = 3.0
W_TRAINER = 1.0


def _weighted_signature(cards, moves=None, evolutions=None):
    """
    {card: weight} for the cards that actually distinguish this deck.

    Pokemon are identified by having attacked, evolved, been evolved
    into, or by the ex / Mega naming convention. Everything else that
    isn't a generic staple counts as a lower-weight trainer.
    """
    moves = moves or {}
    evolutions = evolutions or {}
    mons = set(moves) | set(evolutions)
    sig = {}
    for c in cards:
        if c in GENERIC or c.lower().startswith("basic "):
            continue
        is_mon = c in mons or " ex" in c or c.startswith("Mega ")
        sig[c] = W_POKEMON if is_mon else W_TRAINER
    for c in mons:
        if c not in GENERIC:
            sig[c] = W_POKEMON
    return sig


def _pools(conn, label_col, cards_col, moves_col):
    """Accumulated signature for every deck label already recorded."""
    out = {}
    try:
        rows = conn.execute(
            f"SELECT {label_col}, {cards_col}, {moves_col} FROM matches "
            f"WHERE {label_col} IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return out
    for label, cards, moves in rows:
        try:
            cd = json.loads(cards or "{}")
            md = json.loads(moves or "{}")
        except Exception:
            continue
        out.setdefault(label, {}).update(_weighted_signature(cd, md))
    return out


def similarity(sig, pool):
    """
    How much of this match's deck-defining cards appear in a known deck.

    Containment rather than Jaccard, because a short game may reveal 5
    cards out of a 20-card pool -- that is a strong match even though
    the sets are very different sizes.
    """
    if not sig or not pool:
        return 0.0
    shared = sum(w for c, w in sig.items() if c in pool)
    total = sum(sig.values())
    return shared / total if total else 0.0


def match_known_deck(conn, cards, moves, evolutions, *,
                     label_col="deck_label", cards_col="player_cards",
                     moves_col="player_moves",
                     min_score=0.55, min_shared=2):
    """
    Find the recorded deck this match most resembles.

    Returns (label, score, shared_count). label is None when nothing
    clears the bar -- a new deck should get its own name rather than be
    forced into an existing one.
    """
    sig = _weighted_signature(cards, moves, evolutions)
    if len(sig) < min_shared:
        return None, 0.0, 0
    best, best_score, best_shared = None, 0.0, 0
    for label, pool in _pools(conn, label_col, cards_col, moves_col).items():
        shared = sum(1 for c in sig if c in pool)
        if shared < min_shared:
            continue
        sc = similarity(sig, pool)
        if sc > best_score:
            best, best_score, best_shared = label, sc, shared
    if best_score >= min_score:
        return best, best_score, best_shared
    return None, best_score, best_shared


def _label_signatures(conn):
    """The pooled deck-defining cards behind each of your deck names."""
    pools = {}
    counts = {}
    try:
        rows = conn.execute(
            "SELECT deck_label, player_cards, player_moves FROM matches "
            "WHERE deck_label IS NOT NULL AND COALESCE(deck_edited,0)=0"
        ).fetchall()
    except sqlite3.OperationalError:
        return pools, counts
    for label, cards, moves in rows:
        try:
            cd = json.loads(cards or "{}")
            md = json.loads(moves or "{}")
        except Exception:
            continue
        sig = _weighted_signature(cd, md)
        if not sig:
            continue
        pools.setdefault(label, {}).update(sig)
        counts[label] = counts.get(label, 0) + 1
    return pools, counts


def consolidate_decks(conn, threshold=0.5, verbose=True):
    """
    Merge deck names that are obviously the same deck.

    Three mechanisms name decks -- this game's evidence, overlap with
    past games, and a saved decklist -- and they disagree, so the same
    sixty cards end up filed as "Mega Excadrill ex", "Mega Excadrill ex /
    Metang" and "Metagross / Metang". Each is defensible from the game it
    came from; together they are useless, because no two of them add up.

    So: compare the pooled cards behind each name, and where they overlap
    by `threshold` or more, treat them as one deck and keep the name with
    the most games behind it. Names set by hand are never touched, and
    neither is any name that comes from one of your saved decklists.
    """
    pools, counts = _label_signatures(conn)
    if len(pools) < 2:
        return 0

    try:
        protected = {r[0] for r in conn.execute(
            "SELECT DISTINCT deck_label FROM deck_versions")}
    except sqlite3.OperationalError:
        protected = set()

    # biggest first, so the best-evidenced name anchors each group
    order = sorted(pools, key=lambda l: (-counts.get(l, 0), l))
    groups = []
    for label in order:
        sig = pools[label]
        placed = False
        for g in groups:
            shared = sum(w for c, w in sig.items() if c in g["pool"])
            total = sum(sig.values()) or 1
            if shared / total >= threshold:
                g["labels"].append(label)
                g["pool"].update(sig)
                placed = True
                break
        if not placed:
            groups.append({"pool": dict(sig), "labels": [label]})

    renamed = 0
    for g in groups:
        if len(g["labels"]) < 2:
            continue
        # a name that came from one of your own decklists wins; failing
        # that, the one backed by the most games
        keep = next((l for l in g["labels"] if l in protected), None)
        if keep is None:
            keep = max(g["labels"], key=lambda l: counts.get(l, 0))
        for other in g["labels"]:
            if other == keep:
                continue
            n = conn.execute(
                "UPDATE matches SET deck_label=? WHERE deck_label=? "
                "AND COALESCE(deck_edited,0)=0", (keep, other)).rowcount
            if n and verbose:
                print(f"[tracker]   merged '{other}' into '{keep}' "
                      f"({n} match{'es' if n != 1 else ''}, "
                      f"same cards)")
            renamed += n
    if renamed:
        conn.commit()
    return renamed


def match_saved_decklist(conn, cards, min_score=0.6):
    """
    Work out which of your saved decklists this match was played with.

    This is the one case where the deck is not a guess. Your own lists
    are pasted in, so a match can be compared against them directly:
    the list containing the largest share of the cards actually seen is
    the deck that was played. No heuristics, no clustering, and it does
    not care which Pokemon happened to come out that game.

    Returns (deck_label, version, score) or (None, None, 0).
    """
    seen = {c for c in (cards or {}) if c not in GENERIC
            and not c.lower().startswith("basic ")}
    if len(seen) < 2:
        return None, None, 0.0
    try:
        rows = conn.execute(
            "SELECT deck_label, version, cards_json FROM deck_versions"
        ).fetchall()
    except sqlite3.OperationalError:
        return None, None, 0.0

    best = (None, None, 0.0)
    for label, version, cards_json in rows:
        try:
            listed = set(json.loads(cards_json or "{}"))
        except Exception:
            continue
        if not listed:
            continue
        score = len(seen & listed) / len(seen)
        if score > best[2]:
            best = (label, version, score)
    return best if best[2] >= min_score else (None, None, best[2])


# ------------------------------------------------------- deck versions

def current_version(conn, deck_label, at=None):
    """The newest version of this deck created at or before `at`."""
    if not deck_label:
        return None
    at = at or datetime.now().isoformat(timespec="seconds")
    try:
        r = conn.execute(
            "SELECT version FROM deck_versions WHERE deck_label=? "
            "AND created_at <= ? ORDER BY version DESC LIMIT 1",
            (deck_label, at)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r[0] if r else None


def add_deck_version(conn, deck_label, list_text, note=None):
    """
    Store a pasted decklist as the next version of a deck.

    Returns (version, parsed, message). An identical list is not stored
    again -- pasting the same thing twice should not invent a v2.
    """
    from decklist import parse_decklist, as_counts

    parsed = parse_decklist(list_text)
    if not parsed["ok"]:
        return None, parsed, "that doesn't look like a decklist"

    cards = as_counts(parsed)
    prev = conn.execute(
        "SELECT version, cards_json FROM deck_versions WHERE deck_label=? "
        "ORDER BY version DESC LIMIT 1", (deck_label,)).fetchone()
    if prev and prev[1]:
        try:
            if json.loads(prev[1]) == cards:
                return prev[0], parsed, (f"identical to v{prev[0]}, "
                                         f"nothing added")
        except Exception:
            pass

    version = (prev[0] + 1) if prev else 1
    conn.execute(
        "INSERT INTO deck_versions (deck_label, version, created_at, "
        "list_text, cards_json, total, note) VALUES (?,?,?,?,?,?,?)",
        (deck_label, version, datetime.now().isoformat(timespec="seconds"),
         list_text, json.dumps(cards, ensure_ascii=False, sort_keys=True),
         parsed["total"], note))

    # v1 is taken to describe every match played so far with this deck:
    # before the first list was pasted there was nothing else it could be.
    if version == 1:
        conn.execute("UPDATE matches SET deck_version=1 "
                     "WHERE deck_label=? AND deck_version IS NULL",
                     (deck_label,))
    conn.commit()
    return version, parsed, f"saved as v{version}"


def deck_versions(conn, deck_label=None):
    q = ("SELECT deck_label, version, created_at, total, note "
         "FROM deck_versions")
    args = ()
    if deck_label:
        q += " WHERE deck_label=?"
        args = (deck_label,)
    q += " ORDER BY deck_label, version"
    try:
        return conn.execute(q, args).fetchall()
    except sqlite3.OperationalError:
        return []


def deck_version_list(conn, deck_label, version):
    try:
        r = conn.execute(
            "SELECT list_text, cards_json, total, created_at FROM "
            "deck_versions WHERE deck_label=? AND version=?",
            (deck_label, version)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r


def relabel_from_clusters(conn, verbose=True):
    """
    Name every deck, yours and your opponents', from the clusters of
    Pokemon seen across your games.

    Runs after each match. Rows with a hand-set name are left alone, and
    so are rows already named from one of your saved decklists.
    """
    try:
        import cluster
    except ImportError:
        return 0
    total = 0
    for label_col, mons_col, protect in (
            ("deck_label", "player_mons", True),
            ("opponent_archetype", "opponent_mons", False)):
        try:
            rows = conn.execute(
                f"SELECT id, {label_col}, {mons_col}, "
                f"COALESCE(deck_edited,0) FROM matches").fetchall()
            listed = {r[0] for r in conn.execute(
                "SELECT DISTINCT deck_label FROM deck_versions")} \
                if protect else set()
        except sqlite3.OperationalError:
            continue
        sides = []
        for mid, label, mons, ed in rows:
            if protect and (ed or (label and label in listed)):
                continue
            try:
                d = json.loads(mons or "{}")
            except Exception:
                d = {}
            if d:
                sides.append((mid, d))
        if not sides:
            continue
        assignment, _ = cluster.build(sides)
        changed = 0
        for mid, name in assignment.items():
            cur = conn.execute(f"SELECT {label_col} FROM matches WHERE id=?",
                               (mid,)).fetchone()[0]
            if name and name != cur:
                conn.execute(f"UPDATE matches SET {label_col}=? WHERE id=?",
                             (name, mid))
                changed += 1
        if changed:
            conn.commit()
        total += changed
    if verbose and total > 1:
        print(f"[tracker]   renamed {total} deck name(s) to keep each deck "
              f"under one name")
    return total


# ---------------------------------------------------------------- store

def _opponent_label(conn, p):
    """Same treatment for the opponent's deck, so archetypes stay
    consistent between matches instead of drifting with whatever they
    happened to play this game."""
    try:
        import archetypes
        named, _, _ = archetypes.identify(p["opponent_cards"])
        if named:
            return named
    except Exception:
        pass
    # No cross-matching on the opponent side. Your own decks are a
    # handful of known lists, so overlap is a safe signal; opponents are
    # a stream of strangers' decks that share staples, and matching on
    # overlap merged genuinely different decks under one name. An
    # unrecognised opponent keeps its local guess and shows up under
    # --unclassified, which is the prompt to write a definition.
    return guess_archetype(p["opponent_cards"], p["opponent_moves"],
                           p["opponent_pokemon_damage"],
                           p["opponent_evolutions"])


def looks_like_rerun(conn, p, within_minutes=10):
    """
    Catch a match that is not byte-identical but is obviously the same
    game recorded twice.

    Hash matching handles the normal case. This covers the awkward one:
    the same match copied twice where the log text differs by a trailing
    newline or a re-rendered line, which would otherwise hash differently
    and slip through as a second record.
    """
    if not p.get("opponent"):
        return None
    cutoff = (datetime.now() - timedelta(minutes=within_minutes)).isoformat()
    try:
        rows = conn.execute(
            "SELECT id, captured_at, turns, result, player_prizes_taken, "
            "opponent_prizes_taken FROM matches WHERE captured_at >= ? "
            "ORDER BY id DESC LIMIT 5", (cutoff,)).fetchall()
    except sqlite3.OperationalError:
        return None
    for r in rows:
        if (r[2] == p["turns"] and r[3] == p["result"]
                and r[4] == p["player_prizes_taken"]
                and r[5] == p["opponent_prizes_taken"]):
            return r[0]
    return None


def relabel_from_clusters(conn, verbose=True):
    """
    Name every deck, yours and your opponents', from the clusters of
    Pokemon seen across your games.

    Runs after each match. Rows with a hand-set name are left alone, and
    so are rows already named from one of your saved decklists.
    """
    try:
        import cluster
    except ImportError:
        return 0
    total = 0
    for label_col, mons_col, protect in (
            ("deck_label", "player_mons", True),
            ("opponent_archetype", "opponent_mons", False)):
        try:
            rows = conn.execute(
                f"SELECT id, {label_col}, {mons_col}, "
                f"COALESCE(deck_edited,0) FROM matches").fetchall()
            listed = {r[0] for r in conn.execute(
                "SELECT DISTINCT deck_label FROM deck_versions")} \
                if protect else set()
        except sqlite3.OperationalError:
            continue
        sides = []
        for mid, label, mons, ed in rows:
            if protect and (ed or (label and label in listed)):
                continue
            try:
                d = json.loads(mons or "{}")
            except Exception:
                d = {}
            if d:
                sides.append((mid, d))
        if not sides:
            continue
        assignment, _ = cluster.build(sides)
        changed = 0
        for mid, name in assignment.items():
            cur = conn.execute(f"SELECT {label_col} FROM matches WHERE id=?",
                               (mid,)).fetchone()[0]
            if name and name != cur:
                conn.execute(f"UPDATE matches SET {label_col}=? WHERE id=?",
                             (name, mid))
                changed += 1
        if changed:
            conn.commit()
        total += changed
    if verbose and total > 1:
        print(f"[tracker]   renamed {total} deck name(s) to keep each deck "
              f"under one name")
    return total


# ---------------------------------------------------------------- store

def store(conn, text: str, me: str, deck_label: str | None,
          ignore_no_attack: bool = True) -> bool:
    # Exact duplicate: one indexed lookup on a UNIQUE column, so this
    # costs the same whether there are ten matches or ten thousand.
    h = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    cur = conn.execute("SELECT 1 FROM matches WHERE log_hash = ?", (h,))
    if cur.fetchone():
        return False

    RAW_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RAW_DIR / f"match_{stamp}_{h[:8]}.txt"
    raw_path.write_text(text, encoding="utf-8")

    # A partial paste, a log cut off before the result, or one whose
    # numbers don't add up is not recorded. The raw text is still saved
    # below the check so nothing is lost if the rule needs revisiting.
    ok, problems = validate(text)
    if not ok:
        print(f"[tracker]   not a complete battle log: "
              f"{'; '.join(problems[:2])}")
        REJECT_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (REJECT_DIR / f"rejected_{stamp}_{h[:8]}.txt").write_text(
            text, encoding="utf-8")
        return False

    p = parse(text, me)
    if not p.get("parse_ok"):
        print(f"  could not parse: {p.get('reason')}")
        return False

    row = {
        "player": p["player"],
        "opponent": p["opponent"],
        "result": p["result"],
        "win_reason": p["win_reason"],
        "went_first": None if p["went_first"] is None else int(p["went_first"]),
        "turns": p["turns"],
        "player_prizes_taken": p["player_prizes_taken"],
        "opponent_prizes_taken": p["opponent_prizes_taken"],
        "player_cards": json.dumps(p["player_cards"], ensure_ascii=False, sort_keys=True),
        "opponent_cards": json.dumps(p["opponent_cards"], ensure_ascii=False, sort_keys=True),
        "opponent_archetype": _opponent_label(conn, p),
        "player_moves": json.dumps(p["player_moves"], ensure_ascii=False),
        "opponent_moves": json.dumps(p["opponent_moves"], ensure_ascii=False),
        "player_mulligans": p["player_mulligans"],
        "opponent_mulligans": p["opponent_mulligans"],
        "player_mulligan_draws": p["player_mulligan_draws"],
        "opponent_mulligan_draws": p["opponent_mulligan_draws"],
        "player_damage": p["player_damage"],
        "opponent_damage": p["opponent_damage"],
    }
    row["log_hash"] = h
    row["captured_at"] = datetime.now().isoformat(timespec="seconds")
    # your deck is detected the same way the opponent's is; a typed label
    # is treated as an override, not a requirement
    # The deck's name is worked out from what was played, the same way
    # the website does it: matches are grouped by the Pokemon seen and
    # each group is named after the one doing the attacking. That means
    # nothing to type and the same name here as on the global page. A
    # saved decklist, if one matches, names it instead -- and a name set
    # by hand is never touched.
    try:
        import cluster
        row["player_mons"] = json.dumps(
            cluster.pokemon_from_parse(p, "mine"), ensure_ascii=False)
        row["opponent_mons"] = json.dumps(
            cluster.pokemon_from_parse(p, "theirs"), ensure_ascii=False)
    except Exception:
        row["player_mons"] = row["opponent_mons"] = "{}"

    from_list, list_version, list_score = match_saved_decklist(
        conn, p["player_cards"])
    if from_list:
        auto = from_list
        print(f"[tracker]   matched your saved list '{from_list}' "
              f"v{list_version} ({list_score:.0%} of cards seen)")
    else:
        # provisional: this game's own evidence. Replaced by the cluster
        # name right after the row is stored (see relabel_from_clusters)
        auto = guess_archetype(p["player_cards"], p["player_moves"],
                               p["player_pokemon_damage"],
                               p["player_evolutions"])
    row["deck_label"] = deck_label or auto
    # Which list was in use? The newest version of this deck recorded at
    # or before now. A list pasted later describes later games, not this
    # one, so versions are never applied retroactively.
    row["deck_version"] = (list_version if from_list
                           else current_version(conn, row["deck_label"]))

    # A game nobody attacked in is not a game. Someone conceded on sight
    # of the matchup, or misclicked into a match and left. Counting those
    # drags every win rate around without saying anything about how the
    # decks actually play.
    #
    # They are recorded and flagged rather than dropped: if this rule
    # ever misfires the match is still there, and the raw log always is.
    row["excluded"] = None
    if ignore_no_attack and not p.get("attacks"):
        row["excluded"] = "no attacks made"

    dup = looks_like_rerun(conn, p)
    if dup:
        print(f"[tracker]   looks like match {dup} recorded again "
              f"(same result, turns and prizes within 10 minutes) - skipped")
        return False
    row["raw_path"] = str(raw_path)

    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO matches ({cols}) VALUES ({marks})", tuple(row.values()))
    conn.commit()

    if row["excluded"]:
        print(f"[tracker] {row['captured_at'][11:16]}  ignored  "
              f"({row['excluded']}) - {row['turns']} turn(s) vs "
              f"{row['opponent_archetype'] or '?'}")
        return True

    # group every match by its Pokemon and name each group; this is what
    # keeps one deck under one name however each game happened to go
    relabel_from_clusters(conn)
    fixed = conn.execute("SELECT deck_label FROM matches WHERE log_hash=?",
                         (h,)).fetchone()
    if fixed and fixed[0]:
        row["deck_label"] = fixed[0]

    print(
        f"[tracker] {row['captured_at'][11:16]}  {str(row['result']):>7}  "
        f"{row['deck_label'] or '?'} vs {row['opponent_archetype'] or 'unknown'}  "
        f"turns={row['turns']}  first={row['went_first']}  "
        f"prizes={row['player_prizes_taken']}-{row['opponent_prizes_taken']}"
    )
    return True


# ---------------------------------------------------------------- main

def _import_clipboard_decklist(conn, text):
    """Auto-import a decklist copied from PTCGL."""
    try:
        from decklist import looks_like_decklist, parse_decklist, as_counts
    except ImportError:
        return
    if not looks_like_decklist(text):
        return
    parsed = parse_decklist(text)
    listed = set(as_counts(parsed))

    # which of your recorded decks is this the list for? compare against
    # the pooled cards behind each name, the same way matches are
    pools, counts = _label_signatures(conn)
    best, best_score = None, 0.0
    for label, pool in pools.items():
        # weighted, so the Pokemon decide: a list is the same deck if it
        # holds the Pokemon that have been played under that name, even
        # if a few trainers differ
        total = sum(pool.values()) or 1
        shared = sum(w for c, w in pool.items() if c in listed)
        score = shared / total
        if score > best_score:
            best, best_score = label, score

    if best and best_score >= 0.5:
        label = best
    else:
        # nothing recorded with it yet: name it after its headline card
        mons = [c for c in listed if " ex" in c or c.startswith("Mega ")]
        label = sorted(mons, key=lambda c: (not c.startswith("Mega "), c))[0] \
            if mons else "New deck"

    ver, _, msg = add_deck_version(conn, label, text)
    if ver:
        print(f"[tracker] decklist from clipboard -> '{label}' ({msg})")


def watch_clipboard(me=None, deck=None, poll=0.4, stop=None,
                    ignore_no_attack=True):
    """Poll the clipboard until `stop` (a threading.Event) is set."""
    conn = open_db()
    print(f"[tracker] watching clipboard. db={DB_PATH}")

    last = ""
    while stop is None or not stop.is_set():
        try:
            text = pyperclip.paste()
        except Exception:
            time.sleep(poll)
            continue

        if text and text != last:
            last = text
            if looks_like_battle_log(text):
                try:
                    if not store(conn, text, me, deck, ignore_no_attack):
                        print("[tracker]   already filed, skipped")
                except Exception as e:
                    print(f"[tracker]   parse/store failed: {e}", file=sys.stderr)
            else:
                # A decklist on the clipboard -- from PTCGL's own Copy
                # button -- is imported without any further step. It is
                # filed under the deck whose past games it matches, so a
                # list copied out of the game names that deck from then on.
                try:
                    _import_clipboard_decklist(conn, text)
                except Exception as e:
                    print(f"[tracker]   decklist import failed: {e}",
                          file=sys.stderr)

        time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default=None,
                    help="your PTCGL display name (auto-detected if omitted)")
    ap.add_argument("--deck", default=None, help="deck label for this session")
    ap.add_argument("--poll", type=float, default=0.4)
    args = ap.parse_args()
    print("ctrl-c to stop.\n")
    try:
        watch_clipboard(args.me, args.deck, args.poll)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
