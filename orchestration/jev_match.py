"""Run a gunboat self-play match with Jev writing every power's orders.

    python -m orchestration.jev_match --until 1906

Each movement phase costs two requests per power: one valuation
(`engine.valuation`) and one order set (`engine.orders_jev`). Retreat and
adjustment phases skip the valuation. No negotiation, no agent in the loop —
this exists to see whether the order pipeline can actually play a game.

It watches for three capabilities that a working pipeline has to show at least
once, and that nothing in the S1901M testing could reveal:

  1. a unit is built
  2. a unit is dislodged
  3. a convoy carries an army

Dumb-but-legal orders are not flagged. The point is whether the machinery
functions across every phase type, not whether the play is good.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from orchestration._common import POWERS, repo_root

from engine import jev, orders_jev, state, valuation
from engine.coherence import parse_order


def _capped_adjustments(game, power: str, orders: list[str]) -> list[str]:
    """Builds are offered per home centre, but only so many are allowed.

    A power with one build and three open home centres gets three questions and
    can answer "build" to all of them. Keep the allowed number and waive the
    rest; the engine handles an under-filled disband on its own.
    """
    allowed = len(game.powers[power].centers) - len(game.powers[power].units)
    if allowed <= 0:
        return orders
    builds = [o for o in orders if o.upper().endswith(" B")]
    if len(builds) <= allowed:
        return orders
    keep = set(builds[:allowed])
    return [o for o in orders if not o.upper().endswith(" B") or o in keep]


def run(root: Path, until: int, *, log=print) -> dict:
    game = state.load_game(root)
    hits: dict[str, list] = {"build": [], "dislodge": [], "convoy": []}
    phases = 0
    per_power_orders: dict[str, int] = defaultdict(int)

    while not game.is_game_done and phases < 200:
        phase = game.get_current_phase()
        if int(phase[1:5]) > until:
            break
        movement = game.phase_type == "M"
        acted = []
        for power in POWERS:
            if not orders_jev.unit_questions(game, power):
                continue
            values = (valuation.province_values(game, power, root=root)
                      if movement else None)
            result = orders_jev.choose_orders(game, power, root=root, values=values)
            orders = result.orders
            if game.phase_type == "A":
                orders = _capped_adjustments(game, power, orders)
            if any(o.upper().endswith(" B") for o in orders):
                hits["build"].append((phase, power,
                                      [o for o in orders if o.upper().endswith(" B")]))
            for o in orders:
                if parse_order(o).kind == "CONVOY":
                    hits["convoy"].append((phase, power, o))
            game.set_orders(power, orders)
            per_power_orders[power] += len(orders)
            acted.append(f"{power[:3]} {' | '.join(orders) or '-'}")
        log(f"\n--- {phase} ---")
        for line in acted:
            log("  " + line)

        before = {p: set(u for u in game.powers[p].units) for p in POWERS}
        game.process()
        # A dislodgement shows up as a unit owing a retreat.
        for power in POWERS:
            retreats = getattr(game.powers[power], "retreats", {}) or {}
            for unit in retreats:
                hits["dislodge"].append((phase, power, unit))
        del before

        phases += 1

    centers = {p: len(game.powers[p].centers) for p in POWERS}
    return {"final_phase": game.get_current_phase(), "phases": phases,
            "centers": centers, "hits": hits,
            "orders_written": dict(per_power_orders)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="game root (default: cwd)")
    ap.add_argument("--until", type=int, default=1906, help="last year to play")
    ap.add_argument("--save", default=None, help="write the summary as JSON here")
    args = ap.parse_args()

    root = repo_root(args.root)
    ok, why = jev.available(root)
    if not ok:
        print(f"cannot call Jev: {why}", file=sys.stderr)
        return 1

    summary = run(root, args.until)
    print("\n" + "=" * 64)
    print(f"stopped at {summary['final_phase']} after {summary['phases']} phases")
    print("centres:", ", ".join(f"{p[:3]} {c}" for p, c in
                                sorted(summary["centers"].items(), key=lambda kv: -kv[1])))
    for name, label in [("build", "units built"), ("dislodge", "units dislodged"),
                        ("convoy", "convoys ordered")]:
        events = summary["hits"][name]
        mark = "yes" if events else "NO"
        print(f"  {label:18} {mark:4} ({len(events)})"
              + (f"  first: {events[0][0]} {events[0][1]} {events[0][2]}"
                 if events else ""))
    print(f"spend: {jev.SPEND}")
    if args.save:
        Path(args.save).write_text(json.dumps(summary, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
