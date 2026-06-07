"""Build the static GitHub Pages visualizer bundle.

A match's `state/current.json` (engine saved-game format) already contains every
phase's board state and orders, so the whole site can be baked from one file per
`game/<name>` branch — no live GitHub API calls from the phone, which keeps the
viewer fast and rate-limit-free.

For each game branch this:
  * reconstructs every phase and renders it to an SVG (board + units + move
    arrows) via the AGPL `diplomacy` renderer, and
  * writes a compact `meta.json` (phase labels, supply-center scoreboard, and
    the order list for the text fallback).

It then writes a top-level `games.json` manifest and copies the static front
end. Output goes to `--out` (default `_site/`).

Game branches are read straight from git refs (`git show <ref>:<path>`), so the
builder works both in CI (after fetching `origin/game/*`) and locally.

Usage:
    python site/build_site.py --out _site
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
sys.path.insert(0, str(ROOT))

from diplomacy import Game  # noqa: E402

SEASONS = {"S": "Spring", "F": "Fall", "W": "Winter"}
PHASE_TYPES = {"M": "Movement", "R": "Retreats", "A": "Adjustments"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True,
                          capture_output=True).stdout


def list_game_refs() -> list[tuple[str, str]]:
    """(game_name, git_ref) for every game/* branch, remote preferred."""
    refs: dict[str, str] = {}
    out = git("for-each-ref", "--format=%(refname)",
              "refs/heads/game/", "refs/remotes/origin/game/")
    for ref in filter(None, (r.strip() for r in out.splitlines())):
        name = ref.split("/game/", 1)[1]
        # Prefer the remote ref when both exist (CI authority).
        if name not in refs or ref.startswith("refs/remotes/"):
            refs[name] = ref
    return sorted(refs.items())


def read_json_at(ref: str, path: str) -> dict | None:
    raw = git("show", f"{ref}:{path}")
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def phase_label(code: str) -> str:
    """'S1901M' -> 'Spring 1901 — Movement'."""
    if len(code) >= 6 and code[0] in SEASONS:
        season, year, kind = SEASONS[code[0]], code[1:5], PHASE_TYPES.get(code[-1], "")
        return f"{season} {year} — {kind}".rstrip(" —")
    return code


def build_game(name: str, ref: str, out: Path) -> dict | None:
    saved = read_json_at(ref, "state/current.json")
    if not saved or not saved.get("phases"):
        print(f"  ! {name}: no state/current.json with phases; skipping")
        return None
    config = read_json_at(ref, "game/config.json") or {}

    game_dir = out / "games" / name
    game_dir.mkdir(parents=True, exist_ok=True)

    phases_meta = []
    for ph in saved["phases"]:
        code = ph["name"]
        game = Game()
        game.set_state(ph["state"])
        orders = {p: o for p, o in (ph.get("orders") or {}).items() if o}
        for power, power_orders in orders.items():
            game.set_orders(power, power_orders)

        svg = game.render(incl_orders=True)
        (game_dir / f"{code}.svg").write_text(svg, encoding="utf-8")

        centers = {p: len(c) for p, c in ph["state"].get("centers", {}).items()}
        phases_meta.append({
            "code": code,
            "label": phase_label(code),
            "svg": f"games/{name}/{code}.svg",
            "centers": centers,
            "orders": orders,
        })

    meta = {
        "name": name,
        "title": config.get("name", name),
        "phases": phases_meta,
        "current_phase": phases_meta[-1]["code"],
    }
    (game_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"  + {name}: {len(phases_meta)} phases rendered")
    return {
        "name": name,
        "title": meta["title"],
        "phase_count": len(phases_meta),
        "current_phase": meta["current_phase"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Pages visualizer.")
    parser.add_argument("--out", default="_site", help="Output dir (default _site).")
    args = parser.parse_args()

    out = (ROOT / args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    games = list_game_refs()
    print(f"Found {len(games)} game branch(es).")
    manifest = []
    for name, ref in games:
        entry = build_game(name, ref, out)
        if entry:
            manifest.append(entry)

    (out / "games.json").write_text(json.dumps(manifest), encoding="utf-8")

    for asset in STATIC.iterdir():
        shutil.copy(asset, out / asset.name)

    print(f"\nBuilt site with {len(manifest)} game(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
