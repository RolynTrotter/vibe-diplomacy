"""Write a power's orders with Jev — one Choice per unit, all in one request.

Ordering a unit is a *selection* problem, not a generation problem:
`engine.validate.legal_orders` already enumerates every legal order for every
unit (6-16 at S1901M, 68 at the observed worst). That maps straight onto
TypeSafe's Choice primitive, whose answer is always one of the options you
supplied — so this can never emit a malformed or illegal single order.

v1 is deliberately **batch-only**: every unit is asked in one request, and
questions inside a request cannot see each other's answers. So nothing here
coordinates units. Supports that do not match their move, two units sent to the
same province, and unescorted convoys are all expected; they are legal orders
that simply fail to execute. `engine.coherence.check_orders` names each one, and
`choose_orders` returns those issues rather than hiding them — that report is
the evidence for whether a repair pass is worth building (issue #36).

Diplomatic context (inbox, standing commitments, the power's own notes) is
issue #37 and is not wired in here; `build_state` takes an `extra` mapping so it
can be added without reshaping this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from diplomacy import Game

from engine import coherence, jev, query, rules, validate

# Criteria are presented in this order. Dicts preserve insertion order, so this
# is the order Jev sees the options in: what the unit can do on its own first,
# then what it can do for someone else, then the fallback.
KIND_ORDER = ["MOVE", "SUP_M", "SUP_H", "CONVOY", "OTHER", "H"]


def _names(game: Game) -> dict[str, str]:
    """Province code -> readable name ('BUR' -> 'Burgundy')."""
    return {code.upper().split("/")[0]: full.title()
            for full, code in game.map.loc_name.items()}


def _unit_owners(game: Game) -> dict[str, tuple[str, str]]:
    """Base province -> (owning power, unit string)."""
    out: dict[str, tuple[str, str]] = {}
    for name, power in game.powers.items():
        for unit in power.units:
            out[unit.split()[1].split("/")[0].upper()] = (name, unit)
    return out


def _place(game: Game, prov: str, names: dict[str, str],
           owners: dict[str, tuple[str, str]], me: str) -> str:
    """A short factual description of a province: name, status, occupant."""
    label = names.get(prov, prov)
    bits = []
    if prov in game.map.scs:
        holder = query.owner_of_center(game, prov)
        if holder == me:
            bits.append("your supply centre")
        elif holder:
            bits.append(f"supply centre, owned by {holder}")
        else:
            bits.append("neutral supply centre")
    occupant = owners.get(prov)
    if occupant:
        who, unit = occupant
        bits.append(f"held by {'your' if who == me else who + chr(39) + 's'} {unit}")
    else:
        bits.append("empty")
    return f"{label} ({', '.join(bits)})"


def gloss(game: Game, order: str, names: dict[str, str],
          owners: dict[str, tuple[str, str]], me: str) -> str:
    """One line describing what an order does, in board terms.

    Option descriptions are what separate the options from each other, so these
    carry the facts a choice turns on: what is at the destination, who owns it,
    and whether the order depends on another unit cooperating.
    """
    p = coherence.parse_order(order)
    if p.kind == "MOVE":
        dest = _place(game, p.dest, names, owners, me)
        if p.via:
            return (f"Move to {dest} by sea. Requires a fleet chain ordered to "
                    f"convoy it this same turn; the move fails outright if any "
                    f"link is missing.")
        return f"Move to {dest}."
    if p.kind == "SUP_M":
        who = owners.get(p.target, ("", ""))[0]
        whose = "your" if who == me else (f"{who}'s" if who else "the")
        return (f"Support {whose} unit in {names.get(p.target, p.target)} as it "
                f"moves into {names.get(p.dest, p.dest)}.")
    if p.kind == "SUP_H":
        who = owners.get(p.target, ("", ""))[0]
        whose = "your" if who == me else (f"{who}'s" if who else "the")
        return (f"Support {whose} unit holding in "
                f"{_place(game, p.target, names, owners, me)}, helping it resist "
                f"being dislodged.")
    if p.kind == "CONVOY":
        who = owners.get(p.target, ("", ""))[0]
        whose = "your" if who == me else (f"{who}'s" if who else "the")
        return (f"Convoy {whose} army from {names.get(p.target, p.target)} to "
                f"{names.get(p.dest, p.dest)}.")
    if p.kind == "H":
        return f"Hold in {_place(game, p.loc, names, owners, me)}."
    return f"{order}."


def unit_questions(game: Game, power: str):
    """One Choice per orderable location, options grouped move/support/convoy/hold."""
    from typesafe_sdk import Choice

    power = power.upper()
    names, owners = _names(game), _unit_owners(game)
    legal = validate.legal_orders(game, power)
    unit_by_loc = {loc: unit for loc, (who, unit) in owners.items() if who == power}

    questions = {}
    for loc, opts in legal.items():
        ranked = sorted(
            opts,
            key=lambda o: (KIND_ORDER.index(coherence.parse_order(o).kind)
                           if coherence.parse_order(o).kind in KIND_ORDER
                           else len(KIND_ORDER), o),
        )
        criteria = {o: gloss(game, o, names, owners, power) for o in ranked}
        unit = unit_by_loc.get(loc, loc)
        questions[loc] = Choice(
            instructions=(
                f"You are {power}. Choose the order for your unit {unit} in "
                f"{names.get(loc, loc)} this turn. Weigh it against `your_position` "
                f"and `board`: take or defend supply centres, avoid bouncing your "
                f"own units, and prefer orders that do not depend on another power "
                f"cooperating unless that cooperation is clearly in their interest."
            ),
            criteria=criteria,
        )
    return questions


def board_graph(game: Game) -> dict:
    """The whole board as a graph: every province, what is in it, what it joins.

    Jev takes structured state, so the map goes in as data rather than as prose
    for it to reconstruct. Each province carries its terrain, supply-centre
    status and owner, the unit standing in it, and its neighbours — which is
    everything needed to see routes and pressure without us precomputing them.

    Coasts are collapsed onto their base province and `adjacent` is the union of
    both coasts' neighbours. Legality is not this structure's job: each unit's
    legal orders are enumerated in its own question, and those already respect
    coasts and terrain.
    """
    names = _names(game)
    owners = _unit_owners(game)
    home_of = {prov: power for power, provs in game.map.homes.items()
               for prov in provs}
    # Switzerland is impassable but still sits in the raw adjacency table, so
    # it has to be pruned from the edges or the graph offers routes through it.
    impassable = {l.upper().split("/")[0] for l in game.map.locs
                  if game.map.area_type(l.upper().split("/")[0]) == "SHUT"}
    graph: dict[str, dict] = {}
    for loc in game.map.locs:
        prov = loc.upper().split("/")[0]
        if prov in graph or game.map.area_type(prov) == "SHUT":
            continue
        entry = {
            "name": names.get(prov, prov),
            "terrain": game.map.area_type(prov),
            "adjacent": [a for a in query.adjacencies(game, prov)
                         if a.split("/")[0] not in impassable],
        }
        if prov in game.map.scs:
            entry["supply_center"] = True
            entry["owned_by"] = query.owner_of_center(game, prov) or "neutral"
            if prov in home_of:
                entry["home_of"] = home_of[prov]
        occupant = owners.get(prov)
        if occupant:
            entry["unit"] = f"{occupant[0]} {occupant[1]}"
        coasts = sorted(l.upper() for l in game.map.locs
                        if "/" in l and l.upper().split("/")[0] == prov)
        if coasts:
            entry["separate_coasts"] = coasts
        graph[prov] = entry
    return graph


def build_state(game: Game, power: str, *, root: Path | None = None,
                extra: dict | None = None) -> dict:
    """The board as Jev sees it.

    Text only — Jev accepts strings, objects and arrays of text, so the rendered
    board PNG from `engine.mapviz` has no path in here. `engine.context` already
    carries the same facts in words, which is what this reuses.
    """
    power = power.upper()
    summary = query.board_summary(game)
    state = {
        "rules_of_the_game": rules.FULL_RULES,
        "you_are": power,
        "phase": game.get_current_phase(),
        "phase_type": game.phase_type,
        "your_position": {
            "units": summary["powers"][power]["units"],
            "centers": summary["powers"][power]["centers"],
            "adjustment": summary["powers"][power]["adjustment"],
        },
        "board": {name: {"units": p["units"], "centers": p["centers"]}
                  for name, p in summary["powers"].items()},
        "supply_centre_counts": {name: p["center_count"]
                                 for name, p in summary["powers"].items()},
    }
    # The map itself, as data. Replaces the prose topology section: pathfinding
    # is left to Jev rather than precomputed into sentences.
    state["board_graph"] = board_graph(game)
    try:
        from engine import context
        state["your_legal_moves"] = context._tactical_annex(game, power)
    except Exception:
        pass  # each unit's own options are in its question regardless
    if extra:
        state.update(extra)          # issue #37 hangs notes and press here
    return state


@dataclass
class JevOrders:
    """What one batched request produced, with its own coherence report."""
    power: str
    phase: str
    orders: list[str] = field(default_factory=list)
    probabilities: dict[str, dict[str, float]] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    issues: list[coherence.Issue] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def coherent(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def report(self) -> str:
        lines = [f"{self.power} {self.phase} — {len(self.orders)} orders from Jev"]
        for o in self.orders:
            c = self.confidence.get(coherence.parse_order(o).loc)
            lines.append(f"  {o}" + (f"   (confidence {c:.2f})" if c is not None else ""))
        if self.errors:
            lines.append("Rejected by the engine:")
            lines += [f"  {e}" for e in self.errors]
        if self.issues:
            lines.append("Coherence:")
            lines.append(coherence.format_issues(self.issues))
        elif self.orders:
            lines.append("Coherence: clean.")
        return "\n".join(lines)


def choose_orders(game: Game, power: str, *, root: Path | None = None,
                  extra: dict | None = None, model: str = jev.DEFAULT_MODEL,
                  ask=None) -> JevOrders:
    """Ask Jev for this power's whole order set in one request.

    `ask` is injectable so the assembly logic can be tested without a network
    call; it defaults to `engine.jev.ask`.
    """
    power = power.upper()
    questions = unit_questions(game, power)
    result = JevOrders(power=power, phase=game.get_current_phase())
    if not questions:
        return result

    caller = ask or (lambda state, qs: jev.ask(state, qs, root=root, model=model))
    response = caller(build_state(game, power, root=root, extra=extra), questions)

    picked = []
    for loc in questions:
        answer = response.answers.get(loc)
        if answer is None:
            continue
        picked.append(answer.choice)
        result.probabilities[loc] = dict(getattr(answer, "probabilities", {}) or {})
        conf = getattr(answer, "confidence", None)
        if conf is not None:
            result.confidence[loc] = conf

    # Typed output guarantees the interface, not the truth: re-validate anyway.
    checked = validate.validate_orders(game, power, picked)
    result.orders = checked.accepted
    result.errors = checked.errors
    result.issues = coherence.check_orders(game, power, checked.accepted)
    usage = getattr(response, "usage", None)
    if usage is not None:
        result.usage = {"input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None)}
    return result
