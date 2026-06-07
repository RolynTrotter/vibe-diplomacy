"""Send press to another power (or broadcast) — sealed so only they can read it.

Encrypts the message to each recipient's public key plus an archive copy to the
adjudicator (for the end-of-game reveal), and drops them in the shared mail pool.
The skill commits the new `mail/*.enc` files.

Usage:
    echo "Want to DMZ the Channel?" | python -m orchestration.send_message \\
        --power FRANCE --to ENGLAND
    echo "Stop Russia." | python -m orchestration.send_message --power FRANCE --to ALL
"""
from __future__ import annotations

import argparse
import sys

from orchestration._common import repo_root

from engine import comms, state


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a sealed message.")
    parser.add_argument("--power", required=True, help="Your power (the sender).")
    parser.add_argument("--to", required=True, nargs="+",
                        help="Recipient power(s), or ALL/GLOBAL to broadcast.")
    parser.add_argument("--root", help="Game root (default: cwd).")
    parser.add_argument("--message", help="Message text (default: read stdin).")
    args = parser.parse_args()

    root = repo_root(args.root)
    sender = args.power.upper()

    body = (args.message if args.message is not None else sys.stdin.read()).strip()
    if not body:
        print("Empty message.", file=sys.stderr)
        return 2

    config = state.load_config(root)
    if config.get("press", "none") != "full":
        print("This game is gunboat (press disabled). No messaging.", file=sys.stderr)
        return 1

    recipients = ["GLOBAL"] if any(r.upper() in ("ALL", "GLOBAL") for r in args.to) \
        else [r.upper() for r in args.to]

    players = comms.list_players(root)
    if sender not in players:
        print(f"{sender} hasn't claimed a seat yet — run join_game first.",
              file=sys.stderr)
        return 1
    unknown = [r for r in recipients if r != "GLOBAL" and r not in players]
    if unknown:
        print(f"No claimed recipient(s): {', '.join(unknown)}.", file=sys.stderr)
        return 1

    keys = comms.load_keys(root, sender)
    if not keys or not keys.get("sign"):
        print(f"No signing key for {sender}. Re-run join_game in this tree.",
              file=sys.stderr)
        return 1

    adjudicator_pub = state.pubkey_file(root).read_text(encoding="utf-8").strip()
    phase = state.load_game(root).get_current_phase()
    written = comms.send_message(root, sender, recipients, body, phase,
                                 adjudicator_pub, sign_priv=keys["sign"])

    label = "everyone" if recipients == ["GLOBAL"] else ", ".join(recipients)
    print(f"Sealed message from {sender} to {label} ({phase}).")
    print(f"  wrote {len(written)} mail file(s). Commit the mail/ additions to send.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
