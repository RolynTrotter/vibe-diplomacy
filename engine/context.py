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

from engine import comms, mapviz, query, state
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
                                # collapses to a threaded per-partner summary
    "topology": True,           # engine-derived map geometry: who you border,
                                # which centers are near and through where
    "image": True,              # a labelled PNG of the board, per phase
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
        out.append(_older_threads(older))
    out += [_format_msg(m) for m in recent[-30:]]
    return "\n".join(out)


GIST_CHARS = 110        # enough for the substance of a line, not the pleasantries
THREAD_DEPTH = 3        # older messages kept per partner, most recent last


def _gist(body: str) -> str:
    """One line of a message — collapsed whitespace, trimmed to its substance."""
    text = " ".join((body or "").split())
    if len(text) <= GIST_CHARS:
        return text
    return text[:GIST_CHARS].rsplit(" ", 1)[0] + "…"


def _older_threads(older: list[dict]) -> str:
    """Mail older than the raw window, grouped into a thread per partner.

    A pure count ("GERMANY ×6") tells you a relationship exists but not what
    was agreed in it, so a deal struck three phases back goes invisible right
    when it matters. Keeping the last few lines per partner costs a fraction
    of the full transcript and keeps the relationship legible.
    """
    threads: dict[str, list[dict]] = {}
    for m in older:
        threads.setdefault(m.get("sender", "?"), []).append(m)

    lines = ["_Older mail, threaded by partner "
             "(full text: `read_messages --with <POWER>`):_"]
    for sender, msgs in sorted(threads.items()):
        kept = msgs[-THREAD_DEPTH:]
        span = (msgs[0].get("phase", "?") if len(msgs) == 1
                else f"{msgs[0].get('phase', '?')}–{msgs[-1].get('phase', '?')}")
        head = f"- **{sender}** ×{len(msgs)} ({span})"
        if len(msgs) > len(kept):
            head += f", last {len(kept)}"
        lines.append(head + ":")
        lines += [f"  - [{m.get('phase')}] {_gist(m.get('body', ''))}"
                  for m in kept]
    lines.append("_Standing agreements belong in your notes as DEAL: lines._")
    return "\n".join(lines)


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


TOPOLOGY_HOPS = 3        # far enough to plan an approach, near enough to matter
TOPOLOGY_TARGETS = 10    # centers listed before the section stops earning tokens


def _base(prov: str) -> str:
    """Province code without its coast suffix: 'SPA/SC' -> 'SPA'."""
    return prov.upper().split("/")[0]


def _my_ground(game, power: str) -> set[str]:
    """Provinces you stand in or own a center in — your side of the map."""
    me = game.powers[power]
    return ({_base(u.split()[1]) for u in me.units}
            | {_base(c) for c in me.centers})


def _neighbours(game, prov: str) -> set[str]:
    return {_base(a) for a in query.adjacencies(game, prov)} - {_base(prov)}


def _spread(game, start: set[str]) -> dict[str, tuple[int, set[str]]]:
    """Breadth-first hops outward from `start`.

    Returns {province: (hops, doors)}, where a "door" is the province you
    would move into FIRST on a shortest path there — the actionable half of
    the route, and the square someone else can shut. Adjacency here is the raw
    map graph: it ignores unit type, so a listed route may be army-only or
    fleet-only. The tactical annex says which moves are actually legal; this
    says which parts of the map are near each other.
    """
    seen: dict[str, tuple[int, set[str]]] = {p: (0, set()) for p in start}
    frontier = set(start)
    for hop in range(1, TOPOLOGY_HOPS + 1):
        nxt: dict[str, set[str]] = {}
        for prov in frontier:
            for neighbour in _neighbours(game, prov):
                if neighbour not in seen:
                    # One step off your own ground IS its own door; deeper
                    # provinces inherit the door their predecessor came through.
                    door = {neighbour} if hop == 1 else seen[prov][1]
                    nxt.setdefault(neighbour, set()).update(door)
        if not nxt:
            break
        for prov, vias in nxt.items():
            seen[prov] = (hop, vias)
        frontier = set(nxt)
    return seen


def _borders(game, power: str, mine: set[str]) -> str:
    """Which powers you actually touch, and at which provinces."""
    contacts: dict[str, set[str]] = {}
    for prov in mine:
        for neighbour in _neighbours(game, prov):
            for hit in query.units_at(game, neighbour):
                owner = hit.split(":", 1)[0]
                if owner != power:
                    contacts.setdefault(owner, set()).add(f"{prov}–{neighbour}")
    if not contacts:
        return "- You touch no other power's units right now."
    lines = []
    for owner, pairs in sorted(contacts.items()):
        shown = sorted(pairs)[:4]
        more = f" (+{len(pairs) - len(shown)} more)" if len(pairs) > len(shown) else ""
        lines.append(f"- **{owner}**: {', '.join(shown)}{more}")
    return "\n".join(lines)


def _nearby_centers(game, power: str, reach: dict[str, tuple[int, set[str]]]) -> str:
    """Supply centers you don't own, nearest first, and the way in."""
    mine = set(game.powers[power].centers)
    owners = {_base(c): name for name, p in game.powers.items() for c in p.centers}

    rows = []
    for prov, (hops, doors) in reach.items():
        if prov not in game.map.scs or prov in mine:
            continue
        owner = owners.get(prov)
        rows.append((hops, prov, owner or "neutral", sorted(doors)[:3]))
    if not rows:
        return ""
    rows.sort(key=lambda r: (r[0], r[1]))

    lines = []
    for hops, prov, owner, doors in rows[:TOPOLOGY_TARGETS]:
        if hops == 0:
            # You are standing on a center you don't own yet: holding it
            # through the Fall retreat is what actually converts it.
            where = "you occupy it — hold it through Fall to take it"
        else:
            step = "move" if hops == 1 else "moves"
            route = f" in through {' or '.join(doors)}" if hops > 1 else ""
            where = f"{hops} {step}{route}"
        lines.append(f"- **{prov}** ({owner}) — {where}")
    return "\n".join(lines)


def _topology(game, power: str) -> str:
    """The shape of the map around you — the part agents keep hallucinating.

    The tactical annex answers "what may this unit do this turn"; this answers
    "what is near what", which is the question a plan is built from. Both are
    engine-derived, so neither can drift from the real board.
    """
    mine = _my_ground(game, power)
    if not mine:
        return ""
    reach = _spread(game, mine)
    out = ["Powers whose units touch your ground "
           "(your province–their province):",
           _borders(game, power, mine)]
    centers = _nearby_centers(game, power, reach)
    if centers:
        out += ["",
                f"Supply centers you don't own, within {TOPOLOGY_HOPS} moves "
                "(hops ignore unit type — the annex has the legal moves):",
                centers]
    return "\n".join(out)


def _board_picture(root: Path, game, power: str) -> str:
    """Point the agent at the rendered board, if one could be drawn."""
    path = mapviz.phase_image(root, game)
    if path is None:
        ok, why = mapviz.available()
        if ok:
            return ""
        return (f"_(no board image — install `cairosvg` and a system cairo to "
                f"get one: {why})_")
    color = mapviz.POWER_COLORS.get(power, "your colour")
    return (f"A labelled picture of the current board is at `{path}` — every "
            f"province named, units drawn in their power's colour ({power} is "
            f"**{color}**), legend top-left. **Look at it before you plan.** "
            "If you cannot view images, the sections above carry the same "
            "facts in text.")


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
    if opts["topology"]:
        topology = _topology(game, power)
        if topology:
            sections += ["", "## Board topology (engine-derived)\n" + topology]
    if opts["annex"]:
        sections += [
            "",
            "## Tactical annex (engine-verified, private)\n"
            + _tactical_annex(game, power),
            "",
            "## Rules reminders\n" + RULES_CRIB,
        ]
    if opts["image"]:
        picture = _board_picture(root, game, power)
        if picture:
            sections += ["", "## The board, drawn\n" + picture]
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
        + (" — negotiate first (**negotiate**)," if full_press else ",")
        + " then validate + sign + seal your orders and commit only your own files.",
        "Use the live board (`game_status`, check-board-state) as ground truth; "
        "this brief is a snapshot.",
    ]
    return "\n".join(sections)
