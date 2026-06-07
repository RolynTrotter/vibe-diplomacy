"""Tactical order suggestions — the contract behind the run-cicero skill.

The interface is fixed so real Cicero can be dropped in later with no change
upstream:

    suggest(game, power, order_history=None, engine="heuristic") -> Suggestion

`engine="heuristic"` ships now: a fast, comms-blind greedy suggester that
favours capturing supply centers and otherwise holds. `engine="cicero"` is a
stretch (Epic 6) — same signature, real model behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from diplomacy import Game


@dataclass
class Suggestion:
    orders: list[str] = field(default_factory=list)
    rationale: dict[str, str] = field(default_factory=dict)  # location -> why
    engine: str = "heuristic"


def _destination(order: str) -> str | None:
    """Destination province of a move order, else None."""
    parts = order.split()
    if "-" in parts:
        i = parts.index("-")
        if i + 1 < len(parts):
            return parts[i + 1].split("/")[0]
    return None


def _heuristic(game: Game, power: str) -> Suggestion:
    power = power.upper()
    possible = game.get_all_possible_orders()
    own_centers = set(game.get_power(power).centers)
    all_centers = set(game.map.scs)

    suggestion = Suggestion(engine="heuristic")
    for loc in game.get_orderable_locations(power):
        options = possible.get(loc) or []
        if not options:
            continue

        best, best_score, why = None, -1, "hold"
        for order in options:
            dest = _destination(order)
            score, reason = 0, "hold/other"
            if dest in all_centers and dest not in own_centers:
                # Capturing a center we don't own is the whole game.
                score, reason = 3, f"move on supply center {dest}"
            elif dest in all_centers and dest in own_centers:
                score, reason = 1, f"reposition toward own center {dest}"
            elif dest is not None:
                score, reason = 2, f"advance to {dest}"
            elif order.endswith(" H"):
                score, reason = 0, "hold"
            if score > best_score:
                best, best_score, why = order, score, reason

        if best is None:
            best = options[0]
        suggestion.orders.append(best)
        suggestion.rationale[loc] = why
    return suggestion


def suggest(
    game: Game,
    power: str,
    order_history: list | None = None,
    engine: str = "heuristic",
) -> Suggestion:
    """Suggest a full set of legal orders for `power` this phase.

    `order_history` (public, from history/) is accepted for parity with the
    real Cicero interface; the heuristic engine does not yet use it.
    """
    if engine == "heuristic":
        return _heuristic(game, power)
    raise NotImplementedError(
        f"Suggestion engine {engine!r} is not wired yet (see Epic 6: real Cicero)."
    )
