"""The diplomatic half of Jev's state: notes, standing deals, mail, outcomes.

`engine.orders_jev.build_state` describes the board. A power that orders units
while ignoring what it agreed to last phase is playing a different game from
everyone else, so this module supplies the other half — the same material
`engine.context` already assembles for a human or agent player, reshaped as
structured state rather than markdown prose.

Structured, not prose, for the reason that keeps recurring on this path: a fact
in prose loses to a number. A deal buried in a paragraph of notes is a sentence
competing with a `Priority 2/100`; the same deal as a row in
`your_standing_deals`, and as an explicit `keep`/`break` decision in
`deal_policy_this_turn`, is a field the selection can actually read.

Everything here is private to one power and is read from that power's own files
only. Nothing reaches for another power's notes, mail or keys — an inbox needs
the power's private key in `secrets/`, and without it this degrades to empty
rather than raising.
"""
from __future__ import annotations

from pathlib import Path

from diplomacy import Game

from engine import comms, context, state as state_mod

#: Raw mail is kept for this many of the most recent phases that produced any;
#: everything older collapses to a gist per partner. Mirrors `engine.context`.
RAW_PHASES = 2
THREAD_DEPTH = 3
GIST_CHARS = 110


def _inbox(root: Path, power: str) -> dict | None:
    """This power's decrypted mail, split into recent raw and older gists.

    Returns None when there is no key or no mail — a gunboat game, or a seat
    that has not been claimed. Callers treat that as "no press section".
    """
    try:
        privkey = comms.load_privkey(root, power)
        if not privkey:
            return None
        msgs = comms.read_inbox(root, power, privkey)
    except Exception:
        return None
    if not msgs:
        return None

    phases: list[str] = []
    for m in msgs:
        if m.get("phase") not in phases:
            phases.append(m.get("phase"))
    recent_phases = set(phases[-RAW_PHASES:])

    recent, older = [], {}
    for m in msgs:
        row = {
            "phase": m.get("phase"),
            "from": m.get("sender"),
            "to": "everyone" if m.get("recipient") == comms.GLOBAL else "you",
            "body": m.get("body", ""),
        }
        if not m.get("verified", True):
            # An unsigned or badly-signed message may be a forgery. Say so in
            # the row itself; a caveat kept somewhere else does not travel.
            row["signature_verified"] = False
        if m.get("phase") in recent_phases:
            recent.append(row)
        else:
            older.setdefault(m.get("sender", "?"), []).append(row)

    digest = {}
    for sender, rows in older.items():
        kept = rows[-THREAD_DEPTH:]
        digest[sender] = {
            "messages": len(rows),
            "span": f"{rows[0]['phase']}–{rows[-1]['phase']}",
            "last": [{"phase": r["phase"], "gist": _gist(r["body"])} for r in kept],
        }
    out = {"recent_messages": recent[-30:]}
    if digest:
        out["earlier_by_partner"] = digest
    return out


def _gist(body: str) -> str:
    text = " ".join((body or "").split())
    if len(text) <= GIST_CHARS:
        return text
    return text[:GIST_CHARS].rsplit(" ", 1)[0] + "…"


def standing_deals(root: Path, power: str) -> list[str]:
    """The `DEAL:` lines from this power's own notes, as a list.

    Read from the raw notes file, like `engine.context._commitments`, so a
    long notebook can never silently drop a treaty at the truncation point.
    """
    path = Path(root) / "notes" / f"{power.upper()}.md"
    if not path.exists():
        return []
    return [d.strip() for d in
            context.DEAL_RE.findall(path.read_text(encoding="utf-8"))]


def diplomatic_state(root: Path | None, game: Game, power: str) -> dict:
    """Named state fields for the private, diplomatic side of a position.

    Only fields with something in them are returned. An empty section is worse
    than an absent one: it reads as a positive statement that there is nothing
    to honour, and it costs tokens to say so.
    """
    power = power.upper()
    if root is None:
        return {}
    root = Path(root)
    out: dict = {}

    deals = standing_deals(root, power)

    notes_path = root / "notes" / f"{power}.md"
    if notes_path.exists():
        text = notes_path.read_text(encoding="utf-8").strip()
        if len(text) > context.NOTES_CHAR_CAP:
            text = text[:context.NOTES_CHAR_CAP].rsplit("\n", 1)[0]
        # The DEAL: lines get a field of their own below, so they come out of
        # the prose here. Saying the same thing twice is the failure this path
        # keeps running into: two statements of one fact read as two facts, and
        # the duplicate competes with the field that is actually scored.
        text = "\n".join(l for l in text.splitlines()
                          if not context.DEAL_RE.match(l)).strip()
        if text:
            out["your_own_plan"] = text

    if deals:
        out["your_standing_deals"] = deals

    try:
        press = state_mod.load_config(root).get("press") == "full"
    except Exception:
        press = True
    if press:
        inbox = _inbox(root, power)
        if inbox:
            out["your_inbox"] = inbox

    try:
        outcomes = context._my_last_outcomes(game, power)
    except Exception:
        outcomes = ""
    if outcomes:
        out["what_happened_to_your_last_orders"] = outcomes
    return out


KEEP, BREAK = "keep", "break"


def stab_questions(deals: list[str], power: str) -> dict:
    """One `keep`/`break` Choice per standing deal.

    Asked as its own decision rather than left implicit in the per-unit
    choices, because implicitly it is never made: a deal is prose and the unit
    questions are scored in centres, so the prose loses every time. Deciding it
    once, up front, turns it into a field the order stages read.

    Keep leads the ballot. Option order measurably biases the answer (see
    `engine.staged`), and the default in Diplomacy is that an agreement holds —
    a stab should have to win the argument.
    """
    from typesafe_sdk import Choice

    questions = {}
    for index, deal in enumerate(deals):
        questions[f"deal_{index}"] = Choice(
            instructions=(
                f"You are {power}. You agreed: \"{deal}\". Do you honour that "
                f"this turn, or break it? Weigh what breaking it wins you on "
                f"this board against the fact that the other power will see it "
                f"resolve and will play the rest of the game accordingly."),
            criteria={
                KEEP: ("Honour it this turn. Order nothing that violates it, "
                       "and keep the partner's trust for later turns."),
                BREAK: ("Break it this turn. Take the ground the agreement was "
                        "keeping you out of, and expect the partner to treat "
                        "you as hostile from now on."),
            },
        )
    return questions


def stab_policy(deals: list[str], state: dict, *, ask) -> list[dict]:
    """Decide each standing deal, as rows to hang on the order request.

    Returns one row per deal: the deal text, `keep` or `break`, and how sure.
    The probability is carried through rather than reduced to the label so a
    marginal call reads as marginal downstream.
    """
    if not deals:
        return []
    questions = stab_questions(deals, state.get("you_are", ""))
    response = ask(state, questions)
    rows = []
    for index, deal in enumerate(deals):
        answer = response.answers.get(f"deal_{index}")
        if answer is None:
            continue
        probs = dict(answer.probabilities or {})
        rows.append({
            "deal": deal,
            "this_turn": answer.choice,
            "instruction": ("Your orders this turn must not violate this."
                            if answer.choice == KEEP else
                            "You are breaking this deal this turn; the ground it "
                            "protected is fair game."),
            "confidence": round(probs.get(answer.choice, answer.confidence or 0), 3),
        })
    return rows
