"""Conductor helpers: deterministic bits of running a whole match from one
session that spawns each power as a scoped subagent.

The conductor SKILL (.claude/skills/conduct-match) does the spawning (via
callstack `/call` or native subagents). This CLI provides the non-LLM pieces it
leans on, so the conductor itself juggles almost nothing — the files are the log:

    roster   who still needs to play this phase (+ claimed/submitted status)
    brief    the selective context to hand a power's subagent
    tasks    every task text this phase needs, one per power, ready to fan out
    collect  turn one subagent's REPLY into sealed mail + sealed orders
    advance  commit, adjudicate, commit the new board, push — the whole seam

`tasks` + `collect` + `advance` exist because the conductor was spending model
tokens on work with no judgement in it: composing seven near-identical prompts,
remembering which CLI each subagent should run, and committing after every
power. With these, a subagent needs no tools at all — it reads a task and
replies with text — and the phase costs one commit instead of twenty.

Adjudication and status reuse the existing modules (run_adjudication,
game_status), so conductor mode produces the exact same signed/sealed artifacts
as distrusting sessions.

Usage:
    python -m orchestration.conduct roster
    python -m orchestration.conduct brief --power FRANCE
    python -m orchestration.conduct tasks --kind combined
    echo "<subagent reply>" | python -m orchestration.conduct collect --power FRANCE
    python -m orchestration.conduct advance
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

from orchestration import tasks as task_text
from orchestration._common import POWERS, publish, repo_root
from orchestration.game_status import collect as status_collect
from orchestration.player_agent import extract_messages, extract_orders

from engine import comms, context, state


def roster(root) -> dict:
    status = status_collect(root)
    claimed = set(comms.list_players(root))
    powers = {}
    for name in POWERS:
        p = status["powers"].get(name, {})
        powers[name] = {
            "type": p.get("type", "agent"),
            "claimed": name in claimed,
            "needs_orders": p.get("needs_orders", True),
            "submitted": p.get("submitted", False),
        }
    # to_play: live powers that actually have decisions to make this phase.
    # Empty on trivial retreat phases (no dislodgements) and adjustment phases
    # where every power has 0 adjustment — conductor can adjudicate immediately.
    to_play = status["waiting_on"]
    return {
        "phase": status["phase"],
        "phase_type": status["phase_type"],
        "press": state.load_config(root).get("press", "none"),
        "done": status["done"],
        "all_submitted": status["all_submitted"],
        "to_play": to_play,
        "powers": powers,
    }


def default_kind(rs: dict) -> str:
    """What this phase asks for, given press and phase type.

    Full-press movement phases default to `combined` — messages and orders in
    one reply — because a separate orders round doubles the model calls to buy
    a power the chance to change its mind about what it just promised.
    """
    if rs["press"] == "full" and rs["phase_type"] == "M":
        return "combined"
    return "orders"


def phase_tasks(root, kind: str | None = None, powers: list[str] | None = None,
                style: str = "reply") -> dict:
    """The complete task text for every power that still has to act.

    Composing these is pure bookkeeping — same brief call, same wording, seven
    times — so the conductor should never spend a model call on it.
    """
    rs = roster(root)
    kind = kind or default_kind(rs)
    if kind not in task_text.KINDS:
        raise ValueError(f"kind must be one of {task_text.KINDS}, got {kind!r}")
    chosen = [p.upper() for p in powers] if powers else rs["to_play"]
    return {
        "phase": rs["phase"],
        "phase_type": rs["phase_type"],
        "press": rs["press"],
        "kind": kind,
        "done": rs["done"],
        "powers": {
            power: task_text.build(power, kind, rs["phase"],
                                   context.power_brief(root, power),
                                   press=rs["press"], style=style)
            for power in chosen
        },
    }


def collect_reply(root, power: str, reply: str, repo: str | None = None) -> dict:
    """Turn one subagent's reply into sealed mail and sealed orders.

    The subagent needs no tools and no CLI knowledge: it reads a task and
    answers in text, exactly like a raw model seat. Everything it says is
    driven through the SAME join/send/submit CLIs a distrusting session uses,
    so the artifacts are identical either way.
    """
    power = power.upper()
    repo = repo or str(pathlib.Path(__file__).resolve().parent.parent)
    out = {"power": power, "sent": [], "orders": [], "ok": True, "error": None}

    def run(module, args, stdin=None):
        env = dict(os.environ)
        env.pop("ADJUDICATOR_PRIVATE_KEY", None)   # players never see this key
        return subprocess.run(
            [sys.executable, "-m", module, "--root", str(root), *args],
            cwd=repo, input=stdin, text=True, capture_output=True, env=env)

    if power not in comms.list_players(root):
        run("orchestration.join_game", ["--power", power])

    if state.load_config(root).get("press") == "full":
        for recipient, body in extract_messages(reply):
            if recipient == "NOBODY":
                continue
            proc = run("orchestration.send_message",
                       ["--power", power, "--to", recipient], stdin=body)
            if proc.returncode == 0:
                out["sent"].append(recipient)
            else:
                out["ok"] = False
                out["error"] = proc.stderr.strip()[:300]

    orders = extract_orders(reply)
    if orders:
        proc = run("orchestration.submit_orders", ["--power", power],
                   stdin="\n".join(orders))
        out["orders"] = orders
        if proc.returncode != 0:
            out["ok"] = False
            # The rejection text is the retry prompt: hand it straight back to
            # the subagent rather than re-deriving what went wrong.
            out["error"] = (proc.stderr.strip() or proc.stdout.strip())[:1000]
    elif out["sent"] == []:
        out["ok"] = False
        out["error"] = "reply contained no messages and no parseable orders"
    return out


def advance(root, force: bool = True, push: bool = True) -> dict:
    """Commit what the powers produced, adjudicate, commit the board, push.

    One commit per phase instead of one per power per round, and one call
    instead of the six the skill used to spell out.
    """
    rs = roster(root)
    before = rs["phase"]
    result = {"phase": before, "adjudicated": False, "error": None}
    result["staged"] = publish(root, f"Players submitted {before}", push=False)

    if not os.environ.get("ADJUDICATOR_PRIVATE_KEY"):
        result["error"] = ("ADJUDICATOR_PRIVATE_KEY is not set — export it to "
                           "adjudicate locally.")
        return result

    repo = str(pathlib.Path(__file__).resolve().parent.parent)
    args = [sys.executable, "-m", "orchestration.run_adjudication",
            "--root", str(root)] + (["--force"] if force else [])
    proc = subprocess.run(args, cwd=repo, text=True, capture_output=True)
    result["output"] = (proc.stdout or proc.stderr).strip()[-800:]
    if proc.returncode != 0:
        result["error"] = proc.stderr.strip()[-500:]
        return result

    result["adjudicated"] = True
    result["published"] = publish(root, f"Adjudicate {before}", push=push)
    after = roster(root)
    result["next_phase"] = after["phase"]
    result["done"] = after["done"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Conductor helpers.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("roster", help="Who still needs to play this phase.")
    r.add_argument("--root")

    b = sub.add_parser("brief", help="Selective context for one power's subagent.")
    b.add_argument("--power", required=True)
    b.add_argument("--root")

    t = sub.add_parser("tasks", help="Every task text this phase needs.")
    t.add_argument("--kind", choices=task_text.KINDS,
                   help="Default: combined on full-press movement phases, "
                        "else orders.")
    t.add_argument("--power", action="append", dest="powers",
                   help="Limit to these powers (repeatable). Default: to_play.")
    t.add_argument("--style", choices=("reply", "agentic"), default="reply",
                   help="reply: subagent answers in text (default). "
                        "agentic: subagent runs the CLIs itself.")
    t.add_argument("--format", choices=("json", "text"), default="json")
    t.add_argument("--root")

    c = sub.add_parser("collect", help="Turn a subagent's reply into artifacts.")
    c.add_argument("--power", required=True)
    c.add_argument("--file", help="Reply text (default: stdin).")
    c.add_argument("--root")

    a = sub.add_parser("advance", help="Commit, adjudicate, commit, push.")
    a.add_argument("--no-push", action="store_true")
    a.add_argument("--wait", action="store_true",
                   help="Fail rather than force-adjudicating stragglers.")
    a.add_argument("--root")

    args = parser.parse_args()
    root = repo_root(args.root)

    if args.cmd == "roster":
        print(json.dumps(roster(root), indent=2))
    elif args.cmd == "brief":
        print(context.power_brief(root, args.power))
    elif args.cmd == "tasks":
        out = phase_tasks(root, kind=args.kind, powers=args.powers,
                          style=args.style)
        if args.format == "json":
            print(json.dumps(out, indent=2))
        else:
            print(f"# {out['phase']} — kind: {out['kind']} — "
                  f"{len(out['powers'])} power(s) to play")
            for power, task in out["powers"].items():
                print(f"\n{'=' * 70}\n## TASK FOR {power}\n{'=' * 70}\n{task}")
    elif args.cmd == "collect":
        reply = (open(args.file, encoding="utf-8").read() if args.file
                 else sys.stdin.read())
        result = collect_reply(root, args.power, reply)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    elif args.cmd == "advance":
        result = advance(root, force=not args.wait, push=not args.no_push)
        print(json.dumps(result, indent=2))
        return 0 if result["adjudicated"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
