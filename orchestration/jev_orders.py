"""CLI: have Jev write a power's orders for the current phase.

    python -m orchestration.jev_orders --power FRANCE
    python -m orchestration.jev_orders --power FRANCE --dry-run   # no API call

Prints the chosen orders, each with its confidence, plus the coherence report.
This does NOT submit anything — `submit_orders` still validates, signs and seals.
Batch-only by design; see issue #36.
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestration._common import POWERS, repo_root
from engine import jev, orders_jev, state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--power", required=True, help=f"one of {', '.join(POWERS)}")
    ap.add_argument("--root", default=None, help="game root (default: cwd)")
    ap.add_argument("--model", default=jev.DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the request; make no API call")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = repo_root(args.root)
    power = args.power.upper()
    if power not in POWERS:
        print(f"unknown power {power!r}; expected one of {', '.join(POWERS)}",
              file=sys.stderr)
        return 2

    game = state.load_game(root)

    if args.dry_run:
        questions = orders_jev.unit_questions(game, power)
        payload = {
            "state": orders_jev.build_state(game, power, root=root),
            "questions": {loc: {"instructions": q.instructions, "criteria": q.criteria}
                          for loc, q in questions.items()},
        }
        print(json.dumps(payload, indent=2, default=str))
        counts = {loc: len(q.criteria) for loc, q in questions.items()}
        print(f"\n{len(questions)} questions, options per unit: {counts}",
              file=sys.stderr)
        return 0

    ok, why = jev.available(root)
    if not ok:
        print(f"cannot call Jev: {why}", file=sys.stderr)
        return 1

    result = orders_jev.choose_orders(game, power, root=root, model=args.model)
    if args.json:
        print(json.dumps({
            "power": result.power, "phase": result.phase, "orders": result.orders,
            "confidence": result.confidence, "errors": result.errors,
            "issues": [{"severity": i.severity, "order": i.order, "message": i.message}
                       for i in result.issues],
            "usage": result.usage,
        }, indent=2))
    else:
        print(result.report())
        if result.usage:
            print(f"\ntokens: {result.usage}")
    return 0 if result.coherent and not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
