"""CLI: have Jev write a power's orders for the current phase.

    python -m orchestration.jev_orders --power FRANCE
    python -m orchestration.jev_orders --power FRANCE --dry-run   # no API call
    python -m orchestration.jev_orders --power FRANCE --stab      # decide deals
    python -m orchestration.jev_orders --power FRANCE --orders-only \
        | scripts/submit.sh FRANCE                                # negotiate, then let Jev order

Prints the chosen orders with their confidences and the coherence report. This
does NOT submit anything — `submit_orders` still validates, signs and seals.

The staged path (`engine.staged`) is the default, because the single-pass one
froze a whole game in testing; `--batch` selects it anyway for comparison. On a
movement phase the run opens with one `engine.valuation` request so each move
option carries its destination's priority; `--no-values` skips it.

State includes this power's own notes, standing `DEAL:` lines, inbox and last
outcomes whenever those files exist (issue #37) — a gunboat game simply has
none of them. `--no-press` forces the board-only state.
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestration._common import POWERS, repo_root
from engine import jev, orders_jev, press, staged, state, valuation


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--power", required=True, help=f"one of {', '.join(POWERS)}")
    ap.add_argument("--root", default=None, help="game root (default: cwd)")
    ap.add_argument("--model", default=jev.DEFAULT_MODEL)
    ap.add_argument("--batch", action="store_true",
                    help="single-pass path instead of the staged one")
    ap.add_argument("--stab", action="store_true",
                    help="decide each standing DEAL: keep-or-break first")
    ap.add_argument("--no-values", action="store_true",
                    help="skip the province-valuation request")
    ap.add_argument("--no-press", action="store_true",
                    help="board-only state: no notes, deals, inbox or outcomes")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the request; make no API call")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--orders-only", action="store_true",
                    help="print just the order lines, ready to pipe into submit.sh")
    args = ap.parse_args()

    root = repo_root(args.root)
    power = args.power.upper()
    if power not in POWERS:
        print(f"unknown power {power!r}; expected one of {', '.join(POWERS)}",
              file=sys.stderr)
        return 2

    game = state.load_game(root)

    if args.dry_run:
        built = orders_jev.build_state(game, power, root=root,
                                       include_press=not args.no_press)
        questions = orders_jev.unit_questions(game, power)
        payload = {
            "state": built,
            "questions": {loc: {"instructions": q.instructions, "criteria": q.criteria}
                          for loc, q in questions.items()},
        }
        if args.stab:
            deals = press.standing_deals(root, power)
            payload["stab_questions"] = {
                key: {"instructions": q.instructions, "criteria": q.criteria}
                for key, q in press.stab_questions(deals, power).items()}
        print(json.dumps(payload, indent=2, default=str))
        counts = {loc: len(q.criteria) for loc, q in questions.items()}
        carried = [k for k in ("your_own_plan", "your_standing_deals", "your_inbox",
                               "what_happened_to_your_last_orders") if k in built]
        print(f"\n{len(questions)} questions, options per unit: {counts}",
              file=sys.stderr)
        print(f"private state carried: {carried or 'none (gunboat / no files)'}",
              file=sys.stderr)
        return 0

    ok, why = jev.available(root)
    if not ok:
        print(f"cannot call Jev: {why}", file=sys.stderr)
        return 1

    values = None
    if not args.no_values and game.phase_type == "M":
        values = valuation.province_values(game, power, root=root, model=args.model)

    if args.batch:
        result = orders_jev.choose_orders(game, power, root=root,
                                          model=args.model, values=values)
    else:
        result = staged.choose_orders_staged(game, power, root=root, values=values,
                                             model=args.model, stab=args.stab)
    if args.orders_only:
        # The whole report goes to stderr so stdout is exactly what
        # `scripts/submit.sh` expects on its stdin.
        print(result.report(), file=sys.stderr)
        print("\n".join(result.orders))
        return 0 if result.coherent and not result.errors else 1
    if args.json:
        print(json.dumps({
            "power": result.power, "phase": result.phase, "orders": result.orders,
            "confidence": result.confidence, "errors": result.errors,
            "deal_policy": result.deal_policy,
            "stages": [{"name": s.name, "picked": s.picked,
                        "confidence": s.confidence, "marginals": s.marginals}
                       for s in result.stages],
            "issues": [{"severity": i.severity, "order": i.order, "message": i.message}
                       for i in result.issues],
            "usage": result.usage,
        }, indent=2))
    else:
        print(result.report())
        print(f"\nspend: {jev.SPEND}")
    return 0 if result.coherent and not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
