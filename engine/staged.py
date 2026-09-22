"""Decide who moves before deciding what anyone does.

The batch-only path in `engine.orders_jev` asks every unit for a whole order in
one shot. Played out over a game that froze: supports outnumber moves as
options, so aggregate selection kept picking them, mutual support is a stable
fixed point, and by 1902 the board never changed again — Italy submitted the
same three orders twelve phases running.

This path fixes the order of decisions rather than the weights. Movement is
settled first, over subsets of units, and supports are offered only to units
that already lost that decision. Supports cannot crowd out moves because they
are not on the same ballot.

Per power, per movement phase:

  1. which armies move   Choice over subsets of armies (groups of <= 6)
  2. army destinations   one Choice per moving army, all in one request
  3. which fleets move   Choice over subsets, with stage 2's orders in state
  4. fleet destinations  one Choice per moving fleet
  5. the rest            support or convoy; hold only where nothing is legal

Fleets decide after armies have real destinations, which is what makes a
convoy reachable: a fleet can see `A LON - NWY VIA` already committed and
stay put to carry it.

Subsets are asked as whole combinations because the commonest decision on the
board is exclusive: which of two units attacks and which supports it. Only a
question over combinations can say "Moscow or Warsaw, not both".

The instructions state mechanics and nothing else. They used to editorialise —
"a unit that does not move is still useful, it can support or convoy one
that does", and "back up one that is" — and that advice was worth 0.05 of
probability against moving at S1901M, measured by ablation on the fleet
question that kept Brest at home. Boilerplate that tells the model what is
worth doing is a thumb on the scale wearing the costume of a hint; the numbers
in the state are where a preference belongs.

Per-unit marginals are logged for inspection and nothing reads them. They are
recorded because they are free, not because they are a decision rule — on that
same exclusive pairing, `{Mos}` at 0.48 against `{War}` at 0.47 marginalises to
0.48 and 0.47, and every threshold over that is wrong: above it neither unit
moves, below it both do and bounce. The chosen combination is the answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from diplomacy import Game

from engine import coherence, jev, orders_jev, press, query, validate

#: Units per subset question. 2**6 = 64 options, well inside the 255 ceiling.
#: Every split costs joint reasoning, so this is as high as it goes while
#: keeping the fallback ladder tidy: 12 units is two groups, 18 is three.
GROUP_CAP = 6
NONE_KEY = "NONE"


@dataclass
class Stage:
    """One decision, kept for inspection afterwards."""
    name: str
    picked: str = ""
    marginals: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    tokens: int = 0


def _units_by_kind(game: Game, power: str) -> tuple[list[str], list[str]]:
    """This power's orderable locations, armies first then fleets."""
    legal = validate.legal_orders(game, power)
    armies, fleets = [], []
    for loc in legal:
        unit = next((u for u in game.powers[power.upper()].units
                     if u.split()[1].split("/")[0] == loc), "")
        (armies if unit.startswith("A") else fleets).append(loc)
    return sorted(armies), sorted(fleets)


def _groups(locs: list[str], cap: int = GROUP_CAP) -> list[list[str]]:
    """Split into chunks small enough to enumerate every subset of."""
    return [locs[i:i + cap] for i in range(0, len(locs), cap)] or []


def _english(items: list[str]) -> str:
    """"A", "A and B", "A, B and C" — a list a reader can parse as a sentence."""
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _subset_options(locs: list[str], unit_of: dict[str, str]) -> dict[str, str]:
    """Every subset of these units, as Choice options.

    Each option is two plain sentences: who moves, and who stays. An earlier
    version read "F BRE out of Brest advances. Staying put and free to support
    or convoy: no others." — which names Brest twice (the unit token already
    says where it is), uses a word the rules do not ("advance"; the order is a
    move), and ends in a label-colon-list that degenerates into "no others"
    when nothing stays behind. Options are compared by reading them, so an
    option that has to be decoded is an option at a disadvantage.

    The empty subset is offered. Sitting still for a phase is a real decision,
    especially in a late-game stalemate — which is also exactly where a power
    has too many units to ask about at once.
    """
    options: dict[str, str] = {}
    # Largest first: everything moving leads, nobody moving comes last. Option
    # order measurably biases the answer — putting hold at the head of a unit's
    # options pushed the hold rate from 13/22 to 17/22 — so the passive end of
    # the ballot does not get the primacy slot.
    for size in range(len(locs), -1, -1):
        for combo in combinations(locs, size):
            key = ",".join(combo) if combo else NONE_KEY
            if not combo:
                options[key] = ("No unit moves. Each one can support, convoy "
                                "or hold instead.")
                continue
            movers = _english([unit_of[l] for l in combo])
            moves = "moves" if len(combo) == 1 else "move"
            stays = [unit_of[l] for l in locs if l not in combo]
            text = f"{movers} {moves}."
            if stays:
                text += (f" {_english(stays)} {'stays' if len(stays) == 1 else 'stay'}"
                         f", and can support, convoy or hold instead.")
            options[key] = text
    return options


def _unit_digest(game: Game, power: str, locs: list[str],
                 values: dict[str, float] | None,
                 names: dict[str, str], impassable: set[str]) -> list[dict]:
    """A table: one row per move any of these units could make.

    Columns are what the decision turns on, already reduced to marginals —
    what standing there would *win* you, not what exists there. An earlier
    version summarised each destination in prose and dropped whether it was a
    centre you would capture, and a version before that reported absolutes, so
    four French-owned neighbours outscored one free centre.

    Every number here comes from `orders_jev.gain_of`, the same function the
    option glosses use, so the table and the options cannot disagree.
    """
    owners = orders_jev._unit_owners(game)
    legal = validate.legal_orders(game, power)
    rows: list[dict] = []
    for loc in locs:
        unit = next((u for u in game.powers[power.upper()].units
                     if u.split()[1].split("/")[0] == loc), loc)
        for order in legal.get(loc, []):
            p = coherence.parse_order(order)
            if p.kind != "MOVE":
                continue
            takes, borders = orders_jev.gain_of(game, p.dest, power, impassable)
            row = {"unit": unit, "order": order, "to": names.get(p.dest, p.dest),
                   "new_centres": takes, "borders_not_yours": borders}
            occupant = owners.get(p.dest)
            if occupant:
                row["defended_by"] = f"{occupant[0]} {occupant[1]}"
            if p.via:
                row["needs_convoy"] = True
            if values is not None:
                row["priority"] = values.get(p.dest, 0)
            rows.append(row)
        takes, borders = orders_jev.gain_of(game, loc, power, impassable)
        rows.append({"unit": unit, "order": f"{unit} H", "to": names.get(loc, loc),
                     "new_centres": takes, "borders_not_yours": borders,
                     "staying_put": True})
    return rows


def _marginals(locs: list[str], probabilities: dict[str, float]) -> dict[str, float]:
    """P(this unit moves), summed over every subset containing it.

    Diagnostic only — see the module docstring. Never use this to decide which
    units move: it discards the exclusivity that the subset question exists to
    capture.
    """
    out = {}
    for loc in locs:
        out[loc] = round(sum(
            p for key, p in probabilities.items()
            if key != NONE_KEY and loc in key.split(",")), 4)
    return out


def _movers_from(game: Game, power: str, locs: list[str], kind: str,
                 state: dict, *, ask, stages: list[Stage]) -> list[str]:
    """Ask which of these units move, in groups small enough to enumerate."""
    from typesafe_sdk import Choice

    unit_of = {l: next((r["unit"] for r in state["your_units"]
                        if r["unit"].split()[1].split("/")[0] == l), l) for l in locs}
    movers: list[str] = []
    for index, group in enumerate(_groups(locs)):
        question = Choice(
            instructions=(
                f"You are {power}. Decide which of these {kind} move this turn. "
                f"Each unit's options are in `your_units`; anything already "
                f"ordered is in `committed_orders`. Your own plan is in "
                f"`your_own_plan`; agreements you are bound by this turn are in "
                f"`deal_policy_this_turn`. Choose the combination that does most "
                f"for your position."),
            criteria=_subset_options(group, unit_of),
        )
        key = f"{kind}_group_{index}"
        response = ask(state, {key: question})
        answer = response.answers[key]
        probs = dict(answer.probabilities or {})
        stages.append(Stage(name=key, picked=answer.choice,
                            marginals=_marginals(group, probs),
                            confidence=answer.confidence,
                            tokens=getattr(response.usage, "input_tokens", 0) or 0))
        if answer.choice != NONE_KEY:
            movers += [l for l in answer.choice.split(",") if l in group]
    return movers


def _destinations(game: Game, power: str, movers: list[str], state: dict, kind: str,
                  values: dict[str, float] | None, *, ask, stages: list[Stage],
                  taken: set[str] | None = None,
                  forbid: set[str] | None = None) -> tuple[list[str], list[str]]:
    """One Choice per moving unit, over its legal moves only.

    The questions run in one request and cannot see each other, so two units
    can pick the same province — a self-bounce that wastes both. Rather than
    spend a second round trip, the answers carry a probability for every
    option: a unit that loses a contested destination takes its best remaining
    one. A unit with nothing left is demoted to the supporting group.

    Returns (orders, demoted locations).
    """
    from typesafe_sdk import Choice

    if not movers:
        return [], []
    taken = set(taken or ())
    names, owners = orders_jev._names(game), orders_jev._unit_owners(game)
    impassable = {l.upper().split("/")[0] for l in game.map.locs
                  if game.map.area_type(l.upper().split("/")[0]) == "SHUT"}
    legal = validate.legal_orders(game, power)
    questions = {}
    for loc in movers:
        moves = [o for o in legal.get(loc, [])
                 if coherence.parse_order(o).kind == "MOVE"
                 and coherence.parse_order(o).dest not in (forbid or set())]
        if not moves:
            continue
        questions[loc] = Choice(
            instructions=(f"You are {power}. This unit is moving this turn. "
                          f"Where does it go? Avoid a province another of your "
                          f"units is already ordered into — see `committed_orders`, "
                          f"and do not enter ground a deal you are keeping puts "
                          f"off limits (`deal_policy_this_turn`)."),
            criteria={o: orders_jev.gloss(game, o, names, owners, power,
                                          impassable, values) for o in moves},
        )
    if not questions:
        return [], []
    response = ask(state, questions)

    ranked = {}
    for loc in questions:
        answer = response.answers.get(loc)
        if answer is None:
            continue
        probs = dict(answer.probabilities or {})
        order = sorted(probs, key=lambda o: -probs[o]) or [answer.choice]
        ranked[loc] = (answer, order)

    # Settle contested destinations by confidence: the surest unit keeps it.
    chosen, demoted = [], []
    for loc, (answer, order) in sorted(
            ranked.items(), key=lambda kv: -(kv[1][0].confidence or 0)):
        pick = next((o for o in order
                     if coherence.parse_order(o).dest not in taken), None)
        if pick is None:
            demoted.append(loc)
            stages.append(Stage(name=f"{kind}_dest_{loc}", picked="(demoted)"))
            continue
        taken.add(coherence.parse_order(pick).dest)
        chosen.append(pick)
        stages.append(Stage(
            name=f"{kind}_dest_{loc}", picked=pick,
            confidence=answer.confidence)
            if pick == answer.choice else Stage(
            name=f"{kind}_dest_{loc}", picked=f"{pick} (2nd; {answer.choice} taken)",
            confidence=answer.confidence))
    return chosen, demoted


def _helpers(game: Game, power: str, stayers: list[str], state: dict,
             values: dict[str, float] | None, *, ask, stages: list[Stage],
             sealed: set[str] | None = None) -> list[str]:
    """Supports and convoys for the units that are not moving.

    Hold is offered only where the unit has no legal support or convoy at all.
    """
    from typesafe_sdk import Choice

    if not stayers:
        return []
    names, owners = orders_jev._names(game), orders_jev._unit_owners(game)
    impassable = {l.upper().split("/")[0] for l in game.map.locs
                  if game.map.area_type(l.upper().split("/")[0]) == "SHUT"}
    legal = validate.legal_orders(game, power)
    mine = {coherence.parse_order(o).loc: coherence.parse_order(o)
            for o in state.get("committed_orders", [])}
    ours = {u.split()[1].split("/")[0] for u in game.powers[power].units}

    def useful(order: str) -> bool:
        """Drop supports that cannot work against the orders already given.

        A support for a move nobody is making, or a hold-support for a unit
        that is leaving, is a wasted unit. We know both for our own units, so
        those options never reach the model. Foreign units stay on offer — we
        cannot see their orders, and backing one is a legitimate gamble.
        """
        p = coherence.parse_order(order)
        # A demilitarised province stays off limits when you are helping
        # somebody else in — escorting a rival through a DMZ is not honouring
        # it. A province PROMISED to another power is the opposite case: the
        # support is the thing you agreed to give, so it stays on the ballot.
        if p.dest and p.dest in (sealed or set()):
            return False
        if p.target not in ours:
            return True
        committed = mine.get(p.target)
        if p.kind == "SUP_H":
            return committed is None or committed.kind != "MOVE"
        if p.kind in ("SUP_M", "CONVOY"):
            return (committed is not None and committed.kind == "MOVE"
                    and committed.dest == p.dest
                    and (committed.via if p.kind == "CONVOY" else True))
        return True

    questions = {}
    for loc in stayers:
        opts = [o for o in legal.get(loc, [])
                if coherence.parse_order(o).kind in ("SUP_M", "SUP_H", "CONVOY")
                and useful(o)]
        if not opts:
            opts = [o for o in legal.get(loc, [])
                    if coherence.parse_order(o).kind == "H"]
        if not opts:
            continue
        questions[loc] = Choice(
            instructions=(f"You are {power}. This unit is not moving this turn. "
                          f"Choose what it does instead. `committed_orders` lists "
                          f"the moves your other units are making. A support only "
                          f"takes effect if it matches an order actually given, "
                          f"and a convoy only if that army is moving by sea."),
            criteria={o: orders_jev.gloss(game, o, names, owners, power,
                                          impassable, values) for o in opts},
        )
    if not questions:
        return []
    response = ask(state, questions)
    chosen = []
    for loc in questions:
        answer = response.answers.get(loc)
        if answer is None:
            continue
        chosen.append(answer.choice)
        stages.append(Stage(name=f"help_{loc}", picked=answer.choice,
                            confidence=answer.confidence))
    return chosen


def choose_orders_staged(game: Game, power: str, *, root: Path | None = None,
                         values: dict[str, float] | None = None,
                         model: str = jev.DEFAULT_MODEL,
                         extra: dict | None = None, stab: bool = False,
                         forbid: set[str] | None = None,
                         sealed: set[str] | None = None,
                         ask=None) -> orders_jev.JevOrders:
    """Movement first, then destinations, then everyone else.

    `extra` is pinned onto the state for every stage. With `stab`, each standing
    `DEAL:` line is decided keep-or-break once, before any unit is asked, and
    the verdicts ride along in `deal_policy_this_turn` — see `engine.press`.

    `forbid` is every province this power's own units may not enter; `sealed`
    is the subset that must stay empty altogether, so supports and convoys
    carrying somebody else in are dropped too. A province in `forbid` but not
    `sealed` is one the power promised to a friend: it stays out, and helping
    the friend in is exactly what it agreed to do. Both come from
    `engine.valuation.province_constraints`.
    """
    power = power.upper()
    result = orders_jev.JevOrders(power=power, phase=game.get_current_phase())

    if game.phase_type != "M":
        # Retreats and adjustments are one decision per location with no
        # move/support division to make; the single-pass path handles them.
        return orders_jev.choose_orders(game, power, root=root, values=values,
                                        model=model, extra=extra, ask=ask)

    caller = ask or (lambda s, q: jev.ask(s, q, root=root, model=model))
    armies, fleets = _units_by_kind(game, power)
    if not armies and not fleets:
        return result

    impassable = {l.upper().split("/")[0] for l in game.map.locs
                  if game.map.area_type(l.upper().split("/")[0]) == "SHUT"}
    names = orders_jev._names(game)
    state = orders_jev.build_state(game, power, root=root, extra=extra)
    if stab:
        deals = press.standing_deals(root, power) if root is not None else []
        policy = press.stab_policy(deals, state, ask=caller)
        if policy:
            state["deal_policy_this_turn"] = policy
            result.deal_policy = policy
    state["what_your_units_can_do"] = _unit_digest(
        game, power, armies + fleets, values, names, impassable)
    state["your_units"] = state["what_your_units_can_do"]
    state["committed_orders"] = []
    stages: list[Stage] = []
    orders: list[str] = []

    army_movers = _movers_from(game, power, armies, "armies", state,
                               ask=caller, stages=stages)
    army_orders, demoted = _destinations(game, power, army_movers, state, "army",
                                         values, ask=caller, stages=stages,
                                         forbid=forbid)
    orders += army_orders
    state["committed_orders"] = list(orders)
    army_movers = [l for l in army_movers if l not in demoted]

    fleet_movers = _movers_from(game, power, fleets, "fleets", state,
                                ask=caller, stages=stages)
    taken = {coherence.parse_order(o).dest for o in orders}
    fleet_orders, demoted = _destinations(game, power, fleet_movers, state, "fleet",
                                          values, ask=caller, stages=stages,
                                          taken=taken, forbid=forbid)
    orders += fleet_orders
    state["committed_orders"] = list(orders)
    fleet_movers = [l for l in fleet_movers if l not in demoted]

    stayers = [l for l in armies + fleets
               if l not in army_movers and l not in fleet_movers]
    orders += _helpers(game, power, stayers, state, values,
                       ask=caller, stages=stages, sealed=sealed)

    checked = validate.validate_orders(game, power, orders)
    result.orders = checked.accepted
    result.errors = checked.errors
    result.issues = coherence.check_orders(game, power, checked.accepted)
    result.stages = stages
    tokens = sum(s.tokens for s in stages)
    result.usage = {"input_tokens": tokens, "output_tokens": 0,
                    "cost_usd": jev.cost_usd(tokens)}
    return result
