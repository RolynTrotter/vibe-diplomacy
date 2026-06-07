"""Validate, encrypt, and stage a power's orders for the current phase.

This is what the write-orders skill runs. It validates against the current
(public) board first so the player gets readable feedback, then seals the
accepted orders to the adjudicator's public key and writes
orders/<POWER>/<phase>.enc. The committing of that file to the game branch is
done by the skill (via GitHub MCP) — this script only writes it locally.

Usage:
    python -m orchestration.submit_orders --power FRANCE --file my_orders.txt
    echo "A PAR - BUR; F BRE - MAO" | python -m orchestration.submit_orders --power FRANCE
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestration._common import canonical_order_payload, parse_orders, repo_root

from engine import comms, crypto, state, validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit sealed orders for a power.")
    parser.add_argument("--power", required=True, help="Power name (e.g. FRANCE).")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--file", help="File of orders (one per line). Default: stdin.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate only; do not encrypt or write the .enc file.",
    )
    args = parser.parse_args()

    root = repo_root(args.root)
    power = args.power.upper()

    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    orders = parse_orders(text)
    if not orders:
        print("No orders provided.", file=sys.stderr)
        return 2

    game = state.load_game(root)
    phase = game.get_current_phase()
    result = validate.validate_orders(game, power, orders)

    if not result.ok:
        print(f"Rejected {len(result.errors)} order(s) for {power} in {phase}:",
              file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"All {len(result.accepted)} order(s) legal for {power} in {phase}:")
    for order in result.accepted:
        print(f"  {order}")

    if args.dry_run:
        print("(dry run — nothing written)")
        return 0

    # Sign the orders so the adjudicator can prove they came from this power
    # (and not, say, France submitting Germany's orders). Requires a claimed seat.
    keys = comms.load_keys(root, power)
    if not keys or not keys.get("sign"):
        print(f"\nNo signing key for {power}. Claim your seat first:",
              file=sys.stderr)
        print("    python -m orchestration.join_game --power " + power,
              file=sys.stderr)
        return 1

    signature = crypto.sign(keys["sign"],
                            canonical_order_payload(power, phase, result.accepted))
    pub_b64 = state.pubkey_file(root).read_text(encoding="utf-8")
    payload = json.dumps(
        {"power": power, "phase": phase, "orders": result.accepted, "sig": signature},
        sort_keys=True,
    )
    sealed = crypto.encrypt(pub_b64, payload)

    out = state.power_orders_file(root, power, phase)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sealed + "\n", encoding="utf-8")
    print(f"\nSealed + signed orders written to {out}")
    print("Commit this file to the game branch to submit your turn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
