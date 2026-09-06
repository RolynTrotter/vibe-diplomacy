"""Shared helpers for the orchestration CLIs."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Make `engine` / `orchestration` importable when scripts are run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]


def repo_root(arg: str | None) -> Path:
    """Resolve the game root. Defaults to the current working directory."""
    return Path(arg).resolve() if arg else Path.cwd()


def parse_orders(text: str) -> list[str]:
    """Split a blob of orders into a clean list.

    Accepts newline- or semicolon-separated orders; ignores blanks and
    lines starting with '#'.
    """
    raw = text.replace(";", "\n").splitlines()
    return [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]


def canonical_order_payload(power: str, phase: str, orders: list[str]) -> str:
    """Stable serialization of an order set, signed by the submitter and
    verified by the adjudicator so no one can submit another power's orders."""
    import json
    return json.dumps(
        {"power": power.upper(), "phase": phase, "orders": list(orders)},
        sort_keys=True, separators=(",", ":"),
    )


# Everything a phase can touch. Players commit only their own files; the
# conductor publishes the shared board on their behalf.
GAME_PATHS = ("state", "history", "game", "orders", "mail", "players", "notes")


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)


def current_branch(root: Path) -> str:
    return git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def publish(root: Path, message: str, push: bool = True) -> dict:
    """Commit the game's files and (optionally) push — best effort, never fatal.

    One commit per call is the point: a conductor that commits per power per
    round pays a network round trip for every message anyone sends, and the
    pushes race each other on a single branch.
    """
    paths = [d for d in GAME_PATHS if (Path(root) / d).exists()]
    if not paths:
        return {"committed": False, "pushed": False, "detail": "nothing to commit"}
    git(root, "add", "-A", *paths)
    commit = git(root, "commit", "-m", message)
    committed = commit.returncode == 0
    out = {"committed": committed, "pushed": False,
           "detail": (commit.stdout + commit.stderr).strip()[-200:]}
    if push and "origin" in git(root, "remote").stdout.split():
        res = git(root, "push", "origin", current_branch(root))
        out["pushed"] = res.returncode == 0
        if res.returncode != 0:
            out["detail"] = res.stderr.strip()[-200:]
    return out
