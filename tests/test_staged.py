"""Staged order writing: movement decided before anything else.

The batch path froze a whole game — supports outnumbered moves as options,
mutual support is a stable fixed point, and by 1902 nothing moved again. This
path settles who moves first and only offers supports to units that already
lost that decision. These tests pin the structure and the two failure classes
that are removed in code rather than asked away.
"""
import pytest
from diplomacy import Game

from engine import coherence, staged, validate


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
        ["MOS", "WAR", "SEV"], {"MOS": "A MOS", "WAR": "A WAR", "SEV": "F SEV"})
    assert len(opts) == 2 ** 3
    assert staged.NONE_KEY in opts, "sitting still is a real decision at a stalemate"
    assert opts["MOS"] == ("A MOS moves. A WAR and F SEV stay, and can support, "
                           "convoy or hold instead.")
    assert opts["MOS,WAR"].startswith("A MOS and A WAR move.")
    assert opts["MOS,WAR,SEV"] == "A MOS, A WAR and F SEV move.", (
        "nothing stays behind, so nothing is said about what stays behind")


def test_no_question_says_advance():
    """The rules say move. `advance` is a word we invented for the model."""
    opts = staged._subset_options(["MOS", "WAR"], {"MOS": "A MOS", "WAR": "A WAR"})
    assert not any("advanc" in v.lower() for v in opts.values())


def test_a_unit_is_named_once():
    """`F BRE out of Brest` said Brest twice; the token already locates it."""
    text = staged._subset_options(["BRE"], {"BRE": "F BRE"})["BRE"]
    assert text == "F BRE moves."


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


# --- the match runner persists like a real match ---------------------------

def test_runner_saves_board_and_history_each_phase(tmp_path, monkeypatch):
    """The first runs played in memory and exited, so both boards had to be
    reconstructed by replaying a log. Phases now persist as the adjudicator
    writes them."""
    from engine import crypto, state as st
    from orchestration import jev_match

    game = st.new_game("persist-test")
    st.save_game(game, tmp_path)
    st.save_config({"name": "persist-test", "press": "none", "powers": {}}, tmp_path)
    _, pub = crypto.generate_keypair()
    st.pubkey_file(tmp_path).write_text(pub, encoding="utf-8")

    def fake_values(game, power, **kw):
        return {}

    def fake_orders(game, power, **kw):
        from engine.orders_jev import JevOrders
        legal = validate.legal_orders(game, power)
        return JevOrders(power=power, phase=game.get_current_phase(),
                         orders=[opts[0] for opts in legal.values()])

    monkeypatch.setattr(jev_match.valuation, "province_values", fake_values)
    monkeypatch.setattr(jev_match.staged, "choose_orders_staged", fake_orders)

    summary = jev_match.run(tmp_path, until=1901, log=lambda *a: None)

    assert summary["phases"] >= 2
    assert summary["history"], "each resolved phase is written to history/"
    assert "S1901M.json" in summary["history"]
    reloaded = st.load_game(tmp_path)
    assert reloaded.get_current_phase() == summary["final_phase"], \
        "the saved board is the board the run ended on"


def test_build_cap_holds_when_more_centres_than_allowed():
    from orchestration.jev_match import _capped_adjustments
    game = Game()
    game.set_orders("TURKEY", ["A CON - BUL", "F ANK - BLA", "A SMY - ARM"])
    game.process(); game.process()
    owed = len(game.powers["TURKEY"].centers) - len(game.powers["TURKEY"].units)
    capped = _capped_adjustments(game, "TURKEY", ["A CON B", "A SMY B", "F ANK B"])
    assert sum(o.endswith(" B") for o in capped) == max(owed, 0)


def test_stab_policy_is_decided_once_and_seen_by_every_later_stage(tmp_path):
    """The deal is settled before any unit is asked, then rides along.

    Left implicit in the per-unit choices the decision is never actually made:
    a deal is prose and the options are scored in centres, so the prose loses.
    """
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "FRANCE.md").write_text(
        "- DEAL: ENGLAND — Channel DMZ — until end 1903\n", encoding="utf-8")

    game = Game()
    seen, asked = [], []

    def ask(state, questions):
        seen.append(dict(state))
        asked.append(sorted(questions))
        answers = {}
        for key, question in questions.items():
            first = next(iter(question.criteria))
            answers[key] = _Answer(first, {first: 1.0}, confidence=0.7)
        return _Response(answers)

    result = staged.choose_orders_staged(game, "FRANCE", root=tmp_path,
                                         stab=True, ask=ask)
    assert asked[0] == ["deal_0"], "the deal is decided before any unit is"
    assert result.deal_policy[0]["deal"].startswith("ENGLAND")
    later = seen[1:]
    assert later and all("deal_policy_this_turn" in s for s in later), (
        "every order stage sees the verdict")
    legal = validate.legal_orders(game, "FRANCE")
    assert all(o in legal.get(coherence.parse_order(o).loc, [])
               for o in result.orders), "a stab policy cannot smuggle in an illegal order"


def test_no_deals_means_no_stab_request(tmp_path):
    game = Game()
    asked = []

    def ask(state, questions):
        asked.append(sorted(questions))
        return _Response({k: _Answer(next(iter(q.criteria)))
                          for k, q in questions.items()})

    staged.choose_orders_staged(game, "FRANCE", root=tmp_path, stab=True, ask=ask)
    assert not any(k.startswith("deal_") for keys in asked for k in keys), (
        "a gunboat game never pays for a stab question")


# --------------------------------------------------------------------------- #
# A prohibition has to take the option away
# --------------------------------------------------------------------------- #
def test_a_forbidden_province_is_never_on_a_ballot(tmp_path):
    """Describing a DMZ was ignored 3/3 in every phrasing. Removing it works."""
    game = Game()
    offered = []

    def ask(state, questions):
        answers = {}
        for key, q in questions.items():
            offered.extend(q.criteria)
            first = next(iter(q.criteria))
            answers[key] = _Answer(first, {first: 1.0}, confidence=0.7)
        return _Response(answers)

    result = staged.choose_orders_staged(game, "TURKEY", root=tmp_path,
                                         forbid={"BLA"}, ask=ask)
    assert not any("BLA" in o for o in offered), (
        "no move, support or convoy may reach a forbidden province")
    assert not any("BLA" in o for o in result.orders)


def test_forbidding_nothing_leaves_every_option_standing():
    game = Game()
    legal = validate.legal_orders(game, "TURKEY")
    assert any("BLA" in o for o in legal["ANK"]), (
        "the Black Sea is on Ankara's ballot when nothing forbids it")


def test_a_support_into_a_forbidden_province_is_dropped_too(tmp_path):
    """Escorting a rival through a DMZ is not honouring the DMZ."""
    game = Game()
    offered = []

    def ask(state, questions):
        answers = {}
        for key, q in questions.items():
            offered.extend(q.criteria)
            first = next(iter(q.criteria))
            answers[key] = _Answer(first, {first: 1.0})
        return _Response(answers)

    staged.choose_orders_staged(game, "TURKEY", root=tmp_path,
                                forbid={"BLA"}, ask=ask)
    helps = [o for o in offered if " S " in o or " C " in o]
    assert helps, "supports were offered at all"
    assert not any(o.endswith("BLA") or "- BLA" in o for o in helps)
