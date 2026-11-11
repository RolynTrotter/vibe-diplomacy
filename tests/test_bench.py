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
