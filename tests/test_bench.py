"""The gunboat bench counts what it says it counts."""
import pytest

from bench.gunboat import score
from vibe import game as gamemod
from vibe.game import Match


@pytest.fixture
def games(tmp_path, monkeypatch):
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    return tmp_path


def play(m, **orders):
    for power, os in orders.items():
        assert m.submit(power, os).ok
    m.advance(force=True)


def test_self_bounces_and_void_supports(games):
    m = Match.create("sb")
    play(m, FRANCE=["A PAR - BUR", "A MAR - BUR"], GERMANY=["A MUN S A BER - KIE"])
    s = score(m)
    assert s["FRANCE"]["selfbounce"] == 1 and s["FRANCE"]["void"] == 0
    assert s["GERMANY"]["void"] == 1 and s["GERMANY"]["selfbounce"] == 0


def test_an_uncontested_empty_centre_left_alone_is_missed(games):
    m = Match.create("mi")
    play(m)                                   # spring: everyone holds
    play(m)                                   # fall: France leaves Spain alone
    s = score(m)
    assert s["FRANCE"]["missed"] >= 1 and s["FRANCE"]["falls"] == 1
    m2 = Match.create("mi2")
    play(m2)
    play(m2, FRANCE=["A MAR - SPA"])
    assert score(m2)["FRANCE"]["missed"] == s["FRANCE"]["missed"] - 1
    assert score(m2)["FRANCE"]["gain"] == 1


def test_a_chain_behind_a_failed_attack_is_not_a_self_bounce(games):
    m = Match.create("ch")
    play(m, GERMANY=["A MUN H"], FRANCE=["A MAR - BUR"])
    # A BUR attacks MUN and fails; A PAR, moving in behind it, bounces too.
    play(m, GERMANY=["A MUN H"], FRANCE=["A BUR - MUN", "A PAR - BUR"])
    assert score(m)["FRANCE"]["selfbounce"] == 0


def test_held_comes_from_the_resolved_orders(games):
    m = Match.create("hd")
    play(m, FRANCE=["A PAR - BUR"])
    s = score(m)
    assert s["FRANCE"]["held"] == 0 and s["GERMANY"]["held"] == 1


def test_unused_builds_and_a_cutoff_year(games):
    m = Match.create("ub", max_year=1903)
    play(m, FRANCE=["A MAR - SPA"])
    play(m, FRANCE=["A SPA H"])
    assert m.phase() == "W1901A"
    play(m)                                   # France had a build and waived it
    play(m); play(m); play(m)                 # 1902: nothing changes
    s = score(m)
    assert s["FRANCE"]["unbuilt"] == 2 and s["FRANCE"]["winters"] == 2   # 1901 and 1902
    assert s["GERMANY"]["winters"] == 0
    early = score(m, until=1901)
    assert early["FRANCE"]["unbuilt"] == 1 and early["FRANCE"]["gain"] == 1
    assert early["FRANCE"]["moves"] == 2


def test_no_unbuilt_when_there_is_no_room(games):
    # Germany takes Marseilles while France takes Spain: centres even, nothing to build.
    m = Match.create("nr", max_year=1901)
    play(m, FRANCE=["A MAR - SPA"], GERMANY=["A MUN - BUR"])
    play(m, FRANCE=["A SPA H"], GERMANY=["A BUR - MAR"])
    play(m)
    assert score(m)["FRANCE"]["unbuilt"] == 0
    # One build is owed only for an open home centre.
    m2 = Match.create("nr2", max_year=1901)
    play(m2, FRANCE=["A MAR - SPA", "A PAR - GAS"])
    play(m2, FRANCE=["A SPA H", "A GAS - MAR"])        # BRE, MAR occupied; PAR open
    play(m2)
    assert score(m2)["FRANCE"]["unbuilt"] == 1         # Paris was open: one build owed
