"""The match store, adjudication fidelity, and the phase clock."""
import json
import time

import pytest

from vibe import game as gamemod
from vibe.game import POWERS, Match, MatchError, check_orders, normalize


@pytest.fixture
def match(tmp_path):
    return Match.create("t", root=tmp_path)


def submit_all(match, orders=None):
    orders = orders or {}
    game = match.load()
    for p in match.owing(game):
        assert match.submit(p, orders.get(p, []), ready=True).ok


# -- engine fidelity -------------------------------------------------------- #
def test_normalize():
    assert normalize("a par-bur") == normalize("A PAR  -  BUR") == "A PAR - BUR"


def test_check_orders_accepts_and_explains(match):
    game = match.load()
    ok = check_orders(game, "FRANCE", ["a par-bur", "F BRE H"])
    assert ok.ok and ok.accepted == ["A PAR - BUR", "F BRE H"]
    bad = check_orders(game, "FRANCE", ["F BRE - LON", "A MUN - BUR"])
    assert "Legal orders for BRE" in bad.errors[0]
    assert "nothing to order at MUN" in bad.errors[1]


def test_bounce(match):
    submit_all(match, {"FRANCE": ["A PAR - BUR"], "GERMANY": ["A MUN - BUR"]})
    game = match.load()
    assert game.get_current_phase() == "F1901M"
    assert "A PAR" in game.powers["FRANCE"].units
    assert "A MUN" in game.powers["GERMANY"].units
    hist = match.history("S1901M")
    assert "bounce" in hist["results"]["A PAR"]


def test_supported_attack_dislodges(match):
    submit_all(match, {"FRANCE": ["A PAR - BUR"]})                    # S1901
    submit_all(match, {"FRANCE": ["A BUR - MUN", "A MAR - BUR"]})     # F1901: bounce off MUN? no — MUN holds
    game = match.load()
    assert "A BUR" in game.powers["FRANCE"].units or "A MUN" in game.powers["FRANCE"].units


def test_a_year_runs_through_builds(match):
    submit_all(match, {"FRANCE": ["A MAR - SPA"]})
    submit_all(match, {"FRANCE": ["A SPA H"]})
    game = match.load()
    assert game.get_current_phase() == "W1901A"
    assert match.owing(game) == ["FRANCE"] or "FRANCE" in match.owing(game)
    assert match.submit("FRANCE", ["A MAR B"], ready=True).ok
    game = match.load()
    assert game.get_current_phase().startswith("S1902")
    assert "A MAR" in game.powers["FRANCE"].units


# -- the phase clock -------------------------------------------------------- #
def test_resolves_only_when_everyone_is_ready(match):
    for p in POWERS:
        match.submit(p, [])                      # orders in, talks can go on
    assert match.phase() == "S1901M"
    for p in POWERS[:-1]:
        assert match.set_ready(p)
    assert match.phase() == "S1901M"
    match.set_ready("FRANCE", False)             # un-ready until adjudication
    match.set_ready("TURKEY")
    assert match.phase() == "S1901M" and "FRANCE" not in match.readied()
    match.submit("FRANCE", ["A PAR - BUR"], ready=True)
    assert match.phase() == "F1901M"
    assert match.history("S1901M")["orders"]["FRANCE"] == ["A PAR - BUR"]
    assert match.readied() == []                 # a new phase starts with nobody ready
    assert not match.set_ready("FRANCE", phase="S1901M")   # too late for that one


def test_ready_without_orders_holds_and_the_deadline_still_resolves(match):
    for p in POWERS:
        match.set_ready(p)
    assert match.phase() == "F1901M" and match.history("S1901M")["missing"] == list(POWERS)
    match._set_config(deadline_s=1, phase_started=0)
    match.submit("FRANCE", ["A PAR - BUR"])      # submitted, never Ready
    assert match.phase() == "S1902M" or match.phase().startswith("W")
    assert match.history("F1901M")["resolved"] == "deadline"


def test_resubmitting_replaces(match):
    match.submit("FRANCE", ["A PAR - BUR"])
    match.submit("FRANCE", ["A PAR - PIC"])
    pending = json.loads((match.path / "pending" / "FRANCE.json").read_text())
    assert pending["orders"] == ["A PAR - PIC"]


def test_illegal_set_is_rejected_whole_unless_partial(match):
    r = match.submit("FRANCE", ["A PAR - BUR", "F BRE - LON"])
    assert not r.ok and "FRANCE" not in match.submitted()
    r = match.submit("FRANCE", ["A PAR - BUR", "F BRE - LON"], partial=True)
    assert r.accepted == ["A PAR - BUR"] and "FRANCE" in match.submitted()


def test_deadline_holds_missing_powers(tmp_path):
    m = Match.create("d", root=tmp_path, deadline_s=1)
    m.submit("FRANCE", ["A PAR - BUR"])
    assert m.advance() is None
    m._set_config(phase_started=time.time() - 5)
    summary = m.advance()
    assert summary["phase"] == "S1901M"
    assert "GERMANY" in summary["missing"] and "FRANCE" not in summary["missing"]
    assert "A BUR" in m.load().powers["FRANCE"].units


def test_force_advance(match):
    assert match.advance() is None
    assert match.advance(force=True)["phase"] == "S1901M"


def test_year_cap_ends_the_game(tmp_path):
    m = Match.create("y", root=tmp_path, max_year=1901)
    while not m.ended():
        m.advance(force=True)
    assert m.ended() == "year cap 1901"
    with pytest.raises(MatchError):
        m.submit("FRANCE", [])


def test_tokens_find_their_seat(tmp_path):
    m = Match.create("k", root=tmp_path)
    token = m.config["seats"]["ITALY"]
    found, power = Match.by_token(token, root=tmp_path)
    assert power == "ITALY" and found.path == m.path
    assert len(set(m.config["seats"].values())) == 7
    with pytest.raises(MatchError):
        Match.by_token("nope", root=tmp_path)


# -- press ------------------------------------------------------------------ #
def test_gunboat_has_no_mail(match):
    with pytest.raises(MatchError):
        match.send("FRANCE", ["ENGLAND"], "hi")


def test_inbox_is_private(tmp_path):
    m = Match.create("p", root=tmp_path, press="full")
    m.send("FRANCE", ["ENGLAND"], "channel DMZ?")
    m.send("GERMANY", ["ALL"], "peace in our time")
    assert [x["body"] for x in m.inbox("ENGLAND")] == ["channel DMZ?", "peace in our time"]
    assert [x["body"] for x in m.inbox("ITALY")] == ["peace in our time"]
    assert [x["body"] for x in m.inbox("FRANCE")] == ["channel DMZ?", "peace in our time"]
    with pytest.raises(MatchError):
        m.send("FRANCE", ["SPAIN"], "?")


def test_orders_for_a_resolved_phase_are_refused_not_carried_over(match):
    match.advance(force=True)                       # S1901M resolves without ENGLAND
    with pytest.raises(gamemod.LateOrders, match="S1901M has already resolved"):
        match.submit("ENGLAND", ["F LON - NTH"], phase="S1901M")
    assert "ENGLAND" not in match.submitted()       # nothing landed in F1901M


def test_deadline_waits_while_the_runner_has_calls_in_flight(tmp_path):
    import os
    m = Match.create("busy", root=tmp_path, deadline_s=1)
    m._set_config(phase_started=time.time() - 5)
    (m.path / "busy").write_text(str(os.getpid()))
    assert m.advance() is None                      # still waiting on our own calls
    (m.path / "busy").write_text("999999")          # a runner that has died
    assert m.advance()["resolved"] == "deadline"


def test_history_says_how_a_phase_resolved(match):
    submit_all(match)
    assert match.history("S1901M")["resolved"] == "everyone ready"
    assert match.advance(force=True)["resolved"] == "forced"


def test_one_order_per_unit_and_a_pasted_list_holds(match):
    game = match.load()
    pasted = ["A PAR - BUR", "A PAR - PIC", "A PAR - GAS", "A PAR H", "F BRE - MAO"]
    checked = check_orders(game, "FRANCE", pasted)
    assert checked.accepted == ["F BRE - MAO"]             # PAR is not guessed at
    assert "4 different orders for PAR" in checked.errors[0] and "holds" in checked.errors[0]
    same = check_orders(game, "FRANCE", ["A PAR - BUR", "a par-bur"])
    assert same.ok and same.accepted == ["A PAR - BUR"]   # a repeat is not a conflict
    r = match.submit("FRANCE", pasted, partial=True)
    pending = json.loads((match.path / "pending" / "FRANCE.json").read_text())
    assert pending["orders"] == ["F BRE - MAO"]


def test_two_builds_for_one_centre_take_the_last(match):
    submit_all(match, {"FRANCE": ["A MAR - SPA"]})
    submit_all(match, {"FRANCE": ["A SPA H"]})
    checked = check_orders(match.load(), "FRANCE", ["A MAR B", "F MAR B"])
    assert checked.ok and checked.accepted == ["F MAR B"]
