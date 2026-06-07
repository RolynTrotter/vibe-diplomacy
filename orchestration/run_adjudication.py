"""The adjudicator — runs inside GitHub Actions, the only place the private
key exists.

Decrypts every power's sealed orders for the current phase, applies them,
processes the phase, writes the new board, reveals the now-public orders to
history/, and removes the consumed .enc files.

Readiness:
  * On push: only proceed if every LIVE power (non-idle) has submitted.
  * On the scheduled deadline: pass --force to adjudicate regardless, filling
    missing orders with engine defaults (holds / civil disorder).

Reads the adjudicator private key from $ADJUDICATOR_PRIVATE_KEY.

Usage:
    python -m orchestration.run_adjudication [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from orchestration._common import repo_root
from orchestration.game_status import collect

from engine import adjudicate, crypto, state


def _read_sealed_orders(root, private_key: str, phase: str, live_powers) -> dict:
    orders_by_power: dict[str, list[str]] = {}
    for power in live_powers:
        path = state.power_orders_file(root, power, phase)
        if not path.exists():
            continue
        sealed = path.read_text(encoding="utf-8")
        payload = json.loads(crypto.decrypt(private_key, sealed))
        if payload.get("phase") != phase:
            print(f"WARNING: {power} orders are for {payload.get('phase')}, "
                  f"not {phase}; ignoring.", file=sys.stderr)
            continue
        orders_by_power[power] = payload.get("orders", [])
    return orders_by_power


def main() -> int:
    parser = argparse.ArgumentParser(description="Run adjudication for the current phase.")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument(
        "--force", action="store_true",
        help="Adjudicate even if not all live powers have submitted (deadline).",
    )
    parser.add_argument(
        "--respect-deadline", action="store_true",
        help="Auto-force if the phase clock has passed config deadline_hours.",
    )
    args = parser.parse_args()
    root = repo_root(args.root)

    private_key = os.environ.get("ADJUDICATOR_PRIVATE_KEY", "").strip()
    if not private_key:
        print("ADJUDICATOR_PRIVATE_KEY is not set.", file=sys.stderr)
        return 2

    status = collect(root)
    if status["done"]:
        print("Game is already over; nothing to do.")
        return 0

    game = state.load_game(root)
    phase = game.get_current_phase()

    past_deadline = False
    if args.respect_deadline:
        config = state.load_config(root)
        elapsed = state.hours_elapsed(root, phase)
        deadline = config.get("deadline_hours")
        if elapsed is not None and deadline is not None and elapsed >= deadline:
            past_deadline = True
            print(f"Phase {phase} is past its {deadline}h deadline "
                  f"({elapsed:.1f}h elapsed) — forcing.")

    force = args.force or past_deadline
    if not status["all_submitted"] and not force:
        print(f"Not ready: waiting on {', '.join(status['waiting_on'])}.")
        return 0
    live_powers = [n for n, p in status["powers"].items() if p["type"] != "idle"]

    orders_by_power = _read_sealed_orders(root, private_key, phase, live_powers)
    print(f"Adjudicating {phase} with orders from: "
          f"{', '.join(sorted(orders_by_power)) or '(none — all defaults)'}")

    summary = adjudicate.adjudicate(game, orders_by_power)
    state.save_game(game, root)
    state.set_phase_clock(root, game.get_current_phase())

    # Reveal the resolved phase publicly.
    history_path = state.history_dir(root) / f"{phase}.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    # Consume the sealed orders for the phase we just processed.
    for power in live_powers:
        path = state.power_orders_file(root, power, phase)
        if path.exists():
            path.unlink()

    print(f"Processed {phase} -> {game.get_current_phase()}. "
          f"Revealed orders to {history_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
