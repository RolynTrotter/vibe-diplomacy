"""Build the static replay viewer for every match under `games/`.

A match's `game.json` (engine saved-game format) already holds every phase's
board and orders, so each phase is rendered to an SVG once and the page only
loads static files. Messages and notes reveal a power's plans, so they are
published only once a game is over.

    ./dip site --serve 8000
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
from pathlib import Path

from diplomacy import Game

from vibe import mapviz
from vibe.game import ALL, POWERS, ROOT, Match

STATIC = Path(__file__).resolve().parent / "static"

SEASONS = {"S": "Spring", "F": "Fall", "W": "Winter"}
PHASE_TYPES = {"M": "Movement", "R": "Retreats", "A": "Adjustments"}


def phase_label(code: str) -> str:
    """'S1901M' -> 'Spring 1901 — Movement'."""
    if len(code) >= 6 and code[0] in SEASONS:
        season, year, kind = SEASONS[code[0]], code[1:5], PHASE_TYPES.get(code[-1], "")
        return f"{season} {year} — {kind}".rstrip(" —")
    return code


def viewer_messages(match: Match) -> list[dict]:
    """One {phase, sender, recipient, body} per recipient, as the viewer wants."""
    out = []
    for m in match.messages():
        for to in m["to"]:
            out.append({"phase": m["phase"], "sender": m["sender"],
                        "recipient": "GLOBAL" if to == ALL else to, "body": m["body"]})
    return out


def build_game(match: Match, out: Path) -> dict | None:
    name = match.name
    saved = json.loads((match.path / "game.json").read_text())
    if not saved.get("phases"):
        return None
    complete = bool(match.ended())

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
        svg_file = game_dir / f"{code}.svg"
        if not svg_file.exists():
            svg_file.write_text(mapviz.board_svg(game, legend=False), encoding="utf-8")
        phases_meta.append({
            "code": code, "label": phase_label(code),
            "svg": f"games/{name}/{code}.svg",
            "centers": {p: len(c) for p, c in ph["state"].get("centers", {}).items()},
            "orders": orders,
        })

    messages = viewer_messages(match)
    notes = {p: match.notes(p) for p in match.powers if match.notes(p).strip()}
    meta = {
        "name": name, "title": name, "phases": phases_meta,
        "current_phase": phases_meta[-1]["code"], "complete": complete,
        "messages": messages if complete else [],
        "messages_locked": (not complete) and bool(messages),
        "notes": notes if complete else {},
        "notes_locked": (not complete) and bool(notes),
    }
    (game_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"  + {name}: {len(phases_meta)} phases"
          + ("" if complete else " (live: messages and notes hidden until it ends)"))
    return {"name": name, "title": name, "phase_count": len(phases_meta),
            "current_phase": meta["current_phase"], "complete": complete}


def main(args) -> int:
    out = (ROOT / args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest = [e for m in Match.all() if (e := build_game(m, out))]
    (out / "games.json").write_text(json.dumps(manifest), encoding="utf-8")
    for asset in STATIC.iterdir():
        shutil.copy(asset, out / asset.name)
    print(f"Built the viewer for {len(manifest)} match(es) -> {out}")
    if args.serve:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(out))
        print(f"Serving at http://localhost:{args.serve}  (Ctrl-C to stop)")
        http.server.ThreadingHTTPServer(("127.0.0.1", args.serve), handler).serve_forever()
    return 0
