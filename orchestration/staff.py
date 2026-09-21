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

Directions reach the order writer two ways, and both matter:

* `your_directions_this_turn` — this phase only, the freshest statement of
  intent, right next to the board in the same request.
* `notes/<POWER>.md` — persisted, so they survive into later phases and so the
  `DEAL:` ledger keeps working (see `engine.press`). The visualizer reads the
  same file, which is what makes a staff game legible afterwards.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DIRECTIVES_HEADING = "## Standing directions"


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


def save_directions(root: Path, power: str, directions: list[str]) -> None:
    """Persist this phase's directions as the power's notes.

    Overwrite, not append: a notebook that only grows hits the brief's
    truncation cap and starts silently dropping the newest lines, which is
    exactly backwards. `DEAL:` lines the model wrote are kept verbatim so
    `engine.press.standing_deals` still finds them.
    """
    if not directions:
        return
    path = Path(root) / "notes" / f"{power.upper()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {d}" for d in directions)
    path.write_text(f"# {power.upper()}\n\n{DIRECTIVES_HEADING}\n\n{body}\n",
                    encoding="utf-8")


def write_orders(root: Path, power: str, directions: list[str] | None = None, *,
                 stab: bool = True, decide=None, values=True) -> StaffResult:
    """Decide this power's orders. Does not submit — see `write_and_submit`.

    `decide` is injectable so the conductor's fake backend and the tests can run
    the whole loop with no API key and no network; it defaults to the staged
    path in `engine.staged`.
    """
    from engine import staged, state, valuation

    power = power.upper()
    game = state.load_game(root)
    result = StaffResult(power=power, phase=game.get_current_phase())
    extra = {"your_directions_this_turn": list(directions)} if directions else None

    if decide is None:
        from engine import jev
        ok, why = jev.available(root)
        if not ok:
            result.error = f"no order writer available: {why}"
            return result

        def decide(game, power, **kw):
            picks = (valuation.province_values(game, power, root=root)
                     if values and game.phase_type == "M" else None)
            return staged.choose_orders_staged(game, power, root=root,
                                               values=picks, stab=stab, **kw)

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
                     *, repo: Path | None = None, stab: bool = True,
                     decide=None) -> StaffResult:
    """Directions in, sealed orders committed. The whole staff job.

    Submission goes through `orchestration.submit_orders` rather than writing
    the file here, so a staff seat is signed, sealed and validated by exactly
    the same code path as a seat that typed its own orders.
    """
    power = power.upper()
    if directions:
        save_directions(root, power, directions)
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


__all__ = ["StaffResult", "save_directions", "write_orders", "write_and_submit",
           "DIRECTIVES_HEADING"]
