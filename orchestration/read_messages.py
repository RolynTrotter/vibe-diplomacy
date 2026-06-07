"""Read your inbox — every sealed message addressed to your power.

Trial-decrypts the shared mail pool with your private key (gitignored). You only
ever see messages sealed to you; everything else stays opaque.

Usage:
    python -m orchestration.read_messages --power FRANCE
    python -m orchestration.read_messages --power FRANCE --with ENGLAND
    python -m orchestration.read_messages --power FRANCE --json
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestration._common import repo_root

from engine import comms


def main() -> int:
    parser = argparse.ArgumentParser(description="Read your sealed inbox.")
    parser.add_argument("--power", required=True, help="Your power.")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--with", dest="counterpart",
                        help="Only messages to/from this power.")
    parser.add_argument("--phase", help="Only messages from this phase.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = repo_root(args.root)
    power = args.power.upper()

    privkey = comms.load_privkey(root, power)
    if not privkey:
        print(f"No private key for {power}. Did you run join_game in this tree?",
              file=sys.stderr)
        return 1

    msgs = comms.read_inbox(root, power, privkey)
    if args.counterpart:
        cp = args.counterpart.upper()
        msgs = [m for m in msgs if cp in (m.get("sender"), m.get("recipient"))]
    if args.phase:
        msgs = [m for m in msgs if m.get("phase") == args.phase.upper()]

    if args.json:
        print(json.dumps(msgs, indent=2))
        return 0

    if not msgs:
        print(f"No messages for {power}.")
        return 0
    last_phase = None
    for m in msgs:
        if m.get("phase") != last_phase:
            last_phase = m.get("phase")
            print(f"\n--- {last_phase} ---")
        tag = "broadcast" if m.get("recipient") == comms.GLOBAL else f"to {m.get('recipient')}"
        print(f"[{m.get('sender')} {tag}] {m.get('body')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
