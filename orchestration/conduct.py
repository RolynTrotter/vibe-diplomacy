"""Conductor helpers: deterministic bits of running a whole match from one
session that spawns each power as a scoped subagent.

The conductor SKILL (.claude/skills/conduct-match) does the spawning (via
callstack `/call` or native subagents). This CLI provides the non-LLM pieces it
leans on, so the conductor itself juggles almost nothing — the files are the log:

    roster   who still needs to play this phase (+ claimed/submitted status)
    brief    the selective context to hand a power's subagent

Adjudication and status reuse the existing modules (run_adjudication,
game_status), so conductor mode produces the exact same signed/sealed artifacts
as distrusting sessions.

Usage:
    python -m orchestration.conduct roster
    python -m orchestration.conduct brief --power FRANCE
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestration._common import POWERS, repo_root
from orchestration.game_status import collect

from engine import comms, context, state


def roster(root) -> dict:
    status = collect(root)
    claimed = set(comms.list_players(root))
    powers = {}
    for name in POWERS:
        p = status["powers"].get(name, {})
        powers[name] = {
            "type": p.get("type", "agent"),
            "claimed": name in claimed,
            "submitted": p.get("submitted", False),
        }
    to_play = [n for n in POWERS
               if powers[n]["type"] != "idle" and not powers[n]["submitted"]]
    return {
        "phase": status["phase"],
        "press": state.load_config(root).get("press", "none"),
        "done": status["done"],
        "all_submitted": status["all_submitted"],
        "to_play": to_play,
        "powers": powers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Conductor helpers.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("roster", help="Who still needs to play this phase.")
    r.add_argument("--root")

    b = sub.add_parser("brief", help="Selective context for one power's subagent.")
    b.add_argument("--power", required=True)
    b.add_argument("--root")

    args = parser.parse_args()
    root = repo_root(args.root)

    if args.cmd == "roster":
        print(json.dumps(roster(root), indent=2))
    elif args.cmd == "brief":
        print(context.power_brief(root, args.power))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
