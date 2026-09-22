"""Send every `TO ...` line in one go, and commit the mail once.

    printf 'TO ENGLAND: DMZ the Channel?\nTO ENGLAND, GERMANY: BUR stays empty?\nTO ALL: peace in the west\n' \
        | python -m orchestration.send_batch --power FRANCE

A phase of diplomacy used to cost one `send_message` per recipient plus a
`sync.sh` — four or five round trips to say three things. This takes the whole
lot on stdin, in the same `TO <TARGET>: <body>` syntax a tool-less seat already
writes, and sends each message once. A line naming several powers is ONE sealed
message to all of them, because `comms.send_message` already takes a recipient
list.

`TO SELF:` and `TO STAFF:` lines are not mail and are ignored here — they are
routed by `orchestration.player_agent.parse_reply` for seats that have a staff.
This CLI is for a session that runs its own commands.
"""
from __future__ import annotations

import argparse
import sys

from orchestration._common import POWERS, repo_root
from orchestration.player_agent import parse_reply

from engine import comms, state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--power", required=True, help=f"one of {', '.join(POWERS)}")
    ap.add_argument("--root", default=None, help="game root (default: cwd)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent; seal nothing")
    args = ap.parse_args()

    root = repo_root(args.root)
    power = args.power.upper()
    if power not in POWERS:
        print(f"unknown power {power!r}", file=sys.stderr)
        return 2

    config = state.load_config(root)
    if config.get("press", "none") != "full":
        print("this match is gunboat — no press.", file=sys.stderr)
        return 1

    parsed = parse_reply(sys.stdin.read())
    for problem in parsed.errors:
        print(f"warning: {problem}", file=sys.stderr)
    if not parsed.mail:
        print("nothing to send.", file=sys.stderr)
        return 1

    if args.dry_run:
        for targets, body in parsed.mail:
            print(f"TO {', '.join(targets)}: {body}")
        return 0

    keys = comms.load_keys(root, power)
    adj = state.pubkey_file(root).read_text(encoding="utf-8").strip()
    phase = state.load_game(root).get_current_phase()
    sent = 0
    for targets, body in parsed.mail:
        comms.send_message(root, power, targets, body, phase, adj,
                           sign_priv=keys["sign"])
        print(f"sealed to {', '.join(targets)}: {body[:70]}")
        sent += 1
    print(f"\n{sent} message(s) sealed into mail/ — commit with:\n"
          f"  scripts/sync.sh \"{power} {phase} messages\" mail/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
