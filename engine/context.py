"""Selective context for a single power — the slice a subagent player receives.

In conductor mode one session spawns each power as a fresh-context subagent.
"Selective context" means each subagent is handed ONLY what its power may know:
the public board and recent history, plus that power's OWN notes and decrypted
inbox. It never receives another power's notes, inbox, or keys.

`power_brief` returns a ready-to-paste markdown briefing. Everything in it is
either public (board/history) or belongs to `power`.
"""
from __future__ import annotations

import re
from pathlib import Path

from engine import comms, query, state
from engine.coherence import parse_order as _parse

# Player-facing brief sections are individually toggleable so verbose ones can
# be turned off per match: set a `brief` mapping in game/config.json (written
# by `new_game --brief-json` / the match spec's `brief:` key).
DEFAULT_BRIEF_OPTIONS = {
    "outcomes": True,           # per-order feedback on your last resolved phase
    "digest": True,             # yearly center-change digest
    "annex": True,              # tactical annex + rules crib
    "commitments": True,        # DEAL: ledger surfaced from your notes
    "inbox_recent_only": True,  # raw mail from the last two phases; older mail
                                # collapses to per-partner counts
}


def brief_options(config: dict) -> dict:
    opts = dict(DEFAULT_BRIEF_OPTIONS)
    for key, value in (config.get("brief") or {}).items():
        if key in opts:
            opts[key] = bool(value)
    return opts


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


NOTES_CHAR_CAP = 2500  # ~250 words with markdown overhead; keeps briefs bounded


def _my_notes(root: Path, power: str) -> str:
    path = Path(root) / "notes" / f"{power.upper()}.md"
    if not path.exists():
        return "_(no notes yet — start your plan with consult-notes.)_"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return "_(empty)_"
    if len(text) > NOTES_CHAR_CAP:
        text = (text[:NOTES_CHAR_CAP].rsplit("\n", 1)[0]
                + "\n\n_(notes truncated — keep them under 250 words; "
                  "overwrite, don't append.)_")
    return text


def _format_msg(m: dict) -> str:
    tag = "broadcast" if m.get("recipient") == comms.GLOBAL else "to you"
    verified = "" if m.get("verified", True) else " ⚠unverified"
    return (f"- [{m.get('phase')}] **{m.get('sender')}** ({tag}{verified}): "
            f"{m.get('body')}")


def _my_inbox(root: Path, power: str, recent_only: bool = True) -> str:
    privkey = comms.load_privkey(root, power)
    if not privkey:
        return "_(no key yet — you haven't claimed your seat.)_"
    msgs = comms.read_inbox(root, power, privkey)
    if not msgs:
        return "_(empty.)_"
    if not recent_only:
        return "\n".join(_format_msg(m) for m in msgs[-30:])

    # Raw mail only from the last two phases that produced any; everything
    # older collapses to a per-partner digest so long games stop paying for
    # their whole comms history in every brief.
    phases_seen: list[str] = []
    for m in msgs:
        if m.get("phase") not in phases_seen:
            phases_seen.append(m.get("phase"))
    recent_phases = set(phases_seen[-2:])
    recent = [m for m in msgs if m.get("phase") in recent_phases]
    older = [m for m in msgs if m.get("phase") not in recent_phases]

    out = []
    if older:
        counts: dict[str, list] = {}
        for m in older:
            c = counts.setdefault(m.get("sender", "?"), [0, ""])
            c[0] += 1
            c[1] = m.get("phase", "")
        digest = "; ".join(f"{s} ×{n} (last {ph})"
                           for s, (n, ph) in sorted(counts.items()))
        out.append(f"_Older mail (digest): {digest}. Standing agreements "
                   f"belong in your notes as DEAL: lines; reread a thread "
                   f"with `read_messages --with <POWER>` if you must._")
    out += [_format_msg(m) for m in recent[-30:]]
    return "\n".join(out)


def _my_last_outcomes(game, power: str) -> str:
    """What actually happened to YOUR orders last phase, with the why.

    Weak models never close this loop themselves — a support that was void
    three phases running stays void forever unless someone says why.

    Looks back to your most recent MOVEMENT phase (retreat/adjustment orders
    carry no learning signal), so the feedback survives an intervening winter.
    """
    try:
        pairs = list(game.order_history.reversed_items())
    except (AttributeError, TypeError):
        return ""
    phase_key, orders, mine = None, None, []
    for key, value in pairs:
        if str(key).endswith("M") and (value or {}).get(power):
            phase_key, orders, mine = key, value, value[power]
            break
    if not mine:
        return ""
    results = game.result_history.get(phase_key) or {}

    by_loc: dict[str, tuple[str, object]] = {}
    for pw, olist in orders.items():
        for o in olist or []:
            p = _parse(o)
            if p.loc:
                by_loc[p.loc] = (pw, p)

    lines, ok = [], 0
    for o in mine:
        p = _parse(o)
        unit = " ".join(o.split()[:2])
        tags = [str(t) for t in (results or {}).get(unit, []) if str(t)]
        if not tags:
            ok += 1
            continue
        if "void" in tags and p.kind in ("SUP_M", "SUP_H", "CONVOY"):
            actual = by_loc.get(p.target)
            if actual is None:
                why = f"VOID — nothing at {p.target} was ordered at all"
            else:
                pw, ap = actual
                whose = "your own" if pw == power else f"{pw}'s"
                why = f"VOID — {whose} unit was actually ordered {ap.raw!r}"
        elif "no convoy" in tags:
            why = "NO CONVOY — no fleet carried this move"
        elif "cut" in tags:
            why = "support CUT — the supporting unit was attacked"
        elif "bounce" in tags:
            why = "bounced (met equal or greater force)"
            if "dislodged" in tags:
                why += " and the unit was DISLODGED"
        elif "dislodged" in tags:
            why = "the unit was DISLODGED"
        else:
            why = ", ".join(tags)
        lines.append(f"- {o} → {why}")
    if not lines:
        return f"_All {ok} of your orders in {phase_key} succeeded._"
    if ok:
        lines.append(f"- ({ok} other order(s) succeeded.)")
    return f"_{phase_key}:_\n" + "\n".join(lines)


DEAL_RE = re.compile(r"^\s*(?:[-*]\s*)?DEAL:\s*(.+?)\s*$", re.MULTILINE)


def _commitments(root: Path, power: str, full_press: bool) -> str:
    """The DEAL: ledger — standing agreements pulled from your own notes.

    Read from the RAW notes file (not the truncated brief copy) so a bloated
    notebook can never silently drop a treaty.
    """
    path = Path(root) / "notes" / f"{power.upper()}.md"
    deals = DEAL_RE.findall(path.read_text(encoding="utf-8")) if path.exists() else []
    if deals:
        body = "\n".join(f"- {d}" for d in deals)
        return (body + "\nCheck your orders against these before submitting — "
                "breaking one should be a decision, not an accident.")
    if full_press:
        return ("_(none recorded — log agreements in your notes as lines like "
                "`DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end "
                "1903` and they will be surfaced here.)_")
    return ""


def _phase_year(phase: str) -> str:
    return phase[1:5] if len(phase) >= 5 else phase


def _center_digest(game) -> str:
    """One line per year of supply-center changes — the arc of the game.

    Ephemeral agents otherwise only see the last phase; this is the cheapest
    possible long-horizon memory (who is snowballing, which alliance fired).
    """
    snaps: list[tuple[str, dict[str, set]]] = []
    try:
        for phase, st in game.state_history.items():
            centers = st.get("centers") if isinstance(st, dict) else None
            if centers:
                snaps.append((str(phase),
                              {p: set(c) for p, c in centers.items()}))
    except AttributeError:
        pass
    snaps.append((game.get_current_phase(),
                  {n: set(p.centers) for n, p in game.powers.items()}))
    if len(snaps) < 2:
        return ""

    by_year: dict[str, dict[str, list[str]]] = {}
    for (_, prev), (phase, cur) in zip(snaps, snaps[1:]):
        year = _phase_year(phase)
        for name in cur:
            gained = sorted(cur[name] - prev.get(name, set()))
            lost = sorted(prev.get(name, set()) - cur[name])
            if gained or lost:
                deltas = by_year.setdefault(year, {}).setdefault(name, [])
                deltas += [f"+{c}" for c in gained] + [f"−{c}" for c in lost]
    if not by_year:
        return ""
    lines = []
    for year in sorted(by_year):
        parts = [f"{name} {' '.join(d)}"
                 for name, d in sorted(by_year[year].items())]
        lines.append(f"- {year}: " + "; ".join(parts))
    return "\n".join(lines)


def _occupant_tag(game, prov: str, me: str) -> str:
    """' (GERMANY A)' if a unit stands in prov, '' if empty."""
    hits = query.units_at(game, prov)
    if not hits:
        return ""
    owner, unit = hits[0].split(": ", 1)
    who = "your" if owner == me else owner
    return f" ({who} {unit.split()[0]})"


def _tactical_annex(game, power: str) -> str:
    """Engine-derived geometry so agents stop hallucinating (or re-querying) it:
    legal destinations per unit, threats to your centers, retreat/build options.
    """
    possible = game.get_all_possible_orders()
    locs = game.get_orderable_locations(power)
    ptype = game.phase_type

    if ptype == "M":
        me = game.powers[power]
        lines = []
        for loc in locs:
            opts = possible.get(loc) or []
            dests = sorted({o.split(" - ")[1].replace(" VIA", "")
                            for o in opts if " - " in o and " S " not in o
                            and " C " not in o})
            unit = next((u for u in me.units
                         if u.split()[1].split("/")[0] == loc.split("/")[0]), loc)
            shown = [d + _occupant_tag(game, d.split("/")[0], power)
                     for d in dests]
            lines.append(f"- {unit} can move to: {', '.join(shown) or '(nowhere)'}")

        threats = []
        for center in sorted(me.centers):
            for hit in {h for adj in query.adjacencies(game, center)
                        for h in query.units_at(game, adj)}:
                owner, unit = hit.split(": ", 1)
                if owner != power:
                    threats.append(f"- {center}: {owner} {unit} is adjacent")
        out = "Legal moves for your units (engine-verified — do not invent "\
              "others):\n" + "\n".join(lines)
        if threats:
            out += "\n\nEnemy units adjacent to your centers:\n" + \
                   "\n".join(sorted(threats))
        return out

    # Retreat / adjustment phases: just enumerate the choices.
    lines = []
    for loc in locs:
        opts = possible.get(loc) or []
        if opts:
            lines.append(f"- {loc}: {', '.join(sorted(opts))}")
    label = ("Retreat options" if ptype == "R"
             else "Build/disband options (one per adjustment owed)")
    return f"{label}:\n" + ("\n".join(lines) or "- none")


RULES_CRIB = (
    "- A center changes hands only when a unit occupies it at the END of a "
    "Fall move/retreat; vacating a center does NOT lose it.\n"
    "- A support is cut if the supporting unit is attacked from any province "
    "(except the one it is supporting into).\n"
    "- 'A X S A Y - Z' only works if Y - Z is actually ordered this phase — "
    "coordinate it, don't assume it."
)


def power_brief(root: Path, power: str) -> str:
    """A markdown briefing containing only what `power` is allowed to see."""
    power = power.upper()
    game = state.load_game(root)
    config = state.load_config(root)
    opts = brief_options(config)
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
    ]
    if opts["outcomes"]:
        outcomes = _my_last_outcomes(game, power)
        if outcomes:
            sections += ["", "## Your last orders — what happened and why\n"
                             + outcomes]
    if opts["digest"]:
        digest = _center_digest(game)
        if digest:
            sections += ["", "## Center changes so far (public)\n" + digest]
    if opts["annex"]:
        sections += [
            "",
            "## Tactical annex (engine-verified, private)\n"
            + _tactical_annex(game, power),
            "",
            "## Rules reminders\n" + RULES_CRIB,
        ]
    sections += ["", "## Your private notes\n" + _my_notes(root, power)]
    if opts["commitments"]:
        ledger = _commitments(root, power, full_press)
        if ledger:
            sections += ["", "## Your commitments (DEAL: lines from your notes)\n"
                             + ledger]
    if full_press:
        sections += ["", "## Your inbox (private to you)\n"
                         + _my_inbox(root, power,
                                     recent_only=opts["inbox_recent_only"])]

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
