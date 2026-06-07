"""Selective context for a single power — the slice a subagent player receives.

In conductor mode one session spawns each power as a fresh-context subagent.
"Selective context" means each subagent is handed ONLY what its power may know:
the public board and recent history, plus that power's OWN notes and decrypted
inbox. It never receives another power's notes, inbox, or keys.

`power_brief` returns a ready-to-paste markdown briefing. Everything in it is
either public (board/history) or belongs to `power`.
"""
from __future__ import annotations

from pathlib import Path

from engine import comms, query, state


def _last_phase_recap(game) -> str:
    """Public orders + results from the most recently resolved phase."""
    try:
        phase = game.order_history.last_value()
        results = game.result_history.last_value()
    except (AttributeError, IndexError, KeyError):
        return "_(no resolved phases yet — this is the opening.)_"
    if not phase:
        return "_(no orders last phase.)_"
    lines = []
    for power, orders in sorted(phase.items()):
        if orders:
            lines.append(f"- **{power}**: {', '.join(orders)}")
    res = []
    for unit, outcome in (results or {}).items():
        tags = [str(r) for r in outcome if str(r)]
        if tags:
            res.append(f"{unit}: {', '.join(tags)}")
    recap = "\n".join(lines) if lines else "_(all holds)_"
    if res:
        recap += "\n\nNotable results: " + "; ".join(res)
    return recap


def _my_notes(root: Path, power: str) -> str:
    path = Path(root) / "notes" / f"{power.upper()}.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or "_(empty)_"
    return "_(no notes yet — start your plan with consult-notes.)_"


def _my_inbox(root: Path, power: str) -> str:
    privkey = comms.load_privkey(root, power)
    if not privkey:
        return "_(no key yet — you haven't claimed your seat.)_"
    msgs = comms.read_inbox(root, power, privkey)
    if not msgs:
        return "_(empty.)_"
    out = []
    for m in msgs[-30:]:  # most recent
        tag = "broadcast" if m.get("recipient") == comms.GLOBAL else f"to you"
        verified = "" if m.get("verified", True) else " ⚠unverified"
        out.append(f"- [{m.get('phase')}] **{m.get('sender')}** ({tag}{verified}): "
                   f"{m.get('body')}")
    return "\n".join(out)


def power_brief(root: Path, power: str) -> str:
    """A markdown briefing containing only what `power` is allowed to see."""
    power = power.upper()
    game = state.load_game(root)
    config = state.load_config(root)
    phase = game.get_current_phase()
    summary = query.board_summary(game)
    me = summary["powers"].get(power, {})
    full_press = config.get("press") == "full"

    # Public scoreboard: counts only (positions are on the board / in history).
    board = []
    for name, info in sorted(summary["powers"].items(),
                             key=lambda kv: -kv[1]["center_count"]):
        mark = " ← you" if name == power else ""
        board.append(f"- {name}: {info['center_count']} centers, "
                     f"{info['unit_count']} units{mark}")

    adj = me.get("adjustment", 0)
    adj_note = ("none" if adj == 0
                else f"build {adj}" if adj > 0 else f"disband {-adj}")

    sections = [
        f"# You are {power} — {config.get('name', 'match')} — {phase}",
        f"Press: **{'full (negotiation on)' if full_press else 'gunboat (no comms)'}**",
        "",
        f"## Your position\n- Units: {', '.join(me.get('units', [])) or 'none'}"
        f"\n- Centers: {', '.join(me.get('centers', [])) or 'none'}"
        f"\n- Adjustment due: {adj_note}",
        "",
        "## Supply-center standings (public)\n" + "\n".join(board),
        "",
        "## Last phase (public)\n" + _last_phase_recap(game),
        "",
        "## Your private notes\n" + _my_notes(root, power),
    ]
    if full_press:
        sections += ["", "## Your inbox (private to you)\n" + _my_inbox(root, power)]

    sections += [
        "",
        "## Do now",
        "1. If you have no seat yet, claim it (`join-game --power " + power + "`).",
        "2. Run **play-a-turn** for " + power + " this phase"
        + (" — negotiate first (**negotiate**), then" if full_press else ",")
        + " then validate + sign + seal your orders and commit only your own files.",
        "Use the live board (`game_status`, check-board-state) as ground truth; "
        "this brief is a snapshot.",
    ]
    return "\n".join(sections)
