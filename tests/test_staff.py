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
from orchestration.player_agent import parse_reply

REPO = Path(__file__).resolve().parent.parent

REPLY = """TO ENGLAND: Channel DMZ? I will keep my fleets south.
TO ALL: I want no quarrel in the west this year.
TO STAFF: Take Iberia this year, Portugal before Spain
TO STAFF: Munich matters more than Belgium
TO STAFF: A PAR - BUR
TO STAFF: Do not let Italy into Marseilles
TO SELF: DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end 1903
FINAL_MESSAGES
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
                   "engine syntax", "a par - bur", "read_messages",
                   "game_status"):
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
    parsed = parse_reply(REPLY)
    assert "Take Iberia this year, Portugal before Spain" in parsed.directions
    assert not any(d.startswith("A PAR") for d in parsed.directions), (
        "a seat doing its staff's job must not slip an order into the notes")
    assert parsed.notes == [
        "DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end 1903"]
    assert [r for r, _ in parsed.flat_mail] == ["ENGLAND", "ALL"]
    assert parsed.final, "the seat said it was done talking"


def test_one_line_can_address_several_powers():
    """`send_message --to` is variadic, so this stays a single send."""
    parsed = parse_reply("TO ENGLAND, GERMANY: Burgundy stays empty?")
    assert parsed.mail == [(["ENGLAND", "GERMANY"], "Burgundy stays empty?")]
    assert parsed.flat_mail == [("ENGLAND", "Burgundy stays empty?"),
                                ("GERMANY", "Burgundy stays empty?")]


def test_private_targets_never_share_a_line_with_a_power():
    """Mailing a rival your private notes is the worst failure available."""
    parsed = parse_reply("TO SELF, ENGLAND: my real plan is to take Belgium")
    assert parsed.mail == [] and parsed.notes == []
    assert "must be on a line of its own" in parsed.errors[0]


def test_notes_do_not_eat_the_diplomatic_budget():
    reply = "\n".join([f"TO ENGLAND: msg {i}" for i in range(6)]
                      + [f"TO SELF: note {i}" for i in range(6)])
    parsed = parse_reply(reply)
    assert len(parsed.mail) == 4, "mail stays capped"
    assert len(parsed.notes) == 6, "notes are budgeted separately"


def test_an_unknown_recipient_is_reported_not_guessed():
    parsed = parse_reply("TO FRACNE: hello")
    assert parsed.mail == [] and "FRACNE" in parsed.errors[0]


# --------------------------------------------------------------------------- #
# The handoff
# --------------------------------------------------------------------------- #
def test_directions_are_persisted_where_the_order_writer_reads_them(tmp_path):
    from engine import press

    staff.save_notes(tmp_path, "FRANCE", parse_reply(REPLY).notes
                     + parse_reply(REPLY).directions)
    st = press.diplomatic_state(tmp_path, Game(), "FRANCE")
    assert "Take Iberia" in st["your_own_plan"]
    assert st["your_standing_deals"] == [
        "ENGLAND — Channel DMZ, no fleets in ENG — until end 1903"]


def test_directions_overwrite_rather_than_accumulate(tmp_path):
    """A notebook that only grows hits the cap and drops the newest lines."""
    staff.save_notes(tmp_path, "FRANCE", ["Take Iberia"])
    staff.save_notes(tmp_path, "FRANCE", ["Turn on Germany"])
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

    from engine import state as state_mod
    state_mod.save_game(Game(), tmp_path)
    result = staff.write_orders(tmp_path, "FRANCE", ["Take Iberia"], decide=decide)
    assert seen["extra"]["your_directions_this_turn"] == ["Take Iberia"]
    assert result.orders == ["A PAR - BUR"]


def test_directions_also_reach_the_field_valuation_reads(tmp_path):
    """Valuation is where intent becomes a number; it reads `your_own_plan`.

    A direction that lands only in its own field is prose competing with
    `Priority N/100` — measured 0/3 on taking Burgundy when it missed the
    valuation request, 3/3 when it reached it.
    """
    staff.save_notes(tmp_path, "FRANCE", ["Germany is the threat by 1903"])
    extra = staff._directions_state(tmp_path, "FRANCE",
                                    ["Burgundy before Germany gets there"])
    assert extra["your_directions_this_turn"] == [
        "Burgundy before Germany gets there"]
    assert "Burgundy before Germany" in extra["your_own_plan"]
    assert "Germany is the threat by 1903" in extra["your_own_plan"], (
        "the durable notebook is still there underneath")


def test_directions_are_never_written_to_disk(tmp_path):
    """Last phase's intent must not quietly become standing policy."""
    staff.save_notes(tmp_path, "FRANCE", ["Germany is the threat by 1903"])
    staff._directions_state(tmp_path, "FRANCE", ["Burgundy this turn"])
    assert "Burgundy" not in (tmp_path / "notes" / "FRANCE.md").read_text()


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


# --------------------------------------------------------------------------- #
# Nothing to fetch: the seat is handed everything it needs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["negotiation", "directives", "combined"])
def test_an_agentic_task_never_sends_the_seat_looking(kind):
    """Every fact is already in the prompt, so nothing may suggest re-fetching.

    A pointer at a command is a round trip, and a round trip re-sends the whole
    context to learn what the context already said.
    """
    task = tasks.build("FRANCE", kind, "S1901M", "<brief>",
                       press="full", style="agentic").lower()
    for banned in ("game_status", "check-board-state", "scripts/turn.sh",
                   "use the `negotiate` skill", "use the `consult-notes` skill"):
        assert banned not in task, f"task invites a re-fetch: {banned!r}"


def test_agentic_tasks_carry_the_skill_text_itself():
    task = tasks.build("FRANCE", "negotiation", "S1901M", "<brief>",
                       press="full", style="agentic")
    assert "Full-press games only" in task, "the negotiate body is pasted in"
    assert "nothing to go and read" in task


def test_reply_style_stays_lean():
    """A tool-less seat cannot run a command, so it gets no command text."""
    task = tasks.build("FRANCE", "negotiation", "S1901M", "<brief>", press="full")
    assert "Full-press games only" not in task
    assert "TO SELF" in task, "but it does get the one syntax it writes in"


def test_gunboat_never_gets_the_negotiate_body():
    task = tasks.build("FRANCE", "orders", "S1901M", "<brief>",
                       press="none", style="agentic")
    assert "Full-press games only" not in task


# --------------------------------------------------------------------------- #
# The board picture costs half a megabyte; spend it only where it pays
# --------------------------------------------------------------------------- #
def _brief_at(tmp_path, monkeypatch, processes: int, grab: bool = False):
    """The brief `processes` phases in, with a stub picture.

    `grab` takes Spain in 1901 — a centre has to actually change hands or the
    engine skips the adjustment phase entirely and there is nothing to test.
    """
    from engine import context, state as state_mod

    game = Game()
    if grab:
        game.set_orders("FRANCE", ["A MAR - SPA"])
    for _ in range(processes):
        game.process()
    state_mod.save_game(game, tmp_path)
    (tmp_path / "game").mkdir(exist_ok=True)
    (tmp_path / "game" / "config.json").write_text(
        json.dumps({"name": "t", "press": "none"}), encoding="utf-8")
    monkeypatch.setattr(context, "_board_picture", lambda *a, **k: "PICTURE-HERE")
    return context.power_brief(tmp_path, "FRANCE"), game.phase_type


def test_the_map_is_drawn_for_movement(tmp_path, monkeypatch):
    brief, phase_type = _brief_at(tmp_path, monkeypatch, 0)
    assert phase_type == "M"
    assert "PICTURE-HERE" in brief


def test_the_map_is_skipped_on_adjustments(tmp_path, monkeypatch):
    """A build is one decision over a handful of options; 537 KB buys nothing."""
    brief, phase_type = _brief_at(tmp_path, monkeypatch, 2, grab=True)
    assert phase_type == "A", "taking Spain in 1901 produces a build phase"
    assert "PICTURE-HERE" not in brief
    assert "Board topology" in brief, "the geometry is still there, in text"


# --------------------------------------------------------------------------- #
# Staff is opt-in. By default a seat writes its own orders.
# --------------------------------------------------------------------------- #
def test_a_match_has_no_staff_unless_asked():
    assert MatchSpec.load(None).staff_powers() == []
    assert len(MatchSpec.load(None, orders="staff").staff_powers()) == 7


def test_the_staff_flag_is_off_by_default():
    from orchestration.run_match import build_parser

    assert build_parser().parse_args([]).orders is None, "unset leaves the YAML"
    assert build_parser().parse_args(["--staff"]).orders == "staff"


@pytest.mark.parametrize("kind", ["orders", "combined", "negotiation"])
def test_a_self_ordering_seat_is_never_told_it_has_a_staff(kind):
    """Being offered a subordinate that does not exist wastes a whole turn."""
    task = tasks.build("FRANCE", kind, "S1901M", "<brief>", press="full")
    assert "staff" not in task.lower()
    assert "TO STAFF" not in task


def test_the_orders_block_shows_every_form():
    from orchestration.player_agent import ORDERS_BLOCK

    for example in ("A PAR - BUR", "A PAR H", "A MAR S A PAR - BUR",
                    "F BRE S A PAR", "F ENG C A LON - BRE", "A LON - BRE VIA",
                    "A BUR R MAR", "A BUR D", "A PAR B"):
        assert example in ORDERS_BLOCK, f"{example} has no example"


def test_orders_parse_fenced_or_bare():
    """The engine's syntax is not negotiable; the wrapper is not worth a turn."""
    from orchestration.player_agent import extract_orders

    body = "A PAR - BUR\nA MAR - SPA\nF BRE S A PAR - BUR"
    want = ["A PAR - BUR", "A MAR - SPA", "F BRE S A PAR - BUR"]
    assert extract_orders(f"Here they are:\n```\n{body}\n```") == want
    assert extract_orders(f"Here they are:\n\n{body}\n") == want


def test_a_self_seat_can_mail_note_and_order_in_one_reply():
    from orchestration.player_agent import extract_orders

    reply = ("TO ENGLAND: Channel DMZ?\n"
             "TO SELF: DEAL: ENGLAND — Channel DMZ until 1903\n\n"
             "A PAR - BUR\nA MAR - SPA\n")
    parsed = parse_reply(reply)
    assert parsed.flat_mail == [("ENGLAND", "Channel DMZ?")]
    assert parsed.notes == ["DEAL: ENGLAND — Channel DMZ until 1903"]
    assert parsed.directions == [], "no staff, so nothing is directed at one"
    assert extract_orders(reply) == ["A PAR - BUR", "A MAR - SPA"]
