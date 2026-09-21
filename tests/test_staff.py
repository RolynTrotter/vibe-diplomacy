"""Staff seats: the model negotiates, the staff places the units.

The invariant these pin is as much about what a player is NOT told as about
what the pipeline does. A seat that can reason about its own order writer can
try to game it, and every token it spends deciding which tool to call is a
token not spent on the game.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from diplomacy import Game

from orchestration import staff, tasks
from orchestration.match_spec import MatchSpec
from orchestration.player_agent import extract_directives, extract_messages

REPO = Path(__file__).resolve().parent.parent

REPLY = """TO ENGLAND: Channel DMZ? I will keep my fleets south.
TO ALL: I want no quarrel in the west this year.

```
- Take Iberia this year, Portugal before Spain
- Munich matters more than Belgium
- A PAR - BUR
- Do not let Italy into Marseilles
- DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end 1903
```
"""


# --------------------------------------------------------------------------- #
# What the player is told
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("press", ["full", "none"])
@pytest.mark.parametrize("phase", ["S1901M", "F1901R", "W1901A"])
def test_a_directives_task_never_mentions_an_order(press, phase):
    task = tasks.build("FRANCE", "directives", phase, "<brief>", press=press)
    lowered = task.lower()
    for banned in ("jev", "typesafe", "submit.sh", "submit_orders",
                   "engine syntax", "a par - bur"):
        assert banned not in lowered, f"a staff seat must not see {banned!r}"
    assert "staff" in lowered, "it is told it commands through subordinates"


def test_no_skill_names_the_order_writer():
    """If a player-facing skill says 'Jev', something upstream is broken."""
    hits = [p for p in (REPO / ".claude").rglob("*.md")
            if "jev" in p.read_text(encoding="utf-8").lower()]
    assert not hits, f"agent-facing files naming the order writer: {hits}"


def test_the_other_kinds_still_ask_for_orders():
    """The staff path is additive — a `self` seat is untouched."""
    task = tasks.build("FRANCE", "combined", "S1901M", "<brief>", press="full")
    assert "orders" in task.lower()


# --------------------------------------------------------------------------- #
# Parsing a reply
# --------------------------------------------------------------------------- #
def test_directions_are_intent_and_orders_are_dropped():
    lines = extract_directives(REPLY)
    assert "Take Iberia this year, Portugal before Spain" in lines
    assert "DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end 1903" in lines
    assert not any(l.startswith("A PAR") for l in lines), (
        "a seat doing its staff's job must not slip an order into the notes")
    assert [r for r, _ in extract_messages(REPLY)] == ["ENGLAND", "ALL"]


def test_directions_survive_without_a_fenced_block():
    lines = extract_directives("TO ALL: hi\n- Hold the Balkans\n- Take Greece\n")
    assert lines == ["Hold the Balkans", "Take Greece"]


# --------------------------------------------------------------------------- #
# The handoff
# --------------------------------------------------------------------------- #
def test_directions_are_persisted_where_the_order_writer_reads_them(tmp_path):
    from engine import press

    staff.save_directions(tmp_path, "FRANCE", extract_directives(REPLY))
    st = press.diplomatic_state(tmp_path, Game(), "FRANCE")
    assert "Take Iberia" in st["your_own_plan"]
    assert st["your_standing_deals"] == [
        "ENGLAND — Channel DMZ, no fleets in ENG — until end 1903"]


def test_directions_overwrite_rather_than_accumulate(tmp_path):
    """A notebook that only grows hits the cap and drops the newest lines."""
    staff.save_directions(tmp_path, "FRANCE", ["Take Iberia"])
    staff.save_directions(tmp_path, "FRANCE", ["Turn on Germany"])
    text = (tmp_path / "notes" / "FRANCE.md").read_text(encoding="utf-8")
    assert "Turn on Germany" in text and "Take Iberia" not in text


def test_this_turns_directions_ride_next_to_the_board(tmp_path):
    seen = {}

    def decide(game, power, **kw):
        seen.update(kw)
        from engine import orders_jev
        out = orders_jev.JevOrders(power=power, phase=game.get_current_phase())
        out.orders = ["A PAR - BUR"]
        return out

    (tmp_path / "state").mkdir()
    from engine import state as state_mod
    state_mod.save_game(Game(), tmp_path)
    result = staff.write_orders(tmp_path, "FRANCE", ["Take Iberia"], decide=decide)
    assert seen["extra"] == {"your_directions_this_turn": ["Take Iberia"]}
    assert result.orders == ["A PAR - BUR"]


def test_no_key_is_a_clear_refusal_not_a_crash(tmp_path, monkeypatch):
    from engine import state as state_mod
    state_mod.save_game(Game(), tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setattr("engine.jev.resolve_api_key", lambda root=None: None)
    result = staff.write_orders(tmp_path, "FRANCE", ["Take Iberia"])
    assert not result.ok and "no order writer available" in result.error


# --------------------------------------------------------------------------- #
# Routing is decided in code, never by the model
# --------------------------------------------------------------------------- #
def test_seat_spec_carries_the_routing():
    spec = MatchSpec.load(None, orders="staff", seats={"FRANCE": {"orders": "self"}})
    assert spec.staff_powers() == [p for p in spec.live_powers() if p != "FRANCE"]
    assert spec.seats["FRANCE"].orders == "self"


def test_bad_routing_is_rejected_at_load():
    with pytest.raises(ValueError, match="self|staff"):
        MatchSpec.load(None, seats={"FRANCE": {"orders": "whatever"}})


def test_the_fake_backend_refuses_a_staff_seat(tmp_path):
    """No stand-in: faking the staff would report a pipeline never run."""
    from orchestration.player_agent import FakeAgent
    from orchestration.match_spec import SeatSpec

    spec = MatchSpec.load(None)
    agent = FakeAgent("FRANCE", SeatSpec(orders="staff"), REPO, tmp_path, spec)
    result = agent.dispatch("<task>", kind="directives")
    assert not result.ok and "staff" in result.error
