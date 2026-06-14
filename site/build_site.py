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
from diplomacy.utils.export import from_saved_game_format  # noqa: E402

SEASONS = {"S": "Spring", "F": "Fall", "W": "Winter"}
PHASE_TYPES = {"M": "Movement", "R": "Retreats", "A": "Adjustments"}

POWERS = ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True,
                          capture_output=True).stdout


def read_text_at(ref: str, path: str) -> str | None:
    """Raw file contents at a git ref, or None if missing/empty."""
    raw = git("show", f"{ref}:{path}")
    return raw if raw.strip() else None



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


def is_complete(saved: dict) -> bool:
    """Whether the match has ended (solo win or draw)."""
    phases = saved.get("phases") or []
    if phases and phases[-1].get("name") == "COMPLETED":
        return True
    try:
        return bool(from_saved_game_format(saved).is_game_done)
    except Exception:
        return False


def normalize_messages(raw: list | None, phase: str) -> list[dict]:
    """Flatten a saved phase's messages to {phase, sender, recipient, body}.

    Broadcasts use recipient 'GLOBAL'. Convention: messages are PUBLIC ONLY AT
    GAME END (see build_game) — Diplomacy negotiation stays secret while the game
    is live, and is revealed for post-mortem once it's over. Private full-press
    comms (Epic 5) are additionally encrypted per-recipient and would need the
    same end-of-game reveal before they could appear here.
    """
    out = []
    for m in raw or []:
        body = m.get("message") or m.get("body") or ""
        if not body:
            continue
        out.append({
            "phase": m.get("phase", phase),
            "sender": (m.get("sender") or "").upper(),
            "recipient": (m.get("recipient") or "GLOBAL").upper(),
            "body": body,
        })
    return out


def collect_notes(ref: str) -> dict[str, str]:
    """Each power's private strategy notebook (`notes/<POWER>.md`), if any.

    Like messages, notes reveal a power's plans and intentions, so the caller
    publishes them ONLY once the game is over (see build_game) — secret while
    the match is live, revealed for the post-mortem.
    """
    notes: dict[str, str] = {}
    for power in POWERS:
        text = read_text_at(ref, f"notes/{power}.md")
        if text:
            notes[power] = text
    return notes


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
    complete = is_complete(saved)

    game_dir = out / "games" / name
    game_dir.mkdir(parents=True, exist_ok=True)

    phases_meta = []
    messages: list[dict] = []
    for ph in saved["phases"]:
        code = ph["name"]
        messages.extend(normalize_messages(ph.get("messages"), code))
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

    # Full-press comms (Epic 5) live in mail/revealed.json, written by the
    # adjudicator only at game end. Merge them with any engine-native messages.
    if complete:
        revealed_raw = read_json_at(ref, "mail/revealed.json")
        if isinstance(revealed_raw, list):
            messages.extend(normalize_messages(revealed_raw, ""))
            messages.sort(key=lambda m: (m.get("phase", ""), m.get("sender", "")))

    # Messages and notes are revealed only once the game is over (secrecy
    # during play) — a power's notebook gives away its plans just like its mail.
    notes = collect_notes(ref)
    meta = {
        "name": name,
        "title": config.get("name", name),
        "phases": phases_meta,
        "current_phase": phases_meta[-1]["code"],
        "complete": complete,
        "messages": messages if complete else [],
        "messages_locked": (not complete) and bool(messages),
        "notes": notes if complete else {},
        "notes_locked": (not complete) and bool(notes),
    }
    (game_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    revealed = len(meta["messages"])
    locked = " (messages sealed until game end)" if meta["messages_locked"] else ""
    note_n = len(meta["notes"])
    note_locked = " (notes sealed until game end)" if meta["notes_locked"] else ""
    print(f"  + {name}: {len(phases_meta)} phases, {revealed} messages{locked}"
          f", {note_n} notebooks{note_locked}")
    return {
        "name": name,
        "title": meta["title"],
        "phase_count": len(phases_meta),
        "current_phase": meta["current_phase"],
        "complete": complete,
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
