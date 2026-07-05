"""Order-SET coherence — catch orders that are provably wasted.

`validate.py` answers "is each order individually legal?"; this module answers
"do these orders make sense *together*?". Past games show why that matters: in
game/lm-studio-1, 51% of all orders were supports for moves nobody ordered and
another 11% were convoyed moves with no convoy — every one individually legal.

Issues come in two severities:

* **error** — provably wasted using only this power's own order set (e.g.
  supporting your own unit's move when you didn't order that move). There is
  no scenario where the order does anything; submit_orders rejects these so
  the player gets a fix-it message instead of a silently void order.
* **warning** — depends on another power's simultaneous order (cross-power
  support/convoy) or is a legal-but-unusual tactic (self-bounce). Printed so
  the player sees the dependency spelled out, but accepted.

Only movement phases are checked; retreat/adjustment sets have no
inter-order dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass

from diplomacy import Game


@dataclass
class Issue:
    severity: str   # "error" | "warning"
    order: str      # the offending canonical order
    message: str

    def __str__(self) -> str:
        return f"{self.order}: {self.message}"


def _base(province: str) -> str:
    return province.upper().split("/")[0]


def _unit_owners(game: Game) -> dict[str, str]:
    """Base province of every unit on the board -> owning power."""
    owners = {}
    for name, power in game.powers.items():
        for unit in power.units:
            owners[_base(unit.split()[1])] = name
    return owners


@dataclass
class _Parsed:
    raw: str
    kind: str            # H | MOVE | SUP_H | SUP_M | CONVOY | OTHER
    loc: str = ""        # acting unit's base province
    dest: str = ""       # move/support/convoy destination (base)
    target: str = ""     # supported/convoyed unit's base province
    via: bool = False


def _parse(order: str) -> _Parsed:
    """Parse a canonical engine order string (movement phases only)."""
    tokens = order.upper().split()
    if len(tokens) < 2 or tokens[0] not in ("A", "F"):
        return _Parsed(raw=order, kind="OTHER")
    loc = _base(tokens[1])
    rest = tokens[2:]
    if not rest or rest == ["H"]:
        return _Parsed(raw=order, kind="H", loc=loc)
    if rest[0] == "S":
        # S A MAR  |  S A MAR - BUR
        if "-" in rest:
            i = rest.index("-")
            return _Parsed(raw=order, kind="SUP_M", loc=loc,
                           target=_base(rest[i - 1]), dest=_base(rest[i + 1]))
        return _Parsed(raw=order, kind="SUP_H", loc=loc, target=_base(rest[-1]))
    if rest[0] == "C":
        i = rest.index("-")
        return _Parsed(raw=order, kind="CONVOY", loc=loc,
                       target=_base(rest[i - 1]), dest=_base(rest[i + 1]))
    if rest[0] == "-":
        via = tokens[-1] == "VIA"
        dest = tokens[-2] if via else tokens[-1]
        return _Parsed(raw=order, kind="MOVE", loc=loc, dest=_base(dest), via=via)
    return _Parsed(raw=order, kind="OTHER", loc=loc)


def check_orders(game: Game, power: str, orders: list[str]) -> list[Issue]:
    """Coherence-check an accepted (already legal) order set for one power."""
    if game.phase_type != "M":
        return []
    power = power.upper()
    owners = _unit_owners(game)
    parsed = [_parse(o) for o in orders]
    mine = {p.loc: p for p in parsed if p.loc}
    issues: list[Issue] = []

    def moves_exactly(unit_loc: str, dest: str) -> bool:
        p = mine.get(unit_loc)
        return p is not None and p.kind == "MOVE" and p.dest == dest

    foreign_fleet_at_sea = any(
        unit.startswith("F ")
        and game.map.area_type(_base(unit.split()[1])) == "WATER"
        for name, pw in game.powers.items() if name != power
        for unit in pw.units
    )

    for p in parsed:
        if p.kind == "SUP_M":
            owner = owners.get(p.target)
            if owner == power:
                if not moves_exactly(p.target, p.dest):
                    actual = mine.get(p.target)
                    did = f"you ordered {actual.raw!r}" if actual else \
                        f"you gave {p.target} no order"
                    issues.append(Issue(
                        "error", p.raw,
                        f"void support — it needs your own order "
                        f"'{p.target} - {p.dest}', but {did}. Either order that "
                        f"move or change this support."))
            elif owner:
                issues.append(Issue(
                    "warning", p.raw,
                    f"assumes {owner} orders {p.target} - {p.dest} this phase; "
                    f"void otherwise."))
        elif p.kind == "SUP_H":
            owner = owners.get(p.target)
            if owner == power:
                actual = mine.get(p.target)
                if actual is not None and actual.kind == "MOVE":
                    issues.append(Issue(
                        "error", p.raw,
                        f"void support-hold — you ordered {actual.raw!r}, and a "
                        f"unit ordered to move cannot receive hold support."))
        elif p.kind == "CONVOY":
            owner = owners.get(p.target)
            if owner == power:
                actual = mine.get(p.target)
                if not (actual is not None and actual.kind == "MOVE"
                        and actual.dest == p.dest and actual.via):
                    did = f"you ordered {actual.raw!r}" if actual else \
                        f"you gave {p.target} no order"
                    issues.append(Issue(
                        "error", p.raw,
                        f"void convoy — it needs your own order "
                        f"'A {p.target} - {p.dest} VIA', but {did}."))
            elif owner:
                issues.append(Issue(
                    "warning", p.raw,
                    f"assumes {owner} orders A {p.target} - {p.dest} VIA; "
                    f"void otherwise."))
        elif p.kind == "MOVE" and p.via:
            convoyed = any(q.kind == "CONVOY" and q.target == p.loc
                           and q.dest == p.dest for q in parsed)
            if not convoyed:
                if foreign_fleet_at_sea:
                    issues.append(Issue(
                        "warning", p.raw,
                        "relies on another power's fleet to convoy it; without "
                        "that convoy the move does nothing."))
                else:
                    issues.append(Issue(
                        "error", p.raw,
                        "no convoy — you ordered no fleet to convoy this move "
                        "and no other power has a fleet at sea to do it."))

    # Self-bounces: two of your own units moving to the same province, or
    # moving onto your own unit that stays put. Legal (a deliberate standoff
    # is a real tactic) but usually a blunder — warn.
    by_dest: dict[str, list[_Parsed]] = {}
    for p in parsed:
        if p.kind == "MOVE":
            by_dest.setdefault(p.dest, []).append(p)
    for dest, movers in by_dest.items():
        if len(movers) > 1:
            names = ", ".join(repr(m.raw) for m in movers)
            issues.append(Issue(
                "warning", movers[0].raw,
                f"self-bounce — {names} all target {dest}; at most one can "
                f"arrive and none can dislodge your own unit."))
        else:
            blocker = mine.get(dest)
            if (owners.get(dest) == power and
                    (blocker is None or blocker.kind not in ("MOVE",))):
                issues.append(Issue(
                    "warning", movers[0].raw,
                    f"your own unit at {dest} is not moving; this move will "
                    f"bounce (you cannot dislodge yourself)."))
    return issues


def format_issues(issues: list[Issue]) -> str:
    lines = []
    for issue in issues:
        lines.append(f"  [{issue.severity}] {issue}")
    return "\n".join(lines)


__all__ = ["Issue", "check_orders", "format_issues"]
