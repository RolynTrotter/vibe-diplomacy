"""Initialize a new match in the current working tree.

Run this on a freshly created `game/<name>` branch. It:
  1. generates the adjudicator keypair,
  2. writes the public key to game/adjudicator_pub.key (committed),
  3. writes game/config.json,
  4. initializes state/current.json at S1901M,
  5. prints the PRIVATE key for you to paste, once, into a GitHub Actions
     repo secret named ADJUDICATOR_PRIVATE_KEY.

The private key is never written to disk by this script.

Usage:
    python -m orchestration.new_game --name frostbite \\
        --human FRANCE --idle ITALY
"""
from __future__ import annotations

import argparse

from orchestration._common import POWERS, repo_root

from engine import crypto, state


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a new Diplomacy match.")
    parser.add_argument("--name", required=True, help="Match name (e.g. frostbite).")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--human", nargs="*", default=[], help="Powers played by humans.")
    parser.add_argument("--idle", nargs="*", default=[], help="Powers with no player.")
    parser.add_argument(
        "--deadline-hours", type=float, default=24.0,
        help="Hours per phase before the scheduled deadline adjudicates.",
    )
    args = parser.parse_args()

    root = repo_root(args.root)
    human = {p.upper() for p in args.human}
    idle = {p.upper() for p in args.idle}

    priv_b64, pub_b64 = crypto.generate_keypair()

    # Public key (committed).
    pub_path = state.pubkey_file(root)
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    pub_path.write_text(pub_b64 + "\n", encoding="utf-8")

    # Config.
    def player_type(power: str) -> str:
        if power in idle:
            return "idle"
        if power in human:
            return "human"
        return "agent"

    config = {
        "name": args.name,
        "variant": "standard",
        "deadline_hours": args.deadline_hours,
        "powers": {p: {"type": player_type(p)} for p in POWERS},
    }
    state.save_config(config, root)

    # Initial board + empty dirs.
    game = state.new_game(args.name)
    state.save_game(game, root)
    state.set_phase_clock(root, game.get_current_phase())
    state.orders_dir(root).mkdir(parents=True, exist_ok=True)
    state.history_dir(root).mkdir(parents=True, exist_ok=True)

    print(f"Initialized match {args.name!r} at {game.get_current_phase()}.")
    print(f"  public key  -> {pub_path}")
    print(f"  config      -> {state.config_file(root)}")
    print(f"  board       -> {state.state_file(root)}")
    print()
    print("ACTION REQUIRED: add this repo Actions secret (Settings > Secrets >")
    print("Actions), then NEVER share it. The agents must not see it.")
    print()
    print("  Name:  ADJUDICATOR_PRIVATE_KEY")
    print(f"  Value: {priv_b64}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
