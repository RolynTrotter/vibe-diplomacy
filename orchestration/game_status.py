"""Phone-friendly status for the current phase.

Reports the phase, each power's unit/center counts and build/disband owed,
and who has submitted sealed orders — WITHOUT decrypting anything (it only
checks for the presence of orders/<POWER>/<phase>.enc).

Usage:
    python -m orchestration.game_status
    python -m orchestration.game_status --json
"""
from __future__ import annotations

import argparse
import json

from orchestration._common import repo_root

from engine import query, state


def _needs_orders(phase_type: str, power_name: str, game, ptype: str,
                  adjustment: int) -> bool:
    """Return True if this power must submit orders for the current phase.

    Retreat phases only need input from powers with dislodged units.
    Adjustment phases only need input from powers with non-zero build/disband.
    Movement phases always need input from live powers.
    """
    if ptype == "idle":
        return False
    if phase_type == "R":
        p = game.powers.get(power_name)
        retreats = getattr(p, "retreats", True) if p else True
        return bool(retreats)
    if phase_type == "A":
        return adjustment != 0
    return True  # movement phase


def collect(root) -> dict:
    game = state.load_game(root)
    config = state.load_config(root)
    phase = game.get_current_phase()
    summary = query.board_summary(game)
    phase_type = summary["phase_type"]

    powers = {}
    for name, info in summary["powers"].items():
        ptype = config["powers"].get(name, {}).get("type", "agent")
        submitted = state.power_orders_file(root, name, phase).exists()
        needs = _needs_orders(phase_type, name, game, ptype, info["adjustment"])
        powers[name] = {
            "type": ptype,
            "units": info["unit_count"],
            "centers": info["center_count"],
            "adjustment": info["adjustment"],
            "needs_orders": needs,
            "submitted": submitted,
        }

    live = [n for n, p in powers.items() if p["type"] != "idle"]
    waiting = [n for n in live if powers[n]["needs_orders"] and not powers[n]["submitted"]]
    return {
        "name": config.get("name"),
        "phase": phase,
        "phase_type": phase_type,
        "done": game.is_game_done,
        "powers": powers,
        "all_submitted": not waiting,
        "waiting_on": waiting,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show current game status.")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    status = collect(repo_root(args.root))
    if args.json:
        print(json.dumps(status, indent=2))
        return 0

    print(f"Game: {status['name']}   Phase: {status['phase']} "
          f"({status['phase_type']})")
    if status["done"]:
        print("GAME OVER")
    print(f"{'POWER':<9}{'TYPE':<8}{'UNITS':>6}{'CTRS':>6}{'ADJ':>5}  SUBMITTED")
    for name, p in status["powers"].items():
        adj = f"{p['adjustment']:+d}" if p["adjustment"] else "0"
        if p["type"] == "idle" or not p["needs_orders"]:
            sub = "--"
        elif p["submitted"]:
            sub = "yes"
        else:
            sub = "NO"
        print(f"{name:<9}{p['type']:<8}{p['units']:>6}{p['centers']:>6}"
              f"{adj:>5}  {sub}")
    if status["all_submitted"]:
        print("\nAll live powers have submitted — ready to adjudicate.")
    else:
        print(f"\nWaiting on: {', '.join(status['waiting_on'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
