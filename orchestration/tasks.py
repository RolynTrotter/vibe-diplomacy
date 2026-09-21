"""The task text a power is handed for one turn — one builder, three callers.

`run_match` (programmatic conductor), `conduct tasks` (the conduct-match skill's
fan-out), and any future front end all need the SAME words: drift between them
means two powers in one match are playing slightly different games.

Two styles:

* **reply** — the seat has no tools and answers in one message (`raw` backend,
  or a scoped subagent whose reply the conductor pipes back through
  `conduct collect`). The task ends with the exact reply format to produce.
* **agentic** — the seat is a real session that runs the CLIs itself.

Four kinds: `negotiation` (messages only), `orders` (orders only), `combined`
(messages AND orders in one reply, which halves the model calls a full-press
movement phase costs), and `directives` — messages AND written direction to the
power's staff, for a seat whose orders are placed by `orchestration.staff`.

A `directives` task is the only one that never mentions an order. That is the
point of it: the seat is told it commands through subordinates, so it spends
its whole call on language and none of it on tactics it is bad at or on
deciding which tool to reach for. Nothing in this file may name the model on
the other side of that handoff — see the note in `orchestration.staff`.
"""
from __future__ import annotations

from orchestration.player_agent import (COMBINED_FORMAT, DIRECTIVES_FORMAT,
                                        MESSAGES_FORMAT, ORDERS_FORMAT)

REPLY_FORMATS = {
    "negotiation": MESSAGES_FORMAT,
    "orders": ORDERS_FORMAT,
    "combined": COMBINED_FORMAT,
    "directives": DIRECTIVES_FORMAT,
}

KINDS = tuple(REPLY_FORMATS)


#: What a staff seat is asked to direct, per phase type. The words stay in the
#: register of command — a head of government says what it wants held and
#: taken; it does not say "disband A BUR".
_DIRECT = {
    "R": ("where your dislodged units should fall back to, and which are not "
          "worth saving"),
    "A": ("where your new strength should be raised, or which commands to wind "
          "up if you are over-extended"),
    "M": "what you want taken, what must be held, and whom you are fighting",
}


def _what(phase: str) -> str:
    if phase.endswith("R"):
        return "your retreats/disbands"
    if phase.endswith("A"):
        return "your builds/disbands"
    return "your orders"


def build(power: str, kind: str, phase: str, brief: str, *,
          press: str = "none", persona: str | None = None,
          style: str = "reply") -> str:
    """The full task for one power, one phase — brief included.

    `brief` is passed in rather than loaded here so a caller can render it once
    and reuse it (and so this stays a pure function of its inputs).
    """
    if kind not in REPLY_FORMATS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    power = power.upper()
    lead = f"Persona: {persona}\n\n" if persona else ""
    full = press == "full"
    reply = style == "reply"
    trivial = phase.endswith(("R", "A"))    # one decision, no room to negotiate

    if kind == "negotiation":
        body = (
            f"You are {power} in a Diplomacy match. {lead}"
            f"It is {phase} and the negotiation window is open. Acting ONLY as "
            f"{power}, read your inbox and send any messages you want before "
            "orders lock. Do NOT submit orders yet.\n\n"
        )
        if not reply:
            body += (
                "Use the `negotiate` skill: read with `read_messages`, send with "
                "`send_message`, then `scripts/sync.sh` any mail you create.\n\n"
            )
    elif kind == "directives":
        aim = _DIRECT["R" if phase.endswith("R") else
                      "A" if phase.endswith("A") else "M"]
        body = (
            f"You are {power} in a Diplomacy match. {lead}"
            f"It is {phase}. You do not place units yourself — you have a "
            f"general staff for that, and they are competent. Your job is the "
            f"part they cannot do: reading the table, talking to the other "
            f"powers, and telling your staff what you want.\n\n"
            f"Acting ONLY as {power}: "
            + (f"send any messages you want to send, then write your standing "
               f"directions — {aim}.\n\n" if full else
               f"write your standing directions — {aim}. There is no "
               f"negotiation in this match.\n\n")
            + f"Your directions are acted on this phase, so say what you "
              f"actually want. Be concrete about places and aims — \"take "
              f"Portugal before Spain\", \"Munich matters more than Belgium\", "
              f"\"do not let Austria into Serbia\" — and leave the placing of "
              f"units to your staff.\n\n"
        )
        if not reply:
            body += (
                "Send messages with `send_message`, then write your directions "
                f"to `notes/{power}.md` and `scripts/sync.sh` it. Do NOT submit "
                "orders — that is your staff's job, not yours.\n\n"
            )
    elif kind == "combined":
        body = (
            f"You are {power} in a Diplomacy match. {lead}"
            f"It is {phase}. This is your LAST word this phase: acting ONLY as "
            f"{power}, send any final messages AND commit {_what(phase)} in the "
            "same reply. Anything you agree to here you are ordering against "
            "now — there is no later round to adjust in.\n\n"
        )
        if not reply:
            body += (
                "Send messages with `send_message`, then submit in one shot:\n"
                f"     echo \"<orders>\" | scripts/submit.sh {power}\n\n"
            )
    elif reply or trivial:
        body = (
            f"You are {power} in a Diplomacy match. {lead}"
            f"It is {phase}. Decide {_what(phase)} for this phase acting ONLY as "
            f"{power}. Your options are listed in the brief's tactical annex.\n\n"
        )
        if not reply:
            body += ("Submit in one shot:\n"
                     f"  echo \"<orders>\" | scripts/submit.sh {power}\n"
                     "No negotiation or notes update needed this phase.\n\n")
    else:
        steps = []
        if full:
            steps.append("1. (Optional) negotiate first — see the `negotiate` skill.")
        steps.append("2. Decide your moves, then submit them in one shot:\n"
                     "     echo \"A PAR - BUR\\nF BRE - MAO\" | scripts/submit.sh {p}")
        steps.append("3. Update notes/{p}.md with your plan, then `scripts/sync.sh`.")
        body = (
            f"You are {power} in a Diplomacy match. {lead}"
            f"It is {phase}. Play this turn end-to-end acting ONLY as {power}. "
            "Your full brief is below — do NOT re-run `scripts/turn.sh` "
            "(that only regenerates what you already have).\n\n"
            + "\n".join(s.format(p=power) for s in steps)
            + "\n\n"
        )

    task = body + "Your current brief:\n\n" + brief
    if reply:
        task += "\n\n" + REPLY_FORMATS[kind]
    return task


__all__ = ["build", "KINDS", "REPLY_FORMATS"]
