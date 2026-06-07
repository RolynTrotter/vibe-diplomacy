"""On-disk game store: the single source of truth for serialization.

A match lives on its own `game/<name>` git branch. The layout on that branch:

    state/current.json          full saved-game (engine format; replayable)
    history/<phase>.json        human-readable reveal of each processed phase
    orders/<POWER>/<phase>.enc  sealed pending orders for the current phase
    game/config.json            powers, types, deadline policy, metadata
    game/adjudicator_pub.key    base64 public key players encrypt orders to

`state/current.json` holds the engine's full saved-game format, which already
contains every past phase (state, orders, results). That makes it both the
current board AND the authoritative history. The `history/` files are a
convenience reveal for humans and for the Cicero suggestion input.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from diplomacy import Game
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format


def state_file(root: Path) -> Path:
    return Path(root) / "state" / "current.json"


def history_dir(root: Path) -> Path:
    return Path(root) / "history"


def orders_dir(root: Path) -> Path:
    return Path(root) / "orders"


def config_file(root: Path) -> Path:
    return Path(root) / "game" / "config.json"


def pubkey_file(root: Path) -> Path:
    return Path(root) / "game" / "adjudicator_pub.key"


def clock_file(root: Path) -> Path:
    return Path(root) / "game" / "phase_clock.json"


def set_phase_clock(root: Path, phase: str) -> None:
    """Record when the current phase began (drives the timed deadline)."""
    path = clock_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"phase": phase, "started_at": datetime.now(timezone.utc).isoformat()}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def read_phase_clock(root: Path) -> dict | None:
    path = clock_file(root)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def hours_elapsed(root: Path, phase: str) -> float | None:
    """Hours since the current phase began, or None if unknown/mismatched."""
    clock = read_phase_clock(root)
    if not clock or clock.get("phase") != phase:
        return None
    started = datetime.fromisoformat(clock["started_at"])
    return (datetime.now(timezone.utc) - started).total_seconds() / 3600.0


def power_orders_file(root: Path, power: str, phase: str) -> Path:
    return orders_dir(root) / power.upper() / f"{phase}.enc"


def load_game(root: Path) -> Game:
    """Reconstruct the live Game from state/current.json."""
    with open(state_file(root), encoding="utf-8") as fh:
        saved = json.load(fh)
    return from_saved_game_format(saved)


def save_game(game: Game, root: Path) -> None:
    """Persist the full saved-game format to state/current.json."""
    path = state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = to_saved_game_format(game)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(saved, fh, indent=2, sort_keys=True)


def load_config(root: Path) -> dict:
    with open(config_file(root), encoding="utf-8") as fh:
        return json.load(fh)


def save_config(config: dict, root: Path) -> None:
    path = config_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)


def new_game(name: str) -> Game:
    """A fresh standard 7-power game at S1901M."""
    game = Game()
    game.note = name
    return game
