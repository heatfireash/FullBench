"""
Parser for Pokemon TCG Live battle logs.

Written against real log output. Notable format details that are easy
to get wrong:

  * Turn headers are a bare "Name's Turn" line. There is no turn number.
  * The log mixes straight (') and curly (U+2019) apostrophes -- attack
    lines use curly, turn headers use straight. Every name pattern has
    to accept both or half the matches silently vanish.
  * "took a Prize card" (singular, no digit) and "took N Prize cards"
    are both used.
  * Player names can contain digits and apostrophes, so patterns are
    anchored on surrounding literal text, never on a name charset.
  * Card names contain apostrophes and accents (Team Rocket's Petrel,
    Pokegear 3.0 with an accented e).
"""

import json
import re
import unicodedata

AP = "['\u2019]"          # straight or curly apostrophe


# Some cards come through with the game's internal card code in front:
# "(mebsp_33) Mega Lucario ex", "(me1_75) Solrock", "(sv6-5_84)
# Fezandipiti ex", "(me1_73_ph) Hariyama", "(sv8-5_36_mph) Dusclops" -- it
# looks like the game does this when a deck has two printings of the same
# card. The code isn't part of the name, and left
# in, it made "(mebsp_33) Mega Lucario ex" a different deck from "Mega
# Lucario ex", with no sprite.
_CARD_CODE_RE = re.compile(
    r"\([a-z0-9]+(?:-[a-z0-9]+)*_\d+[a-z]?(?:_[a-z0-9]+)*\)\s*", re.I)


def _norm(text: str) -> str:
    """Normalise unicode but keep the original apostrophe distinction,
    and drop the game's card codes from in front of card names."""
    t = unicodedata.normalize("NFC", text.replace("\r\n", "\n"))
    return _CARD_CODE_RE.sub("", t)


# ------------------------------------------------------------ structure

TURN_RE = re.compile(rf"^(?P<who>.+?){AP}s Turn\s*$", re.M)
SETUP_RE = re.compile(r"^Setup\s*$", re.M)
COIN_WIN_RE = re.compile(r"^(?P<who>.+?) won the coin toss\.", re.M)
GO_FIRST_RE = re.compile(r"^(?P<who>.+?) decided to go (?P<order>first|second)\.", re.M)
OPENING_RE = re.compile(r"^(?P<who>.+?) drew 7 cards for the opening hand\.", re.M)


def looks_like_battle_log(text: str) -> bool:
    """Structural check, so a random copied paragraph is never filed."""
    if not text or len(text) < 300:
        return False
    t = _norm(text)
    return bool(SETUP_RE.search(t)) and len(TURN_RE.findall(t)) >= 2


def match_fingerprint(parsed):
    """
    An identifier both players' clients compute identically.

    Each player's log is written from their own perspective -- their
    draws named, the opponent's hidden -- so the two texts differ and so
    do their hashes. If both use the app, the same game arrives twice and
    would be counted twice in any aggregate. This hashes what the two
    logs agree on: who played, who won, how long it took, and the prize
    split. Names go in hashed, never in the clear.

    None when the parse is too incomplete to be sure.
    """
    import hashlib
    if not parsed or not parsed.get("parse_ok"):
        return None
    me, opp = parsed.get("player"), parsed.get("opponent")
    if not me or not opp or parsed.get("result") not in ("win", "loss"):
        return None
    winner, loser = (me, opp) if parsed["result"] == "win" else (opp, me)
    wp, lp = ((parsed["player_prizes_taken"], parsed["opponent_prizes_taken"])
              if parsed["result"] == "win" else
              (parsed["opponent_prizes_taken"], parsed["player_prizes_taken"]))
    key = "|".join(str(x) for x in (
        winner.lower(), loser.lower(), parsed.get("turns"),
        parsed.get("win_reason"), wp, lp))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def pseudonymise(text: str, parsed):
    """
    Replace both player names throughout the log with fixed labels, so
    the text can be sent to a server without carrying anyone's handle.

    Matches whole names only, longest first, so a name that happens to
    be a prefix of the other -- or of a card -- is not mangled.
    """
    t = _norm(text)
    names = [n for n in (parsed.get("player"), parsed.get("opponent")) if n]
    if len(names) != 2:
        return None
    labels = {names[0]: "PlayerA", names[1]: "PlayerB"}
    for n in sorted(names, key=len, reverse=True):
        t = re.sub(r"(?<![\w])" + re.escape(n) + r"(?![\w])", labels[n], t)
    return t


def validate(text: str):
    """
    Is this a complete, internally consistent battle log?

    Returns (ok, problems). Used before a match is recorded and again on
    the server before it is counted. A partial paste, a log cut off
    before the result, or a hand-edited one with numbers that don't add
    up all fail here rather than becoming a data point.
    """
    problems = []
    if not text or len(text) < 300:
        return False, ["too short to be a battle log"]
    t = _norm(text)
    if not SETUP_RE.search(t):
        problems.append("no Setup section")
    turns = TURN_RE.findall(t)
    if len(turns) < 1:
        problems.append("no turns")
    names = players(t)
    if len(names) != 2:
        problems.append(f"expected 2 players, found {len(names)}")
    if not WINS_RE.search(t):
        problems.append("no result line - was the whole log copied?")
    # the result must be the LAST thing: anything after it is not a log
    m = None
    for m in WINS_RE.finditer(t):
        pass
    if m and t[m.end():].strip():
        problems.append("text after the result line")

    d = parse(t) if len(names) == 2 else None
    if d and d.get("parse_ok"):
        pz = d["player_prizes_taken"], d["opponent_prizes_taken"]
        if any(p is not None and not (0 <= p <= 6) for p in pz):
            problems.append("prize count outside 0-6")
        if d["win_reason"] == "prizes" and d["result"] in ("win", "loss"):
            winner_prizes = pz[0] if d["result"] == "win" else pz[1]
            if winner_prizes != 6:
                problems.append("won on prizes without taking six")
        if d["turns"] and d["turns"] > 80:
            problems.append("implausible turn count")
        opening = t.count("drew 7 cards for the opening hand")
        if opening != 2:
            problems.append("opening hands not drawn for both players")
    return not problems, problems


# The local player's draws name the card; the opponent's say "a card".
# This is how we identify whose client produced the log, with no config.
NAMED_DRAW_RE = re.compile(r"^(?:- )?(?P<who>.+?) drew (?!a card\.|\d+ )(?P<card>.+?)\.$", re.M)
HIDDEN_DRAW_RE = re.compile(r"^(?:- )?(?P<who>.+?) drew a card\.$", re.M)


def detect_local_player(text: str):
    """
    Work out which player owns this log.

    Returns (name, confidence). Confidence is the share of named draws
    belonging to the winner, so a caller can fall back to asking when
    the signal is weak.
    """
    t = _norm(text)
    lines = t.split("\n")

    # Strongest signal: the draw at the START of a turn. Yours is named,
    # your opponent's is always "drew a card". Mid-turn draws from a
    # Supporter are revealed to both players, so they are NOT reliable.
    named, hidden = {}, {}
    for i, line in enumerate(lines):
        m = TURN_RE.match(line)
        if not m:
            continue
        owner = m.group("who").strip()
        for nxt in lines[i + 1:i + 3]:
            nxt = nxt.strip()
            if not nxt:
                continue
            if nxt == f"{owner} drew a card.":
                hidden[owner] = hidden.get(owner, 0) + 1
            elif nxt.startswith(f"{owner} drew "):
                named[owner] = named.get(owner, 0) + 1
            break

    if named:
        best = max(named, key=named.get)
        mine = named[best]
        theirs = hidden.get(best, 0)
        conf = mine / (mine + theirs) if (mine + theirs) else 0.0
        return best, round(conf, 3)

    # fallback: any named draw at all
    for m in NAMED_DRAW_RE.finditer(t):
        who = m.group("who").strip()
        named[who] = named.get(who, 0) + 1
    if not named:
        return None, 0.0
    best = max(named, key=named.get)
    return best, round(named[best] / sum(named.values()) * 0.6, 3)


def players(text: str):
    """Both display names, in the order they first appear at setup."""
    t = _norm(text)
    seen = []
    for m in OPENING_RE.finditer(t):
        n = m.group("who").strip()
        if n not in seen:
            seen.append(n)
    for m in TURN_RE.finditer(t):
        n = m.group("who").strip()
        if n not in seen:
            seen.append(n)
    return seen


# ------------------------------------------------------------ events

PRIZE_RE = re.compile(
    r"^(?P<who>.+?) took (?:a|(?P<n>\d+)) Prize cards?\.", re.M)
MULLIGAN_RE = re.compile(
    r"^(?P<who>.+?) took (?:a|(?P<n>\d+)) mulligans?\.", re.M)
KO_RE = re.compile(rf"^(?P<owner>.+?){AP}s (?P<mon>.+?) was Knocked Out!", re.M)
WINS_RE = re.compile(r"(?P<who>[^\s.][^.]*?) wins\.\s*$", re.M)

# "X played Card." / "X played Card to the Bench." / "... to the Active Spot."
PLAYED_RE = re.compile(
    r"^(?P<who>.+?) played (?P<card>.+?)"
    r"(?: to the (?:Bench|Active Spot|Stadium spot))?\.$", re.M)
# "...drew 2 cards and played them to the Bench." names no card; the cards
# are listed on the bullet line that follows. Without this guard the word
# "them" gets filed as a card.
NOT_A_CARD = {"them", "it", "a card", "cards"}
# "X attached Energy to Mon in the Active Spot."
ATTACHED_RE = re.compile(
    r"^(?:- )?(?P<who>.+?) attached (?P<card>.+?) to (?P<mon>.+?) "
    r"(?:in|on) the (?:Active Spot|Bench)\.$", re.M)
# "X evolved A to B on the Bench." -- and the indented form Grand Tree
# and Rare Candy produce: "- X evolved A to B on the Bench."
EVOLVED_RE = re.compile(
    r"^(?:- )?(?P<who>.+?) evolved (?P<from>.+?) to (?P<to>.+?) "
    r"(?:in|on) the (?:Active Spot|Bench)\.$", re.M)
# "X's Mon used Attack on Y's Target for N damage."
ATTACK_RE = re.compile(
    rf"^(?P<who>.+?){AP}s (?P<mon>.+?) used (?P<attack>.+?)"
    rf"(?: on (?P<target_owner>.+?){AP}s (?P<target>.+?) "
    rf"for (?P<dmg>[\d,]+) damage)?\.", re.M)
# bullet lines listing revealed/drawn cards
BULLET_RE = re.compile(r"^\s*\u2022\s*(?P<cards>.+?)\s*$", re.M)
# "X drew 2 more cards because Y took at least 1 mulligan."
MULL_DRAW_RE = re.compile(
    r"^(?P<who>.+?) drew (?P<n>\d+) more cards? because (?P<other>.+?) "
    r"took at least 1 mulligan\.$", re.M)


def _count(d, k, n=1):
    d[k] = d.get(k, 0) + n


def parse(text: str, me: str | None = None) -> dict:
    """
    Parse a battle log into a dict.

    `me` is optional: if omitted, the first player listed is assumed.
    Fields that cannot be determined come back as None rather than a
    guess, so a bad parse shows up as a gap instead of wrong data.
    """
    t = _norm(text)
    names = players(t)
    if not names:
        return {"parse_ok": False, "reason": "no players found"}

    if me and me in names:
        opp = next((n for n in names if n != me), None)
    elif me:
        # name given but not found -- case-insensitive retry
        lower = {n.lower(): n for n in names}
        me = lower.get(me.lower())
        opp = next((n for n in names if n != me), None) if me else None
    else:
        detected, conf = detect_local_player(t)
        if detected and conf >= 0.8:
            me = detected
        else:
            me = names[0]
        opp = next((n for n in names if n != me), None)

    if not me:
        return {"parse_ok": False, "reason": "player name not in log"}

    # --- turn order
    went_first = None
    m = GO_FIRST_RE.search(t)
    if m:
        chooser, order = m.group("who").strip(), m.group("order")
        if order == "first":
            went_first = (chooser == me)
        else:
            went_first = (chooser != me)
    elif (m := COIN_WIN_RE.search(t)):
        pass  # coin winner alone doesn't determine order

    coin_winner = None
    if (m := COIN_WIN_RE.search(t)):
        coin_winner = m.group("who").strip()

    # --- turns
    turn_owners = [x.strip() for x in TURN_RE.findall(t)]
    turns_total = len(turn_owners)

    # --- prizes
    prizes = {}
    for m in PRIZE_RE.finditer(t):
        who = m.group("who").strip()
        n = int(m.group("n")) if m.group("n") else 1
        _count(prizes, who, n)

    # --- mulligans (last count wins: log says "a", then "2", then "3")
    mulligans = {}
    for m in MULLIGAN_RE.finditer(t):
        who = m.group("who").strip()
        n = int(m.group("n")) if m.group("n") else 1
        mulligans[who] = max(mulligans.get(who, 0), n)

    # --- cards drawn because the OTHER player mulliganed
    mull_draws = {}
    for m in MULL_DRAW_RE.finditer(t):
        who = m.group("who").strip()
        mull_draws[who] = mull_draws.get(who, 0) + int(m.group("n"))

    # --- knockouts, attributed to the owner who lost the Pokemon
    kos = {}
    for m in KO_RE.finditer(t):
        _count(kos, m.group("owner").strip())

    # --- result
    result, reason = None, None
    wm = None
    for wm in WINS_RE.finditer(t):
        pass  # take the last "X wins." line
    if wm:
        winner = wm.group("who").strip()
        # strip a leading sentence fragment: "...Prize cards. Gabo1550 wins."
        winner = winner.split(". ")[-1].strip()
        if winner in names:
            result = "win" if winner == me else "loss"
    if "conceded" in t:
        reason = "concede"
    elif "took all of their Prize cards" in t:
        reason = "prizes"
    elif "no more cards" in t or "deck out" in t.lower():
        reason = "deckout"

    # --- cards seen, per player
    cards = {n: {} for n in names}

    for m in PLAYED_RE.finditer(t):
        who, card = m.group("who").strip(), m.group("card").strip()
        if who in cards and card.lower() not in NOT_A_CARD:
            _count(cards[who], card)

    for m in ATTACHED_RE.finditer(t):
        who, card = m.group("who").strip(), m.group("card").strip()
        if who in cards:
            _count(cards[who], card)

    for m in EVOLVED_RE.finditer(t):
        who, to = m.group("who").strip(), m.group("to").strip()
        if who in cards:
            _count(cards[who], to)

    # --- cards revealed on bullet lines
    # Lines like "- heatfireash drew 2 cards and played them to the Bench."
    # or "- 7 drawn cards." are followed by an indented bullet listing the
    # actual cards. Without reading those, cards that entered play via a
    # search effect never get recorded at all.
    lines = t.split("\n")
    owner = None
    REVEAL_CUES = ("drawn cards", "drew", "revealed", "discarded",
                   "shuffled", "played them", "were discarded",
                   "added to", "moved")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # track whose action we are inside
        for n in names:
            if stripped.startswith(n) or stripped.startswith(f"- {n}"):
                owner = n
                break
        else:
            m = TURN_RE.match(stripped)
            if m:
                owner = m.group("who").strip()
        if not stripped.startswith("\u2022"):
            continue
        # only bullets that follow a card-related line. Blank lines in
        # between are skipped: with one there, "played them to the Bench"
        # was never seen, and a Genesect ex played off a Precious Trolley
        # never counted as being in the deck at all
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        prev = lines[j].strip().lower() if j >= 0 else ""
        if not any(c in prev for c in REVEAL_CUES):
            continue
        if owner not in cards:
            continue
        for name in BULLET_RE.match(stripped).group("cards").split(","):
            name = name.strip()
            if name and name.lower() not in NOT_A_CARD:
                _count(cards[owner], name)

    # --- attacks
    attacks = []
    for m in ATTACK_RE.finditer(t):
        who = m.group("who").strip()
        if who not in names:
            continue
        attacks.append({
            "player": who,
            "pokemon": m.group("mon").strip(),
            "attack": m.group("attack").strip(),
            "target": (m.group("target") or "").strip() or None,
            "damage": int(m.group("dmg").replace(",", "")) if m.group("dmg") else None,
        })

    detected, conf = detect_local_player(t)

    # moves seen per Pokemon, per player. Used to identify which cards
    # are Pokemon (they attack) and to match a deck against ones already
    # recorded.
    moves = {n: {} for n in names}
    for a in attacks:
        moves[a["player"]].setdefault(a["pokemon"], set()).add(a["attack"])
    moves = {n: {k: sorted(v) for k, v in d.items()} for n, d in moves.items()}

    # what each player evolved INTO. In a short game this is often the
    # only thing that names the deck: nobody attacked, but you don't
    # evolve into your deck's centrepiece by accident.
    evos = {n: {} for n in names}
    for m in EVOLVED_RE.finditer(t):
        who, to = m.group("who").strip(), m.group("to").strip()
        if who in evos:
            evos[who][to] = evos[who].get(to, 0) + 1

    # damage each Pokemon dealt, per player -- the archetype signal
    pmg = {n: {} for n in names}
    for a in attacks:
        if a["damage"]:
            pmg[a["player"]][a["pokemon"]] = (
                pmg[a["player"]].get(a["pokemon"], 0) + a["damage"])

    # how many times each Pokemon used something that did no damage --
    # abilities, almost always. A Metang that fires Metal Maker four
    # times a game is part of the deck's identity even though it never
    # attacks, and this is the count that shows it.
    uses = {n: {} for n in names}
    for a in attacks:
        if not a["damage"]:
            uses[a["player"]][a["pokemon"]] = (
                uses[a["player"]].get(a["pokemon"], 0) + 1)

    return {
        "parse_ok": True,
        "player": me,
        "detected_player": detected,
        "detect_confidence": conf,
        "opponent": opp,
        "result": result,
        "win_reason": reason,
        "went_first": went_first,
        "coin_winner": coin_winner,
        "turns": turns_total,
        "player_prizes_taken": prizes.get(me, 0),
        "opponent_prizes_taken": prizes.get(opp, 0) if opp else None,
        "player_mulligans": mulligans.get(me, 0),
        "opponent_mulligans": mulligans.get(opp, 0) if opp else None,
        "player_mulligan_draws": mull_draws.get(me, 0),
        "opponent_mulligan_draws": mull_draws.get(opp, 0) if opp else None,
        "player_kos_suffered": kos.get(me, 0),
        "opponent_kos_suffered": kos.get(opp, 0) if opp else None,
        "player_cards": cards.get(me, {}),
        "opponent_cards": cards.get(opp, {}) if opp else {},
        "player_damage": sum(a["damage"] or 0 for a in attacks if a["player"] == me),
        "opponent_damage": sum(a["damage"] or 0 for a in attacks if a["player"] == opp),
        "attacks": attacks,
        "player_moves": moves.get(me, {}),
        "opponent_moves": moves.get(opp, {}) if opp else {},
        "player_pokemon_damage": pmg.get(me, {}),
        "opponent_pokemon_damage": pmg.get(opp, {}) if opp else {},
        "player_evolutions": evos.get(me, {}),
        "opponent_evolutions": evos.get(opp, {}) if opp else {},
        "player_ability_uses": uses.get(me, {}),
        "opponent_ability_uses": uses.get(opp, {}) if opp else {},
    }


# ------------------------------------------------------------ archetype

# Bump when a change here or in cluster.py should apply to matches
# already recorded. The app and the server each re-read their stored logs
# once when they see a newer number.
#   2 -- ability uses counted; Grand Tree / Rare Candy evolutions
#        counted; trainer-owned names ("Team Rocket's") no longer look
#        like one Pokemon; per-match names follow the damage/ability rule
#   3 -- stages of one Pokemon recognised by evolution family, not by
#        the start of the name: no more "Garchomp ex / Gabite"
#   4 -- the game's card codes dropped from names: "(mebsp_33) Mega
#        Lucario ex" is read as "Mega Lucario ex"
#   5 -- and the longer codes too: "(me1_73_ph) Hariyama"
PARSER_VERSION = 5

_OWNER_RE = re.compile(r"^[^'’]{1,24}['’]s\s+")


def _species(name):
    """"Team Rocket's Mewtwo ex" -> "mewtwo". The trainer's name goes
    first, or every Team Rocket's card looks like the same Pokemon."""
    s = _OWNER_RE.sub("", name.strip()).replace("Mega ", "")
    return (s.split(" ")[0] if s else "").lower()


def same_line(a, b):
    """
    Is one Pokemon another's stage -- Gabite and Garchomp, Metang and
    Metagross -- so a deck isn't named after two of its own stages?
    Siblings aren't: Gardevoir and Gallade can both be in a deck's name.

    Decided by real evolution data (evolutions.py). Only for a
    Pokemon that table doesn't know, like one from a set newer than it,
    does it fall back to comparing the start of the names. That fallback
    alone used to decide it, and missed every line whose names don't
    share a start: Gible/Gabite/Garchomp, Dreepy/Drakloak/Dragapult.
    """
    try:
        import evolutions
        known = evolutions.stages_of_one(a, b)
        if known is not None:
            return known
    except ImportError:
        pass
    aw, bw = _species(a), _species(b)
    return bool(aw) and aw[:4] == bw[:4]


def guess_archetype(card_counts: dict, moves: dict = None,
                    damage: dict = None, evolutions: dict = None,
                    uses: dict = None) -> str | None:
    """
    Name the deck after what actually carried this game, by the same
    rule the grouping in cluster.py uses for many games:

      * first name: the Pokemon that did the most damage. Only when
        nothing did any (an early concede) do other signals decide --
        evolving into a card, using it, copies seen, ex over basics.
      * second name: whichever other Pokemon did the most work, measured
        two ways, the larger counting -- a quarter or more of the damage,
        or its ability used twice or more. A Spidops charging energy
        three times is part of the deck even though it never attacks.
        Just being in the deck earns nothing.

    `uses` is how many times each Pokemon used something that did no
    damage (parse()'s *_ability_uses). Without it, each distinct move
    name counts once, which undercounts: three Charging Ups look like
    one.
    """
    if not card_counts:
        return None
    moves = moves or {}
    damage = damage or {}
    evolutions = evolutions or {}
    if uses is None:
        uses = {n: len(v) for n, v in moves.items()
                if not damage.get(n)}

    def is_mon(name):
        # Pokemon are the only cards that attack or evolve; anything that
        # used a move is one, and so is anything we saw damage from or
        # anything evolved into.
        return name in moves or name in damage or name in evolutions

    def premium(name):
        return 2 if " ex" in name else (1 if name.startswith("Mega ") else 0)

    # Every Pokemon with evidence, not only the ones seen being played. A
    # Pokemon that attacked is in the deck even if the log never showed
    # it arriving -- it may have come off a search card whose list was
    # missed. Leaving it out named a deck after its 60-damage Metagross
    # while Genesect ex did the other 300.
    candidates = dict(card_counts)
    for name in list(moves) + list(damage) + list(evolutions):
        candidates.setdefault(name, 0)

    scored = []
    for name in candidates:
        if not is_mon(name):
            continue
        dmg = damage.get(name, 0)
        n_uses = uses.get(name, 0)
        evo = evolutions.get(name, 0)
        scored.append((
            dmg / 100.0 * 3          # damage dominates when there is any
            + evo * 4                # evolving into it is a deliberate act
            + n_uses
            + premium(name)
            + card_counts.get(name, 0) * 0.25,
            dmg, name))
    if not scored:
        # No attacks, no evolutions -- a concession on turn one or two.
        # There is genuinely no evidence here, so say so rather than
        # picking a card at random and calling it the deck.
        return None

    total = sum(damage.values())
    if total:
        # the biggest damage dealer, full stop; score only breaks a tie
        scored.sort(key=lambda t: (-t[1], -t[0], t[2]))
    else:
        scored.sort(key=lambda t: (-t[0], t[2]))
    primary = scored[0][2]

    best, best_strength = None, 0.0
    for _, dmg, n in scored:
        if n == primary or same_line(primary, n):
            continue
        damage_strength = (dmg / total) / 0.25 if total else 0.0
        use_strength = uses.get(n, 0) / 2.0
        strength = max(damage_strength, use_strength)
        if strength > best_strength:
            best, best_strength = n, strength
    if best and best_strength >= 1.0:
        return f"{primary} / {best}"
    return primary


if __name__ == "__main__":
    import sys
    raw = open(sys.argv[1], encoding="utf-8").read()
    me = sys.argv[2] if len(sys.argv) > 2 else None
    out = parse(raw, me)
    out.pop("attacks", None)
    print(json.dumps(out, indent=2, ensure_ascii=False))


def log_view_lines(text: str, anonymise: bool = False):
    """
    The log as (kind, text) lines for display.

    kind is one of: "turn_you", "turn_opp", "turn" (headings), "you",
    "opp", "line", "detail", "cards", "win", "loss", "gap".

    anonymise=True is for a log fetched back from the server, where the
    names are PlayerA/PlayerB: they are shown as You and Opponent. A log
    from this PC keeps the real names -- it is your own copy.
    """
    t = _norm(text)
    # In a log from the server, PlayerA is always you: the app and the
    # website both label it that way before upload.
    d = parse(t, me="PlayerA" if anonymise and "PlayerA" in t else None)
    me = d.get("player") if d.get("parse_ok") else None
    opp = d.get("opponent") if me else None
    if anonymise and me and opp:
        for name, you in ((me, True), (opp, False)):
            n = re.escape(name)
            t = re.sub(rf"(?<!\w){n}['’]s\b",
                       "Your" if you else "Opponent's", t)
            t = re.sub(rf"(?<!\w){n} wins\.",
                       "You win." if you else "Opponent wins.", t)
            t = re.sub(rf"(?<!\w){n}(?!\w)",
                       "You" if you else "Opponent", t)
        t = re.sub(r"(?<=[a-z,] )(You|Your|Opponent)\b",
                   lambda m: m.group(1).lower(), t)
        me, opp = "You", "Opponent"

    def owner(line):
        for who, label in ((me, "you"), (opp, "opp")):
            if who and (line.startswith(who + " ") or
                        line.startswith(who + "'s ") or
                        line.startswith(who + "’s ") or
                        (who == "You" and line.startswith("Your "))):
                return label
        return ""

    out = []
    for raw in t.split("\n"):
        line = raw.strip()
        if not line:
            if out and out[-1][0] != "gap":
                out.append(("gap", ""))
            continue
        if line == "Setup":
            out.append(("turn", line))
        elif line.endswith("Turn") and len(line) < 60:
            w = owner(line)
            out.append(("turn_" + w if w else "turn", line))
        elif line.startswith("•"):
            out.append(("cards", line.lstrip("• ").strip()))
        elif line.startswith("- "):
            out.append(("detail", line[2:]))
        elif line.endswith(" wins.") or line.endswith("You win."):
            won = (me and (line.endswith(f"{me} wins.") or
                           line.endswith("You win.")))
            out.append(("win" if won else "loss", line))
        else:
            out.append((owner(line) or "line", line))
    while out and out[-1][0] == "gap":
        out.pop()
    return out
