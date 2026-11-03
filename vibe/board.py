"""The board as one power sees it, in plain text.

Everything here is either public (positions, centre counts, last phase's
orders) or belongs to `power` (its legal moves, its inbox). It is the whole of
what a seat needs to play a phase, so a seat never has to look anywhere else.
All geometry comes from the engine, so none of it can drift from the rules.
"""
from __future__ import annotations

from diplomacy import Game

from vibe.game import ALL, POWERS, Match

SYNTAX = (
    "Order syntax: `A PAR - BUR` move · `A PAR H` hold · `A MAR S A PAR - BUR` "
    "support a move · `A MUN S A BER` support a hold · `F ENG C A LON - BRE` "
    "convoy, with `A LON - BRE VIA` · retreat `A BUR R PIC` · disband `A BUR D` "
    "· build `A PAR B` / `F BRE B`. Units you don't order hold."
)

RULES = (
    "- Supply centres change hands only when a unit is in them after a Fall "
    "turn; each winter you build or disband to match your centre count.\n"
    "- A support only counts if the supported unit makes exactly that move; it "
    "is cut if the supporter is attacked (except from where it is supporting "
    "into).\n"
    "- 18 centres wins outright."
)


def _base(prov: str) -> str:
    return prov.upper().split("/")[0]


def _units_by_prov(game: Game) -> dict[str, tuple[str, str]]:
    return {_base(u.split()[1]): (name, u)
            for name, p in game.powers.items() for u in p.units}


def _neighbours(game: Game, prov: str) -> set[str]:
    abut = game.map.loc_abut.get(prov) or game.map.loc_abut.get(prov.lower()) or []
    return {_base(a) for a in abut} - {_base(prov)}


def _standings(game: Game, power: str) -> str:
    rows = sorted(POWERS, key=lambda p: -len(game.powers[p].centers))
    return "\n".join(
        f"- {p}: {len(game.powers[p].centers)} centres, {len(game.powers[p].units)} units"
        + (" ← you" if p == power else "") for p in rows)


def _last_phase(match: Match, game: Game) -> str:
    phases = list(game.order_history.keys())
    if not phases:
        return "_(nothing yet — this is the opening.)_"
    hist = match.history(str(phases[-1])) or {}
    lines = [f"_{phases[-1]}:_"]
    for p, orders in sorted((hist.get("orders") or {}).items()):
        if orders:
            lines.append(f"- {p}: {', '.join(orders)}")
    results = hist.get("results") or {}
    if results:
        lines.append("Results: " + "; ".join(f"{u} {', '.join(r)}"
                                              for u, r in sorted(results.items())))
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
        if not bad:
            return f"All {len(mine)} of your {phase} orders succeeded."
        return f"_{phase}:_ {len(mine) - len(bad)} succeeded, these did not:\n" + "\n".join(bad)
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
    possible = game.get_all_possible_orders()
    locs = game.get_orderable_locations(power)
    if not locs:
        return "You have nothing to order this phase — just wait."
    occupied = _units_by_prov(game)

    def tag(dest: str) -> str:
        hit = occupied.get(_base(dest))
        if not hit:
            return dest
        return f"{dest} ({'your' if hit[0] == power else hit[0]} {hit[1].split()[0]})"

    if game.phase_type == "M":
        me = game.powers[power]
        lines = []
        for loc in locs:
            unit = next((u for u in me.units if _base(u.split()[1]) == _base(loc)), loc)
            dests = sorted({o.split(" - ")[1].replace(" VIA", "")
                            for o in possible.get(loc) or []
                            if " - " in o and " S " not in o and " C " not in o})
            lines.append(f"- {unit} → {', '.join(tag(d) for d in dests) or '(nowhere)'}")
        return ("Where each of your units can move (supports and convoys also "
                "allowed — see syntax):\n" + "\n".join(lines))

    lines = [f"- {loc}: {', '.join(sorted(possible.get(loc) or []))}" for loc in locs]
    if game.phase_type == "R":
        return "Your dislodged units must retreat or disband:\n" + "\n".join(lines)
    n = len(game.powers[power].centers) - len(game.powers[power].units)
    what = f"build up to {n}" if n > 0 else f"disband {-n}"
    return (f"Adjustments: you {what}. Options:\n" + "\n".join(lines)
            + ("\nSubmit nothing to waive builds." if n > 0 else ""))


def _surroundings(game: Game, power: str) -> str:
    """Who you border, and the centres you don't own within three moves."""
    me = game.powers[power]
    ground = {_base(u.split()[1]) for u in me.units} | {_base(c) for c in me.centers}
    if not ground:
        return ""
    occupied = _units_by_prov(game)
    touch: dict[str, set[str]] = {}
    for prov in ground:
        for n in _neighbours(game, prov):
            hit = occupied.get(n)
            if hit and hit[0] != power:
                touch.setdefault(hit[0], set()).add(n)
    out = ["Foreign units next to your ground: "
           + ("; ".join(f"{p} at {', '.join(sorted(v))}" for p, v in sorted(touch.items()))
              or "none")]

    seen = {p: 0 for p in ground}
    frontier = set(ground)
    for hop in (1, 2, 3):
        frontier = {n for p in frontier for n in _neighbours(game, p)} - set(seen)
        for n in frontier:
            seen[n] = hop
    owners = {_base(c): n for n, p in game.powers.items() for c in p.centers}
    targets = sorted((h, p) for p, h in seen.items()
                     if p in game.map.scs and p not in me.centers)[:10]
    if targets:
        out.append("Centres you don't own, nearest first (moves away): " + ", ".join(
            f"{p} ({owners.get(p, 'neutral')}, {h})" for h, p in targets))
    return "\n".join(out)


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
           notes: bool = False, picture: str | None = None) -> str:
    """The board for `power` this phase, as markdown."""
    game = match.load()
    phase = game.get_current_phase()
    me = game.powers[power]
    press = "full press" if match.full_press else "gunboat (no messages)"
    out = [f"# {power} — {phase} — {match.name}, {press}"]
    if match.ended():
        out += ["", f"**GAME OVER — {match.ended()}.**", "", "## Final standings",
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
        "", "## Your orders this phase", _orders_section(game, power),
        "", "## Standings", _standings(game, power),
    ]
    surroundings = _surroundings(game, power)
    if surroundings:
        out += ["", "## Around you", surroundings]
    out += ["", "## Everyone's units"] + [
        f"- {p}: {', '.join(game.powers[p].units) or 'none'}" for p in POWERS]
    out += ["", "## Last phase", _last_phase(match, game)]
    mine = _my_outcomes(match, game, power)
    if mine:
        out += ["", "## How your last orders went", mine]
    digest = _digest(game)
    if digest:
        out += ["", "## Centre changes by year", digest]
    if inbox and match.full_press:
        out += ["", "## Messages", _inbox(match, power)]
    if notes:
        out += ["", "## Your notes", match.notes(power).strip() or "_(none yet)_"]
    if picture:
        out += ["", f"A picture of the board is at {picture}"]
    out += ["", SYNTAX, "", RULES]
    return "\n".join(out)
