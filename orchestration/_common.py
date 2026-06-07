"""Shared helpers for the orchestration CLIs."""
from __future__ import annotations

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
