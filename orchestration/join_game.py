"""Claim a power in the current match — the self-serve seat picker.

An agent runs this with no arguments to grab a free seat: it reads the config
and existing `players/*.json` claims, picks an unclaimed power, generates its own
message keypair, writes its public identity, and stashes the private key in the
gitignored secrets/ dir. No human and no shared secrets involved.

Then commit `players/<POWER>.json` to the game branch to lock the claim. If two
sessions race for the same seat, the second push will be rejected — just re-run.

Usage:
    python -m orchestration.join_game                 # auto-pick a free seat
    python -m orchestration.join_game --power FRANCE   # request a specific seat
"""
from __future__ import annotations

import argparse
import random
import sys

from orchestration._common import POWERS, repo_root

from engine import comms, state


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim a power in this match.")
    parser.add_argument("--power", help="Specific power to claim (default: auto).")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--label", help="Optional note about who/what is playing.")
    args = parser.parse_args()

    root = repo_root(args.root)
    try:
        config = state.load_config(root)
    except FileNotFoundError:
        print("No game/config.json here. Are you on a game/<name> branch?",
              file=sys.stderr)
        return 2

    types = {p: config.get("powers", {}).get(p, {}).get("type", "agent")
             for p in POWERS}
    claimed = set(comms.list_players(root))

    if args.power:
        power = args.power.upper()
        if power not in POWERS:
            print(f"Unknown power {power!r}.", file=sys.stderr)
            return 2
        if power in claimed:
            print(f"{power} is already claimed. Pick another.", file=sys.stderr)
            return 1
        if types.get(power) == "idle":
            print(f"{power} is marked idle in this game.", file=sys.stderr)
            return 1
    else:
        free = [p for p in POWERS if p not in claimed and types.get(p) == "agent"]
        if not free:
            free = [p for p in POWERS if p not in claimed and types.get(p) != "idle"]
        if not free:
            print("No free seats left — every power is claimed.", file=sys.stderr)
            return 1
        power = random.choice(free)

    comms.claim_power(root, power, label=args.label)
    pfile = state.player_file(root, power)
    print(f"Claimed {power}.")
    print(f"  identity -> {pfile}   (commit this to lock your seat)")
    print(f"  privkey  -> {state.player_privkey_file(root, power)}   (gitignored; keep it)")
    print()
    print(f"You are {power}. Commit {pfile.relative_to(root)} to the game branch,")
    print("then play with the play-a-turn skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
