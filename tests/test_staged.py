"""Staged order writing: movement decided before anything else.

The batch path froze a whole game — supports outnumbered moves as options,
mutual support is a stable fixed point, and by 1902 nothing moved again. This
path settles who moves first and only offers supports to units that already
lost that decision. These tests pin the structure and the two failure classes
that are removed in code rather than asked away.
"""
import pytest
from diplomacy import Game

from engine import staged, validate


class _Answer:
    def __init__(self, choice, probabilities=None, confidence=None):
        self.choice = choice
        self.probabilities = probabilities or {choice: 1.0}
        self.confidence = confidence


class _Usage:
    input_tokens = 100
    output_tokens = 0


class _Response:
    def __init__(self, answers):
        self.answers = answers
        self.usage = _Usage()


def test_groups_never_exceed_the_subset_cap():
    assert [len(g) for g in staged._groups(list(range(13)))] == [6, 6, 1]
    assert staged._groups([]) == []
    assert 2 ** staged.GROUP_CAP <= 255, "every subset must fit in one Choice"


def test_every_subset_is_offered_including_none():
    opts = staged._subset_options(
        ["MOS", "WAR", "SEV"], {"MOS": "Moscow", "WAR": "Warsaw", "SEV": "Sevastopol"},
        {"MOS": "A MOS", "WAR": "A WAR", "SEV": "F SEV"})
    assert len(opts) == 2 ** 3
    assert staged.NONE_KEY in opts, "sitting still is a real decision at a stalemate"
    assert "A MOS out of Moscow advances" in opts["MOS"], "singular reads correctly"
    assert "advance." in opts["MOS,WAR"], "plural reads correctly"


def test_marginals_are_diagnostic_only_and_would_mislead():
    """The commonest board decision is exclusive: one attacks, one supports.

    Marginalising that pairing throws away the exclusivity, which is why
    nothing in the pipeline reads these numbers.
    """
    probs = {"MOS": 0.48, "WAR": 0.47, staged.NONE_KEY: 0.05}
    m = staged._marginals(["MOS", "WAR"], probs)
    assert m["MOS"] == pytest.approx(0.48) and m["WAR"] == pytest.approx(0.47)
    # Threshold above and neither moves; below and both move into a bounce.
    assert not any(v > 0.5 for v in m.values())
    assert max(probs, key=probs.get) == "MOS", "the combination is the answer"


def test_two_units_never_take_the_same_province():
    """Destination questions run in one request and cannot see each other."""
    game = Game()
    stages = []

    def ask(state, questions):
        return _Response({
            "EDI": _Answer("F EDI - NTH", {"F EDI - NTH": 0.7, "F EDI - NWG": 0.3},
                           confidence=0.9),
            "LON": _Answer("F LON - NTH", {"F LON - NTH": 0.6, "F LON - ENG": 0.4},
                           confidence=0.5)})

    orders, demoted = staged._destinations(
        game, "ENGLAND", ["EDI", "LON"], {"committed_orders": []}, "fleet", None,
        ask=ask, stages=stages)
    assert sorted(orders) == ["F EDI - NTH", "F LON - ENG"]
    assert demoted == [], "a second choice existed, so nobody was demoted"


def test_a_unit_with_no_free_destination_is_demoted_to_supporting():
    game = Game()
    stages = []

    def ask(state, questions):
        return _Response({
            "EDI": _Answer("F EDI - NTH", {"F EDI - NTH": 1.0}, confidence=0.9),
            "LON": _Answer("F LON - NTH", {"F LON - NTH": 1.0}, confidence=0.4)})

    orders, demoted = staged._destinations(
        game, "ENGLAND", ["EDI", "LON"], {"committed_orders": []}, "fleet", None,
        ask=ask, stages=stages)
    assert orders == ["F EDI - NTH"] and demoted == ["LON"]


def test_supports_that_cannot_work_are_never_offered():
    """A hold-support for our own unit that is leaving is a wasted turn."""
    game = Game()
    captured = {}

    def ask(state, questions):
        captured.update(questions)
        return _Response({loc: _Answer(next(iter(q.criteria)))
                          for loc, q in questions.items()})

    staged._helpers(game, "TURKEY", ["SMY"],
                    {"committed_orders": ["A CON - BUL"]}, None,
                    ask=ask, stages=[])
    offered = set(captured["SMY"].criteria)
    assert "A SMY S A CON" not in offered, "CON is moving; hold-support is void"
    # Smyrna does not border Bulgaria, so it cannot support that move either;
    # what is left is everything still capable of doing something.
    assert offered and all("S A CON" not in o for o in offered)


def test_foreign_units_stay_on_offer():
    """We cannot see another power's orders, so backing one is a live gamble."""
    game = Game()
    captured = {}

    def ask(state, questions):
        captured.update(questions)
        return _Response({loc: _Answer(next(iter(q.criteria)))
                          for loc, q in questions.items()})

    staged._helpers(game, "FRANCE", ["PAR"], {"committed_orders": []}, None,
                    ask=ask, stages=[])
    assert any("MUN" in o for o in captured["PAR"].criteria), \
        "Germany's Munich is not ours to rule out"


def test_non_movement_phases_fall_through_to_the_single_pass():
    game = Game()
    game.set_orders("TURKEY", ["A CON - BUL", "F ANK - BLA", "A SMY - ARM"])
    game.process(); game.process()
    assert game.phase_type == "A"
    calls = []

    def ask(state, questions):
        calls.append(questions)
        return _Response({loc: _Answer(next(iter(q.criteria)))
                          for loc, q in questions.items()})

    result = staged.choose_orders_staged(game, "TURKEY", ask=ask)
    assert len(calls) == 1, "builds are one decision per centre, not a staged split"
    assert all(o.endswith(" B") or o == "WAIVE" for o in result.orders + ["WAIVE"])


def test_armies_are_asked_before_fleets():
    game = Game()
    seen = []

    def ask(state, questions):
        key = next(iter(questions))
        seen.append(key)
        if key.startswith(("armies", "fleets")):
            return _Response({key: _Answer(staged.NONE_KEY,
                                           {staged.NONE_KEY: 1.0}, confidence=0.9)})
        return _Response({loc: _Answer(next(iter(q.criteria)))
                          for loc, q in questions.items()})

    staged.choose_orders_staged(game, "ENGLAND", ask=ask)
    assert seen[0].startswith("armies")
    assert any(s.startswith("fleets") for s in seen)
    assert seen.index("armies_group_0") < seen.index("fleets_group_0")
