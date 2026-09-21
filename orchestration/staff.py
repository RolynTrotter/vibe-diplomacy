"""The general staff: written directions in, sealed orders out.

A seat with `orders: staff` never writes an order. Its model negotiates, reads
the table and issues **directions** — plain English, no engine syntax, no
province-by-province tactics — and this module turns those into a legal order
per unit and drives them through the same `submit_orders` CLI every other seat
uses. The artifacts are byte-identical to a hand-played seat.

The split exists because the two jobs want different models. Negotiation is
open-ended language; order writing is bounded selection over
`engine.validate.legal_orders`, which is what `engine.staged` does with Jev. A
frontier model spending tokens to decide *which tool to call* and then to
re-derive tactics it is bad at is the waste this removes.

**The playing model is never told any of that.** It is told it has a staff, and
it writes to its staff. Nothing in its task text names a second model, a
vendor, or this module — a seat that can reason about its own order pipeline
can try to game it, and more prosaically every token spent on routing is a
token not spent on the game. If the word "Jev" ever reaches a player's prompt,
something upstream is broken.

Two channels, and they are not the same thing:

* **`TO SELF:` -> `notes/<POWER>.md`** — the durable notebook. It survives the
  phase, it is what the power is shown next turn, and it is where the `DEAL:`
  ledger lives (see `engine.press`). The visualizer reads the same file, which
  is what makes a staff game legible afterwards.
* **`TO STAFF:` -> this request only** — what the power wants done *now*. Never
  written to disk, or last phase's intent would quietly become policy.

The direction channel only works because its state also reaches the
**valuation** request. That is the single point where written intent turns into
the `Priority N/100` every move option is glossed with, and a direction that
does not reach it is prose losing to a number — the oldest lesson on this path.
`write_orders` carries the numbers that proved it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

NOTES_HEADING = "## Standing plan"
#: Kept as an alias so nothing that imported the old name breaks.
DIRECTIVES_HEADING = NOTES_HEADING


@dataclass
class StaffResult:
    power: str
    phase: str = ""
    orders: list[str] = field(default_factory=list)
    ok: bool = False
    error: str | None = None
    issues: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    deal_policy: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"power": self.power, "phase": self.phase, "orders": self.orders,
                "ok": self.ok, "error": self.error, "issues": self.issues,
                "deal_policy": self.deal_policy, "usage": self.usage}


def save_notes(root: Path, power: str, notes: list[str]) -> None:
    """Persist the power's own notebook — its `TO SELF:` lines.

    Overwrite, not append: a notebook that only grows hits the brief's
    truncation cap and starts silently dropping its newest lines, which is
    exactly backwards. `DEAL:` lines are kept verbatim so
    `engine.press.standing_deals` still finds them.

    This is the durable channel. A power writes it every phase and is shown it
    the next one, which is the whole contract — so an empty list leaves the
    previous notebook alone rather than erasing it.
    """
    if not notes:
        return
    path = Path(root) / "notes" / f"{power.upper()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {n}" for n in notes)
    path.write_text(f"# {power.upper()}\n\n{NOTES_HEADING}\n\n{body}\n",
                    encoding="utf-8")


def save_directions(root: Path, power: str, directions: list[str]) -> None:
    """Back-compat alias: directions written as if they were the notebook.

    Kept for callers that have only directions to persist. Prefer `save_notes`
    for the durable channel and pass directions to `write_orders`, which puts
    them in `your_directions_this_turn` where they belong — per phase, not
    forever.
    """
    save_notes(root, power, directions)


def _directions_state(root: Path, power: str,
                      directions: list[str] | None) -> dict | None:
    """This phase's directions, in every state field that carries intent.

    The directions are not written to disk — only into the request. They are
    what this power wants *this phase*; the notebook is what lasts.

    They go in `your_own_plan` as well as their own field because this state is
    handed to the valuation request too, and `your_own_plan` is what that
    question has always read. See `write_orders`: valuation is the one place
    written intent becomes a number, and reaching it is what decides whether a
    direction is obeyed. Measured at S1901M with "Burgundy before Germany gets
    there" — valuation blind to it put ENG 32, SPA 24, BEL 16 and no Burgundy
    at all; valuation shown it put POR 85, BUR 13, naming exactly the two
    provinces the directions named.
    """
    if not directions:
        return None
    from engine import context

    extra: dict = {"your_directions_this_turn": list(directions)}
    plan = ""
    notes_path = Path(root) / "notes" / f"{power.upper()}.md"
    if notes_path.exists():
        # The DEAL: lines come out — they have their own scored field, and that
        # duplication is the kind that does hurt (see `engine.press`).
        text = notes_path.read_text(encoding="utf-8").strip()
        plan = "\n".join(l for l in text.splitlines()
                         if not context.DEAL_RE.match(l)).strip()
    extra["your_own_plan"] = (
        (plan + "\n\n" if plan else "")
        + "This turn:\n" + "\n".join(f"- {d}" for d in directions))
    return extra


def write_orders(root: Path, power: str, directions: list[str] | None = None, *,
                 stab: bool = True, decide=None, values=True) -> StaffResult:
    """Decide this power's orders. Does not submit — see `write_and_submit`.

    `decide` is injectable so the conductor's fake backend and the tests can run
    the whole loop with no API key and no network; it defaults to the staged
    path in `engine.staged`.
    """
    from engine import orders_jev, staged, state, valuation

    power = power.upper()
    game = state.load_game(root)
    result = StaffResult(power=power, phase=game.get_current_phase())
    extra = _directions_state(root, power, directions)

    if decide is None:
        from engine import jev
        ok, why = jev.available(root)
        if not ok:
            result.error = f"no order writer available: {why}"
            return result

        def decide(game, power, extra=None, **kw):
            # The valuation request MUST see the directions. It is the one
            # place written intent becomes a number, and every move option is
            # then glossed with that number — so a direction that skips it is
            # prose competing with `Priority 24/100`, and loses.
            #
            # Measured at S1901M with "Burgundy before Germany gets there":
            #   valuation without the directions -> ENG 32, SPA 24, BEL 16,
            #     BUR absent; Paris supports instead of moving, 3/3 runs.
            #   valuation with them -> POR 85, BUR 13; Paris takes Burgundy.
            picks = None
            if values and game.phase_type == "M":
                picks = valuation.province_values(
                    game, power, root=root,
                    state=orders_jev.build_state(game, power, root=root,
                                                 extra=extra))
            return staged.choose_orders_staged(game, power, root=root,
                                               values=picks, stab=stab,
                                               extra=extra, **kw)

    chosen = decide(game, power, extra=extra)
    result.orders = list(chosen.orders)
    result.usage = dict(chosen.usage or {})
    result.issues = [f"{i.severity}: {i.order} — {i.message}"
                     for i in (chosen.issues or [])]
    result.deal_policy = list(getattr(chosen, "deal_policy", []) or [])
    if chosen.errors:
        result.error = "; ".join(chosen.errors)[:500]
    result.ok = bool(result.orders) and not chosen.errors
    return result


def write_and_submit(root: Path, power: str, directions: list[str] | None = None,
                     *, notes: list[str] | None = None, repo: Path | None = None,
                     stab: bool = True, decide=None) -> StaffResult:
    """Directions in, sealed orders committed. The whole staff job.

    `notes` is the power's own notebook (its `TO SELF:` lines) and is persisted;
    `directions` are this phase's orders to the staff and are not. Both reach
    the order writer — the notebook through `engine.press`, the directions as
    `your_directions_this_turn` — which is why the seat never has to know the
    difference between them beyond "one lasts, one is for now".

    Submission goes through `orchestration.submit_orders` rather than writing
    the file here, so a staff seat is signed, sealed and validated by exactly
    the same code path as a seat that typed its own orders.
    """
    power = power.upper()
    save_notes(root, power, notes or [])
    if directions and not notes:
        # Nothing durable was written this phase; keep the directions as the
        # notebook so the power is not handed a blank page next turn.
        save_notes(root, power, directions)
    result = write_orders(root, power, directions, stab=stab, decide=decide)
    if not result.orders:
        result.ok = False
        result.error = result.error or "the staff produced no orders"
        return result

    repo = Path(repo or Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env.pop("ADJUDICATOR_PRIVATE_KEY", None)   # players never see this key
    proc = subprocess.run(
        [sys.executable, "-m", "orchestration.submit_orders",
         "--root", str(root), "--power", power],
        cwd=repo, input="\n".join(result.orders), text=True,
        capture_output=True, env=env)
    if proc.returncode != 0:
        result.ok = False
        result.error = (proc.stderr.strip() or proc.stdout.strip())[:500]
    else:
        result.ok = True
    return result


__all__ = ["StaffResult", "save_notes", "save_directions", "write_orders",
           "write_and_submit", "NOTES_HEADING", "DIRECTIVES_HEADING"]
