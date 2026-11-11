"""The board as one power sees it, in plain text.

Everything here is either public (positions, centre counts, last phase's
orders) or belongs to `power` (its legal moves, its inbox). It is the whole of
what a seat needs to play a phase, so a seat never has to look anywhere else.
All geometry comes from the engine, so none of it can drift from the rules.
"""
from __future__ import annotations

import re

from diplomacy import Game

from vibe.game import ALL, POWERS, Match

SYNTAX = (
    "Order forms: move `A <from> - <to>` · hold `A <at> H` · support a move "
    "`A <at> S A <from> - <to>` · support a hold `A <at> S F <at>` · convoy "
    "`F <sea> C A <from> - <to>` with `A <from> - <to> VIA` · retreat "
    "`A <at> R <to>` · disband `A <at> D` · build `A <at> B` or `F <at> B`. "
    "Use F for fleets. Text after # is ignored. Units you don't order hold."
)

RULES = (
    "- Supply centres change hands only when a unit is in them after a Fall "
    "turn. A centre you leave empty in Spring is still yours unless another "
    "power's unit is standing in it when Fall ends. Each winter you build or "
    "disband to match your centre count.\n"
    "- A support only counts if the supported unit makes exactly that move. "
    "It is cut, and the supporter just holds, if the supporter is attacked "
    "from any province other than the one it is supporting into."
)


LORE_SHOWN = 4000               # the newest few games' worth


def _base(prov: str) -> str:
    return prov.upper().split("/")[0]


def _no_coast(order: str) -> str:
    """A support names the destination without its coast: S F BLA - BUL."""
    return re.sub(r"/[A-Z]{2}\b", "", order)


def _units_by_prov(game: Game) -> dict[str, tuple[str, str]]:
    return {_base(u.split()[1]): (name, u)
            for name, p in game.powers.items() for u in p.units}


def _standings(game: Game, power: str) -> str:
    """Every supply centre by owner, biggest first, with any foreign unit on it."""
    occupied = _units_by_prov(game)

    def names(centres, owner) -> str:
        out = []
        for c in sorted(centres):
            hit = occupied.get(c)
            out.append(f"{c} ({hit[0]} {hit[1].split()[0]} there)"
                       if hit and hit[0] != owner else c)
        return ", ".join(out) or "none"

    rows = sorted(POWERS, key=lambda p: -len(game.powers[p].centers))
    lines = [f"- {p}: {len(game.powers[p].centers)} centres, {len(game.powers[p].units)} "
             f"units{' ← you' if p == power else ''} — {names(game.powers[p].centers, p)}"
             for p in rows]
    owned = {c for p in POWERS for c in game.powers[p].centers}
    neutral = [c for c in game.map.scs if c not in owned]
    if neutral:
        lines.append(f"- neutral: {len(neutral)} — {names(neutral, None)}")
    return "\n".join(lines)


def _last_phase(match: Match, game: Game) -> str:
    """The last movement phase in full, then any retreats or builds since.

    After a winter the builds alone say little; the moves before them are
    the only sign of what anyone intends.
    """
    phases = [str(k) for k in game.order_history.keys()]
    if not phases:
        return "_(nothing yet — this is the opening.)_"
    moves = [i for i, ph in enumerate(phases) if ph.endswith("M")]
    start = moves[-1] if moves else len(phases) - 1
    lines = []
    for ph in phases[start:]:
        hist = match.history(ph) or {}
        orders = sorted((p, o) for p, o in (hist.get("orders") or {}).items() if o)
        if ph == phases[start]:
            lines.append(f"_{ph}:_")
            lines += [f"- {p}: {', '.join(o)}" for p, o in orders]
            results = hist.get("results") or {}
            if results:
                lines.append("Results: " + "; ".join(f"{u} {', '.join(r)}"
                                                      for u, r in sorted(results.items())))
        elif orders:
            lines.append(f"_Then {ph}:_ " + "; ".join(f"{p} {', '.join(o)}" for p, o in orders))
    return "\n".join(lines)


_WHY = {
    "void": "VOID — the unit it supported or convoyed did not make that move",
    "no convoy": "NO CONVOY — no fleet carried it",
    "cut": "support CUT — the supporting unit was attacked",
    "bounce": "bounced — met equal or greater strength",
    "dislodged": "your unit was DISLODGED",
    "disrupted": "convoy disrupted",
}


def _my_outcomes(match: Match, game: Game, power: str) -> str:
    """What happened to your orders in your last movement phase, and why."""
    for phase in reversed([str(k) for k in game.order_history.keys()]):
        if not phase.endswith("M"):
            continue
        hist = match.history(phase) or {}
        mine = (hist.get("orders") or {}).get(power) or []
        if not mine:
            continue
        results = hist.get("results") or {}
        bad = []
        for o in mine:
            unit = " ".join(o.split()[:2])
            tags = results.get(unit) or []
            if tags:
                bad.append(f"- {o} → " + "; ".join(_WHY.get(t, t) for t in tags))
        refused = (hist.get("refused") or {}).get(power) or []
        out = (f"All {len(mine)} of your {phase} orders succeeded." if not bad else
               f"_{phase}:_ {len(mine) - len(bad)} succeeded, these did not:\n"
               + "\n".join(bad))
        if refused:
            out += ("\nYou also wrote these, which could not be used, so the orders "
                    "above were played instead:\n" + "\n".join(f"- {r}" for r in refused))
        return out
    return ""


def _digest(game: Game) -> str:
    """Centre changes, one line per year — the arc of the game."""
    snaps = [(str(ph), {p: set(c) for p, c in (st.get("centers") or {}).items()})
             for ph, st in game.state_history.items()]
    snaps.append((game.get_current_phase(),
                  {n: set(p.centers) for n, p in game.powers.items()}))
    years: dict[str, list[str]] = {}
    for (_, prev), (ph, cur) in zip(snaps, snaps[1:]):
        for name in sorted(cur):
            delta = ([f"+{c}" for c in sorted(cur[name] - prev.get(name, set()))]
                     + [f"−{c}" for c in sorted(prev.get(name, set()) - cur[name])])
            if delta:
                years.setdefault(ph[1:5], []).append(f"{name} {' '.join(delta)}")
    return "\n".join(f"- {y}: " + "; ".join(v) for y, v in sorted(years.items()))


def _orders_section(game: Game, power: str) -> str:
    """Every move each unit can make, written as the order itself, one per line.

    One order per line, in the exact syntax, because a model will copy a line
    from here into its answer; anything that is not itself an order (arrows,
    lists, annotations outside a # comment) comes back as an illegal order.
    """
    possible = game.get_all_possible_orders()
    locs = game.get_orderable_locations(power)
    if not locs:
        return "You have nothing to order this phase — just wait."
    occupied = _units_by_prov(game)
    owners = {c: p for p, pw in game.powers.items() for c in pw.centers}

    def note(order: str) -> str:
        """`# TURKEY centre, TURKEY A there`: what is in the destination."""
        if " - " not in order:
            return order
        dest = _base(order.split(" - ")[1].replace(" VIA", ""))
        what = []
        if dest in game.map.scs:
            owner = owners.get(dest)
            what.append("your centre" if owner == power else
                        f"{owner} centre" if owner else "neutral centre")
        hit = occupied.get(dest)
        what.append(f"{'your' if hit[0] == power else hit[0]} {hit[1].split()[0]} there"
                    if hit else "empty")
        return f"{order}   # {', '.join(what)}"

    lines = []
    if game.phase_type == "M":
        # Supports a unit could give each of your own moves, nested under the
        # move: "A BUD S A SER - BUL" goes under "A SER - BUL".
        backing: dict[str, list[str]] = {}
        for loc in locs:
            for o in possible.get(loc) or []:
                if " S " in o and " - " in o:
                    backing.setdefault(_no_coast(o.split(" S ", 1)[1]), []).append(o)
        for loc in locs:
            opts = possible.get(loc) or []
            moves = sorted(o for o in opts if (" - " in o and " S " not in o
                                               and " C " not in o) or o.endswith(" H"))
            for o in moves:
                lines.append(note(o))
                lines += [f"    {b}" for b in sorted(backing.get(_no_coast(o), []))]
            lines.append("")
        return ("Each line below is a complete legal order. After # is what is in the "
                "destination. Indented under a move are the supports your other units "
                "could give it; supports of holds and convoys use the forms below the "
                "list. Pick one order per unit:\n" + "\n".join(lines).rstrip())

    for loc in locs:
        lines += sorted(possible.get(loc) or []) + [""]
    if game.phase_type == "R":
        return ("Your dislodged units must retreat or disband. Each line is a "
                "complete order; pick one per unit:\n" + "\n".join(lines).rstrip())
    n = len(game.powers[power].centers) - len(game.powers[power].units)
    what = f"build up to {n}" if n > 0 else f"disband {-n}"
    return (f"Adjustments: you {what}. Each line is a complete order:\n"
            + "\n".join(lines).rstrip()
            + ("\nSubmit nothing to waive builds." if n > 0 else ""))


def _inbox(match: Match, power: str, limit: int = 40) -> str:
    msgs = match.inbox(power)
    if not msgs:
        return "_(no messages yet)_"
    lines = []
    for m in msgs[-limit:]:
        if m["sender"] == power:
            lines.append(f"- [{m['phase']}] you → {', '.join(m['to'])}: {m['body']}")
        else:
            to = "everyone" if ALL in m["to"] else (
                "you" if m["to"] == [power] else ", ".join(m["to"]))
            lines.append(f"- [{m['phase']}] {m['sender']} → {to}: {m['body']}")
    return "\n".join(lines)


def render(match: Match, power: str, *, inbox: bool = False,
           picture: str | None = None) -> str:
    """The board for `power` this phase, as markdown."""
    game = match.load()
    phase = game.get_current_phase()
    me = game.powers[power]
    press = "full press" if match.full_press else "gunboat (no messages)"
    out = [f"# {power} — {phase} — {match.name}, {press}"]
    if match.ended():
        out += ["", f"**GAME OVER — {match.ended()}.**", "", "## Final supply centres",
                _standings(game, power)]
        return "\n".join(out)
    if not me.units and not me.centers:
        out += ["", "You have been eliminated. Nothing more to do."]
        return "\n".join(out)

    sub = match.submitted(game)
    owing = match.owing(game)
    out += [
        f"Submitted this phase: {len([p for p in sub if p in owing])}/{len(owing)}"
        + (" (including you)" if power in sub else ""),
        "", "## You",
        f"- Units: {', '.join(me.units) or 'none'}",
        f"- Centres ({len(me.centers)}): {', '.join(sorted(me.centers)) or 'none'}",
    ]
    if notes := match.notes(power).strip():
        out += ["", "## Your notebook (only you see this)", notes]
    if not game.order_history and (lore := match.lore(power).strip()):
        out += ["", f"## Left by earlier players of {power}", lore[-LORE_SHOWN:]]
    out += [
        "", "## Your orders this phase", _orders_section(game, power), "", SYNTAX,
        "", f"## Supply centres ({len(game.map.scs)}; 18 wins)", _standings(game, power),
    ]
    out += ["", "## Everyone's units"] + [
        f"- {p}: {', '.join(game.powers[p].units) or 'none'}" for p in POWERS]
    out += ["", "## Last moves", _last_phase(match, game)]
    mine = _my_outcomes(match, game, power)
    if mine:
        out += ["", "## How your last orders went", mine]
    digest = _digest(game)
    if digest:
        out += ["", "## Centre changes by year", digest]
    if inbox and match.full_press:
        out += ["", "## Messages", _inbox(match, power)]
    if picture:
        out += ["", f"A picture of the board is at {picture}"]
    out += ["", "## Rules", RULES]
    return "\n".join(out)
