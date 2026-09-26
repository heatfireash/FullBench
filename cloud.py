"""
Cloud sync for Full Bench.

Sends this machine's matches to your account and pulls back anything
recorded on another machine, so two PCs converge on one history.

Sync is keyed on each battle log's hash, which makes it idempotent: the
same match uploaded twice is stored once, and a failed sync can simply be
retried. That also means the local database stays the source of truth —
the server never deletes anything and nothing is lost if it is
unreachable.

Signing in happens in a browser: the app shows a short code, opens the
site, and receives a device token once you approve the computer there.
The app never handles a password. Each computer gets its own token, so
signing one out leaves the others alone.

Only match statistics and your own decklists are sent. Player names,
yours and your opponents', are never uploaded.
"""

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path.home() / "ptcgl_matches.db"
TIMEOUT = 20

# Where Full Bench lives. Everyone uses the same server, so there is
# nothing for anyone to type. Override with FULLBENCH_SERVER if you are
# running your own, or testing against one.
DEFAULT_SERVER = os.environ.get("FULLBENCH_SERVER", "https://fullbench.gg")

# Columns sent to the server, mapped from the local names.
FIELDS = {
    "log_hash": "log_hash",
    "played_at": "captured_at",
    "deck_label": "deck_label",
    "deck_version": "deck_version",
    "opp_archetype": "opponent_archetype",
    "result": "result",
    "win_reason": "win_reason",
    "went_first": "went_first",
    "turns": "turns",
    "prizes_mine": "player_prizes_taken",
    "prizes_theirs": "opponent_prizes_taken",
    "mulligans_mine": "player_mulligans",
    "mulligans_theirs": "opponent_mulligans",
    "mull_draws_mine": "player_mulligan_draws",
    "mull_draws_theirs": "opponent_mulligan_draws",
}


def _col(row, name):
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def normalise_url(url):
    """
    Make a typed-in address usable.

    A browser quietly adds the scheme, so "127.0.0.1:8000" works there
    and fails here — urllib cannot parse it and raises, which surfaced as
    "could not reach the server" and sent people hunting firewalls.
    Also strips a trailing slash and any path that was pasted along with
    it.
    """
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme if parts.scheme in ("http", "https") else "http"
    netloc = parts.netloc or parts.path.split("/")[0]
    return f"{scheme}://{netloc}"


def _headers(token=None):
    h = {"Content-Type": "application/json",
         "User-Agent": "FullBench-sync/1"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _post(base_url, path, token, payload):
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=json.dumps(payload).encode(),
        method="POST", headers=_headers(token))
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _get(base_url, path, token):
    req = urllib.request.Request(base_url.rstrip("/") + path,
                                 headers=_headers(token))
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _err(e):
    """Turn a failure into something worth showing a person."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = json.loads(e.read().decode()).get("detail")
        except Exception:
            detail = None
        if detail:
            return str(detail)
        return {401: "wrong email or password",
                409: "that email is already registered",
                400: "check the email and password"}.get(
                    e.code, f"server error (HTTP {e.code})")
    if isinstance(e, urllib.error.URLError):
        reason = getattr(e, "reason", None)
        name = type(reason).__name__ if reason else ""
        text = str(reason) if reason else ""
        if "refused" in text.lower() or name == "ConnectionRefusedError":
            return ("nothing is listening there - is the server running, "
                    "and is the port right?")
        if "timed out" in text.lower() or name == "timeout":
            return ("the server did not answer - a firewall is the usual "
                    "cause")
        if "not known" in text.lower() or "resolve" in text.lower():
            return "that address does not resolve - check the spelling"
        if "certificate" in text.lower():
            return f"TLS problem: {text}"
        return f"could not reach the server ({text or name})"
    if isinstance(e, ValueError):
        return f"that address is not valid: {e}"
    return f"{type(e).__name__}: {e}"


def _device_name():
    import platform
    try:
        return platform.node() or "PC"
    except Exception:
        return "PC"


def start_browser_login(base_url, device=None):
    """
    Begin signing in through a browser.

    Returns (ok, info, message). `info` carries the code to display, the
    URL to open, and the secret the app polls with.

    Typing a password into a desktop window asks the person to trust that
    the window is what it claims to be. In a browser they can see the
    address bar, and the site's certificate, which is the whole point of
    doing it this way.
    """
    base_url = normalise_url(base_url)
    try:
        d = _post(base_url, "/v1/device/start", None,
                  {"device": device or _device_name()})
        return True, d, "waiting for you to approve it in the browser"
    except Exception as e:
        return False, None, _err(e)


def poll_browser_login(base_url, device_code):
    """
    Returns (state, token, message) where state is
    "pending", "approved", or "failed".
    """
    base_url = normalise_url(base_url)
    try:
        d = _post(base_url, "/v1/device/poll", None,
                  {"device_code": device_code})
    except urllib.error.HTTPError as e:
        if e.code == 410:
            return "failed", None, "the code expired - try again"
        return "failed", None, _err(e)
    except Exception as e:
        return "failed", None, _err(e)
    if d.get("status") == "approved":
        return "approved", d["token"], f"signed in as {d.get('email', '')}"
    return "pending", None, "waiting for approval"


def sign_out(base_url, token):
    try:
        _post(base_url, "/v1/logout", token, {})
    except Exception:
        pass
    return True, "signed out on this computer"


def check(base_url, token):
    """Confirm the stored token still works."""
    base_url = normalise_url(base_url)
    try:
        d = _get(base_url, "/v1/me", token)
        return True, f"signed in as {d['email']} ({d['matches']} matches stored)"
    except Exception as e:
        return False, _err(e)


def _log_payload(raw_path):
    """
    The battle log with player names replaced, plus a fingerprint.

    The server parses the log itself rather than trusting the numbers we
    send, so the text has to go. Names are swapped for PlayerA/PlayerB
    first -- the server never sees a handle. The fingerprint is what lets
    the server notice the same game arriving from both players.
    """
    try:
        from ptcgl_parse import parse, pseudonymise, match_fingerprint
        text = Path(raw_path).read_text(encoding="utf-8", errors="replace")
        d = parse(text)
        if not d.get("parse_ok"):
            return None, None
        return pseudonymise(text, d), match_fingerprint(d)
    except Exception:
        return None, None


def _local_payload(conn):
    # Matches flagged as not-a-game stay on this machine. Uploading them
    # would put instant concedes into everyone's global figures.
    try:
        rows = conn.execute(
            "SELECT * FROM matches WHERE COALESCE(excluded,'') = ''"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute("SELECT * FROM matches").fetchall()
    matches = []
    for r in rows:
        m = {out: _col(r, local) for out, local in FIELDS.items()}
        if not m["log_hash"]:
            continue
        raw = _col(r, "raw_path")
        if raw:
            m["log_text"], m["match_fp"] = _log_payload(raw)
        for key, local in (("my_cards", "player_cards"),
                           ("opp_cards", "opponent_cards")):
            try:
                m[key] = json.loads(_col(r, local) or "{}")
            except Exception:
                m[key] = {}
        matches.append(m)

    decks = []
    try:
        for d in conn.execute(
                "SELECT deck_label, version, created_at, list_text, total "
                "FROM deck_versions").fetchall():
            decks.append({"deck_label": d["deck_label"], "version": d["version"],
                          "created_at": d["created_at"],
                          "list_text": d["list_text"], "total": d["total"]})
    except sqlite3.OperationalError:
        pass
    return matches, decks


def _insert_remote(conn, matches, decks):
    """Write back matches this machine has never seen."""
    added = 0
    for m in matches:
        if conn.execute("SELECT 1 FROM matches WHERE log_hash=?",
                        (m["log_hash"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO matches (log_hash, captured_at, deck_label, "
            "deck_version, opponent_archetype, result, win_reason, "
            "went_first, turns, player_prizes_taken, opponent_prizes_taken, "
            "player_mulligans, opponent_mulligans, player_mulligan_draws, "
            "opponent_mulligan_draws, player_cards, opponent_cards) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (m["log_hash"], m.get("played_at"), m.get("deck_label"),
             m.get("deck_version"), m.get("opp_archetype"), m.get("result"),
             m.get("win_reason"), m.get("went_first"), m.get("turns"),
             m.get("prizes_mine"), m.get("prizes_theirs"),
             m.get("mulligans_mine"), m.get("mulligans_theirs"),
             m.get("mull_draws_mine"), m.get("mull_draws_theirs"),
             m.get("my_cards") if isinstance(m.get("my_cards"), str)
             else json.dumps(m.get("my_cards") or {}),
             m.get("opp_cards") if isinstance(m.get("opp_cards"), str)
             else json.dumps(m.get("opp_cards") or {})))
        added += 1

    for d in decks:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO deck_versions (deck_label, version, "
                "created_at, list_text, cards_json, total) "
                "VALUES (?,?,?,?,?,?)",
                (d["deck_label"], d["version"], d["created_at"],
                 d["list_text"], None, d.get("total")))
        except sqlite3.OperationalError:
            break
    conn.commit()
    return added


def sync(base_url, token, db_path=None):
    """
    Push local matches, pull remote ones. Returns (ok, message).

    Nothing is deleted on either side: this only ever adds.
    """
    base_url = normalise_url(base_url)
    path = Path(db_path or DB_PATH)
    if not path.exists():
        return False, "no local database yet - record a match first"

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        matches, decks = _local_payload(conn)
        payload = {"matches": matches, "decks": decks,
                   "have": [m["log_hash"] for m in matches]}
        try:
            res = _post(base_url, "/v1/sync", token, payload)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "signed out - sign in again"
            return False, f"sync failed: {_err(e)}"
        except Exception as e:
            return False, f"sync failed: {_err(e)}"

        pulled = _insert_remote(conn, res.get("matches", []),
                                res.get("decks", []))
        msg = (f"uploaded {res.get('added', 0)}, downloaded {pulled}, "
               f"{res.get('server_total', 0)} stored in your account")
        rej = res.get("rejected") or []
        if rej:
            reasons = {}
            for x in rej:
                reasons[x.get("reason", "?")] = reasons.get(x.get("reason", "?"), 0) + 1
            msg += " - " + ", ".join(f"{n} rejected ({why})"
                                     for why, n in reasons.items())
        return True, msg
    finally:
        conn.close()
