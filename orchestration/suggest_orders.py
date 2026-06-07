"""Print tactical order suggestions for a power (the run-cicero skill's CLI).

Uses the heuristic engine by default; the --engine flag will select real
Cicero once Epic 6 lands. Reads the public board and history only — never any
sealed orders.

Usage:
    python -m orchestration.suggest_orders --power FRANCE
"""
from __future__ import annotations

import argparse
import json

from orchestration._common import repo_root

from engine import state, suggest


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest orders for a power.")
    parser.add_argument("--power", required=True)
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--engine", default="heuristic")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = repo_root(args.root)
    game = state.load_game(root)
    result = suggest.suggest(game, args.power, engine=args.engine)

    if args.json:
        print(json.dumps({
            "engine": result.engine,
            "orders": result.orders,
            "rationale": result.rationale,
        }, indent=2))
        return 0

    print(f"Suggested orders for {args.power.upper()} "
          f"({game.get_current_phase()}, engine={result.engine}):")
    for order in result.orders:
        loc = order.split()[1] if len(order.split()) > 1 else order
        why = result.rationale.get(loc, "")
        print(f"  {order:<24}  # {why}")
    print("\nThese are suggestions only — review, then submit with the "
          "write-orders skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
