"""
Working out archetypes from the data instead of a curated list.

A hand-written definition file names decks accurately and needs updating
every time a set drops. This does the opposite trade: it groups decks by
the Pokemon that actually appeared in play, names each group after its
most common Pokemon, and keeps working when the format rotates because
nobody has to tell it anything.

It will sometimes be wrong. Two decks sharing an engine can merge; a
deck that shows different Pokemon in different games can split. Those
are the costs of not maintaining a list, and they get smaller as the
number of recorded games grows.

How it works:

  1. Each side of each match contributes the set of Pokemon seen.
  2. Sets are grouped by overlap, largest first, so the commonest
     versions of a deck anchor the groups and odd games attach to them
     rather than founding their own.
  3. A group is named after the Pokemon present in most of its games,
     preferring the headline cards (ex, Mega) that players use as names.
"""

import json
import re
from collections import Counter

try:
    from ptcgl_parse import mega_family
except ImportError:                      # used on its own
    def mega_family(name):
        m = re.match(r"^(Mega \S.*?) [XY]( ex)?$", name or "")
        return f"{m.group(1)}{m.group(2) or ''}" if m else name

# Shown in almost every deck, so they say nothing about which deck it is.
GENERIC = {
    "Ultra Ball", "Nest Ball", "Buddy-Buddy Poffin", "Rare Candy", "Switch",
    "Super Rod", "Night Stretcher", "Earthen Vessel", "Professor's Research",
    "Iono", "Boss's Orders", "Arven", "Pokegear 3.0", "Poke Pad",
    "Counter Catcher", "Technical Machine: Evolution", "Hero's Cape",
    "Energy Retrieval", "Energy Recycler", "Jumbo Ice Cream",
}

# How much of a deck's Pokemon must appear in a group for it to belong.
JOIN = 0.6
# Below this many games a group is not named separately; it is reported
# as "other" rather than presented as an archetype.
MIN_GAMES = 3


def is_identity_card(name):
    """Is this card worth clustering on?"""
    if not name or name in GENERIC:
        return False
    if name.lower().startswith("basic ") and name.lower().endswith(" energy"):
        return False
    return True


def headline_score(name):
    """How likely players are to name the deck after this card."""
    s = 0
    if " ex" in name:
        s += 3
    if name.startswith("Mega "):
        s += 2
    if name.endswith(" V") or name.endswith(" VMAX") or name.endswith(" VSTAR"):
        s += 2
    return s


def _signature(mons):
    return frozenset(m for m in mons if is_identity_card(m))


def _containment(sig, pool):
    """Share of this deck's Pokemon that the group already knows about."""
    if not sig:
        return 0.0
    return len(sig & pool) / len(sig)


def _main_attackers(items):
    """
    Which Pokemon actually lead decks.

    A Pokemon leads the damage in an odd game now and then -- a Dusknoir
    taking two prizes while the real attacker sets up -- and if every
    such game counted as its own kind of deck, those Pokemon would each
    become an archetype that games from every real deck leak into. So a
    Pokemon is a main attacker only if it tops the damage in a real
    share of games: at least three, and at least 3% of all games with
    an attacker.
    """
    tops = Counter()
    for _, sig, dmg, _u in items:
        top = _top_attacker(dmg)
        if top:
            tops[top] += 1
    total = sum(tops.values()) or 1
    # The bar scales with how much there is to go on. At a few hundred
    # games, three is what separates a deck from a fluke. At a dozen, it
    # means nothing ever qualifies, nothing groups, and every game stands
    # alone under its own name -- two games of one deck show as two
    # decks. So early on, leading the damage once is enough; a side
    # attacker's odd game still joins the deck it overlaps (pass 1)
    # rather than founding its own.
    if total >= 150:
        need, share = 3, 0.03
    elif total >= 40:
        need, share = 2, 0.0
    else:
        need, share = 1, 0.0
    return {m for m, n in tops.items() if n >= need and n / total >= share}


def _engines(items, mains):
    """
    Pokemon that appear across many different decks are engines, not
    identities: Mega Kangaskhan sits in a Slowking deck and a Dragapult
    deck and a dozen others, drawing cards and never attacking. Counting
    it as evidence merges decks that have nothing else in common, and
    counting it towards a name gets the name wrong.

    Found from the data: a Pokemon seen alongside three or more different
    main attackers, at least three games each, is an engine -- everywhere
    except a game where it did the attacking itself. Only established
    main attackers count, so an evolution line is not mistaken for an
    engine just because a side attacker led one odd game.
    """
    pair = Counter()
    for _, sig, dmg, _u in items:
        top = _top_attacker(dmg)
        if not top or top not in mains:
            continue
        for m in sig:
            if m != top:
                pair[(m, top)] += 1
    partners = {}
    for (m, top), n in pair.items():
        if n >= 3:
            partners.setdefault(m, set()).add(top)
    return {m for m, tops in partners.items() if len(tops) >= 3}


def _split(mons):
    """
    Accept either {mon: damage} or {mon: {"d": damage, "u": uses}}.
    Returns (damage, uses) dicts.
    """
    dmg, use = {}, {}
    if isinstance(mons, dict):
        for m, v in mons.items():
            # both Mega forms of one Pokemon (Charizard X and Y) are one
            # Pokemon for grouping and naming: decks run both
            m = mega_family(m)
            if isinstance(v, dict):
                dmg[m] = dmg.get(m, 0) + int(v.get("d", 0) or 0)
                use[m] = use.get(m, 0) + int(v.get("u", 0) or 0)
            else:
                dmg[m] = dmg.get(m, 0) + int(v or 0)
                use.setdefault(m, 0)
    else:
        for m in mons:
            m = mega_family(m)
            dmg.setdefault(m, 0)
            use.setdefault(m, 0)
    return dmg, use


def _top_attacker(dmg):
    """The Pokemon that dealt the most damage this game, if any did."""
    if not dmg:
        return None
    best = max(dmg.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else None


def build(sides):
    """
    Group deck sightings into archetypes.

    `sides` is a list of (key, mons) where mons is {pokemon: damage}.

    Two passes. Games with an attacker are grouped by who attacked: the
    deck IS its attacker, and a shared engine Pokemon is not grounds for
    merging. Games with no attacker -- concessions -- then attach to
    whichever group they share the most Pokemon with, since that is all
    the evidence they have.

    Returns (assignment, clusters) where assignment maps key -> name.
    """
    items = []
    for key, mons in sides:
        dmg, use = _split(mons)
        sig = _signature(dmg)
        if sig:
            items.append((key, sig, dmg, use))

    mains = _main_attackers(items)
    engines = _engines(items, mains)

    def identity(sig, dmg):
        """The Pokemon that count as evidence for this game."""
        top = _top_attacker(dmg)
        return {m for m in sig if m not in engines or m == top}

    def led_by_main(dmg):
        """Did a real main attacker lead this game? Only those games
        anchor groups; a game led by a side attacker is placed by
        overlap like a concession."""
        top = _top_attacker(dmg)
        return bool(top) and top in mains

    # A game whose only Pokemon are engines says nothing about which
    # deck it was. It may still attach to a group later, on whatever
    # overlap it has, but it never founds one: that was producing a new
    # "archetype" for every short game that showed Kangaskhan and
    # nothing else.
    def informative(sig, dmg):
        return bool(identity(sig, dmg))

    # A group can't take in a game that shows a deck it has never seen
    # lead: one where the Pokemon that did the most damage, or a Mega,
    # appears in none of the group's games. Without this, a Charizard
    # deck that also runs Kangaskhan, Latias and Meowth for draw was
    # filed under the Kangaskhan deck those three also appear in, though
    # Charizard did all the damage. The same rule Limitless naming uses:
    # a deck is never named after one that doesn't play its attacker.
    def foreign(group_known, top, ident):
        if top and top not in group_known:
            return True
        return any(m.startswith("Mega ") and m not in group_known
                   for m in ident)

    with_attacks = [it for it in items
                    if led_by_main(it[2]) and informative(it[1], it[2])]
    without = [it for it in items
               if not (led_by_main(it[2]) and informative(it[1], it[2]))]
    with_attacks.sort(key=lambda it: -len(it[1]))

    clusters = []

    # pass 1: games with an attacker. Overlap of the deck-defining
    # Pokemon decides, with a strong preference for a group that has
    # already seen this game's attacker do the attacking. Preference,
    # not requirement: a game where a side attacker took the KOs still
    # belongs to its deck, and must not found a new one.
    for key, sig, dmg, use in with_attacks:
        top = _top_attacker(dmg)
        ident = identity(sig, dmg)
        best, best_score = None, 0.0
        for c in clusters:
            known = c["pool"] | set(c["counts"])
            if foreign(known, top, ident):
                continue
            # and the other way round: a game whose attacker isn't one of
            # this group's, and that didn't even show the group's own
            # lead attacker, is another deck that shares its helpers --
            # a Kangaskhan deck must not join a Charizard group because
            # the Charizard deck runs Kangaskhan for draw. (A game of this
            # deck where a side attacker took the KOs and the main one
            # never came out starts a group of its own, which pass 3 then
            # folds back in.)
            lead = (c["top_counts"].most_common(1)[0][0]
                    if c["top_counts"] else None)
            if lead and lead not in sig and top not in c["attackers"]:
                continue
            score = _containment(ident, known)
            if top in c["attackers"]:
                score += 0.35
            elif top in known:
                score += 0.15
            if score > best_score:
                best, best_score = c, score
        if best is not None and best_score >= JOIN:
            _add(best, key, ident, dmg, use)
        else:
            clusters.append(_new(key, ident, dmg, use))

    # pass 2: everything else attaches by overlap alone. Uninformative
    # games use their full card set, engines included, since that is all
    # they have; if nothing fits they stay unassigned rather than
    # becoming a group of one.
    for key, sig, dmg, use in without:
        ident = identity(sig, dmg) or set(sig)
        top = _top_attacker(dmg)
        best, best_score = None, 0.0
        for c in clusters:
            known = c["pool"] | set(c["counts"])
            if foreign(known, top, ident):
                continue
            score = _containment(ident, known)
            if score > best_score:
                best, best_score = c, score
        if best is not None and best_score >= JOIN * 0.8:
            _add(best, key, ident, dmg, use)
        # else: unassigned. A game that fits no group and was not led by
        # a main attacker is not enough to found an archetype.

    # pass 3: a group too small to be a deck is a game that went oddly --
    # a side attacker took the KOs once, say. Fold it into the group it
    # overlaps most, so one unusual game does not become an archetype.
    clusters.sort(key=lambda c: -len(c["members"]))
    big = [c for c in clusters if len(c["members"]) >= MIN_GAMES]
    small = [c for c in clusters if len(c["members"]) < MIN_GAMES]
    kept = list(big)
    for c in small:
        best, best_score = None, 0.0
        for b in big:
            known = b["pool"] | set(b["counts"])
            if any(foreign(known, a, set(c["counts"])) for a in
                   (c["attackers"] or {None})):
                continue
            score = _containment(set(c["counts"]), known)
            if score > best_score:
                best, best_score = b, score
        if best is not None and best_score >= 0.4:
            for k in c["members"]:
                best["members"].append(k)
            best["counts"].update(c["counts"])
            best["damage"].update(c["damage"])
            best["attacked"].update(c["attacked"])
            best["uses"].update(c["uses"])
        else:
            kept.append(c)
    clusters = kept

    assignment = {}
    out = []
    for c in clusters:
        n = len(c["members"])
        name = _name_cluster(c, n)
        out.append({"name": name, "games": n,
                    "cards": c["counts"].most_common()})
        for k in c["members"]:
            assignment[k] = name
    return assignment, out


def _new(key, ident, dmg, use=None):
    c = {"pool": set(ident), "members": [key], "counts": Counter(ident),
         "damage": Counter(), "attacked": Counter(), "attackers": set(),
         "top_counts": Counter(), "uses": Counter()}
    _add_damage(c, dmg, use)
    return c


def _add(c, key, ident, dmg, use=None):
    c["members"].append(key)
    c["counts"].update(ident)
    c["pool"] |= {m for m, n in c["counts"].items() if n >= 2}
    _add_damage(c, dmg, use)


def _add_damage(c, dmg, use=None):
    for m, n in (use or {}).items():
        if n:
            c["uses"][m] += n
    for m, v in dmg.items():
        if v:
            c["damage"][m] += v
            c["attacked"][m] += 1
    top = _top_attacker(dmg)
    if top:
        c["top_counts"][top] += 1
        # a Pokemon is one of this deck's attackers once it has led the
        # damage in two games -- one odd game where a support Pokemon
        # took the KOs must not redefine what the deck is
        if c["top_counts"][top] >= 2 or len(c["members"]) == 1:
            c["attackers"].add(top)


def _name_cluster(c, n):
    """
    Name a group after the Pokemon that best identifies it.

    Frequency first -- a card in nearly every game of the deck is what
    players call it -- then the headline weighting, so "Charizard ex"
    wins over the Pidgeot that appears just as often.
    """
    # No special case for small groups: a group of one or two games is
    # named by the same rule as a group of a hundred. (It used to fall
    # back to whichever card was seen most, which named decks after
    # their Tarountula.)
    # The deck is named after what attacks. Damage share is the score;
    # how often the card was merely present only breaks ties. That is
    # what stops an engine Pokemon in every game from naming a deck it
    # never attacks with.
    total_damage = sum(c["damage"].values()) or 1
    scored = []
    for card, count in c["counts"].items():
        share = count / n
        damage_share = c["damage"].get(card, 0) / total_damage
        attack_share = c["attacked"].get(card, 0) / n
        if damage_share < 0.05 and share < 0.35:
            continue
        score = (damage_share * 3
                 + attack_share
                 + share * 0.3
                 + headline_score(card) * 0.05)
        scored.append((round(score, 3), damage_share, card))
    if not scored:
        return "unknown"
    scored.sort(reverse=True)
    primary = scored[0][2]

    # The second name goes to whichever other Pokemon does the most
    # work: a real second attacker (a quarter of the damage or more), or
    # the deck's ability engine (an ability fired twice a game or more).
    # A Metang using Metal Maker four times a game is more a part of the
    # deck than a Pokemon that landed one 60-damage attack, so uses and
    # damage are put on the same footing and the larger wins. A card
    # that is merely present every game earns nothing.
    best_second, best_strength = None, 0.0
    for card in c["counts"]:
        if card == primary or _same_line(primary, card):
            continue
        damage_strength = (c["damage"].get(card, 0) / total_damage) / 0.25
        use_strength = (c["uses"].get(card, 0) / n) / 2.0
        strength = max(damage_strength, use_strength)
        if strength > best_strength:
            best_second, best_strength = card, strength
    if best_second and best_strength >= 1.0:
        return f"{primary} / {best_second}"
    return primary


_OWNER = re.compile(r"^[^'’]{1,24}['’]s\s+")


def _species(name):
    """
    "Team Rocket's Mewtwo ex" -> "mewtwo", "Mega Excadrill ex" ->
    "excadrill". The trainer's name has to go first: compared as it
    stood, every Team Rocket's card looked like the same Pokemon, so
    Spidops could never be named beside Mewtwo.
    """
    s = _OWNER.sub("", name.strip())
    s = s.replace("Mega ", "")
    return (s.split(" ")[0] if s else "").lower()


def _same_line(a, b):
    """One Pokemon another's stage? The same check the per-game name
    uses (ptcgl_parse.same_line), so both agree."""
    try:
        from ptcgl_parse import same_line
        return same_line(a, b)
    except ImportError:
        aw, bw = _species(a), _species(b)
        return bool(aw) and aw[:4] == bw[:4]


def pokemon_from_parse(d, side):
    """
    The Pokemon seen for one side of a parsed match, with the damage each
    one dealt.

    A card is a Pokemon if it attacked, used an ability, was evolved
    into, or reads like one by name. Trainers and energy never do the
    first three, which is what makes this work without a card database.

    The damage matters for naming: players name a deck after its main
    attacker, so the Pokemon that does the work should win over one that
    merely appears as often.
    """
    prefix = "player" if side == "mine" else "opponent"
    dmg = dict(d.get(f"{prefix}_pokemon_damage") or {})
    mons = set(d.get(f"{prefix}_moves") or {})
    mons |= set(d.get(f"{prefix}_evolutions") or {})
    mons |= set(dmg)
    for card in (d.get(f"{prefix}_cards") or {}):
        if " ex" in card or card.startswith("Mega ") or card.endswith(" V"):
            mons.add(card)
    uses = dict(d.get(f"{prefix}_ability_uses") or {})
    return {m: {"d": int(dmg.get(m, 0)), "u": int(uses.get(m, 0))}
            for m in sorted(mons) if is_identity_card(m)}
