"""Order validation with readable, per-order feedback.

The engine's `set_orders` silently drops illegal orders, which is useless for
a player trying to fix a mistake. Instead we validate each order against the
engine's own enumeration of every legal order for the phase
(`get_all_possible_orders`), restricted to the locations the power may order.
That enumeration is the ground truth for legality, so membership in it (after
normalizing whitespace/dashes) is both correct and complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from diplomacy import Game


def normalize(order: str) -> str:
    """Canonicalize an order string for comparison.

    Upper-cases, pads dashes with spaces, and collapses whitespace so that
    "A PAR-BUR", "a par - bur" and "A PAR  -  BUR" all compare equal to the
    engine's canonical "A PAR - BUR".
    """
    text = order.upper().strip()
    text = text.replace("-", " - ")
    text = re.sub(r"\s+", " ", text)
    return text


def _order_location(order: str) -> str:
    """The province an order acts on (token after the unit type)."""
    parts = normalize(order).split()
    if len(parts) >= 2 and parts[0] in ("A", "F"):
        return parts[1].split("/")[0]
    return parts[0].split("/")[0] if parts else ""


def legal_orders(game: Game, power: str) -> dict[str, list[str]]:
    """Map of orderable location -> canonical legal orders for `power`."""
    power = power.upper()
    possible = game.get_all_possible_orders()
    orderable = game.get_orderable_locations(power)
    result: dict[str, list[str]] = {}
    for loc in orderable:
        opts = possible.get(loc) or possible.get(loc.upper()) or []
        if opts:
            result[loc.split("/")[0]] = sorted(opts)
    return result


@dataclass
class ValidationResult:
    accepted: list[str] = field(default_factory=list)   # canonical order strings
    errors: list[str] = field(default_factory=list)     # human-readable messages

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_orders(game: Game, power: str, orders: list[str]) -> ValidationResult:
    """Validate `orders` for `power` against the current phase.

    Returns accepted canonical orders and a readable error per rejected order.
    """
    power = power.upper()
    legal = legal_orders(game, power)
    legal_set = {normalize(o): o for opts in legal.values() for o in opts}

    result = ValidationResult()
    for raw in orders:
        if not raw or not raw.strip():
            continue
        norm = normalize(raw)
        if norm in legal_set:
            result.accepted.append(legal_set[norm])
            continue
        loc = _order_location(raw)
        hint = legal.get(loc)
        if hint:
            result.errors.append(
                f"Illegal order {raw!r}. Legal orders for {loc}: {hint}"
            )
        elif loc not in legal:
            result.errors.append(
                f"Illegal order {raw!r}: {power} has no orderable unit at "
                f"{loc!r} this phase. Orderable: {sorted(legal)}"
            )
        else:
            result.errors.append(f"Illegal order {raw!r}.")
    return result
