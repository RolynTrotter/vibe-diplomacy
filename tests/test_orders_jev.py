"""Jev order-writing: question construction, assembly, and the coherence report.

No network. `choose_orders` takes an injectable `ask`, so every test here drives
the assembly logic with canned answers.
"""
import json
import pathlib

import pytest
from diplomacy import Game

from engine import coherence, jev, orders_jev, validate


class _Answer:
    def __init__(self, choice, probabilities=None, confidence=None):
        self.choice = choice
        self.probabilities = probabilities or {choice: 1.0}
        self.confidence = confidence


class _Usage:
    input_tokens = 1234
    output_tokens = 56


class _Response:
    def __init__(self, answers):
        self.answers = answers
        self.usage = _Usage()


def _ask_returning(picks, *, capture=None):
    """A fake `ask` that answers each question with a fixed order."""
    def ask(state, questions):
        if capture is not None:
            capture["state"] = state
            capture["questions"] = questions
        return _Response({loc: _Answer(picks[loc], confidence=0.9)
                          for loc in questions if loc in picks})
    return ask


# --- questions -------------------------------------------------------------

def test_every_option_is_a_legal_order():
    game = Game()
    legal = validate.legal_orders(game, "FRANCE")
    for loc, question in orders_jev.unit_questions(game, "FRANCE").items():
        assert set(question.criteria) == set(legal[loc])


def test_options_are_grouped_moves_then_supports_then_hold():
    game = Game()
    criteria = orders_jev.unit_questions(game, "FRANCE")["PAR"].criteria
    kinds = [coherence.parse_order(o).kind for o in criteria]
    assert kinds[0] == "MOVE", "moves lead"
    assert kinds[-1] == "H", "hold is the last resort"
    # Supports sit between them, never before a move.
    assert kinds.index("SUP_M") > max(i for i, k in enumerate(kinds) if k == "MOVE")


def test_every_option_has_a_gloss_naming_the_board():
    game = Game()
    criteria = orders_jev.unit_questions(game, "FRANCE")["PAR"].criteria
    assert all(text and text[0].isupper() for text in criteria.values())
    assert "Burgundy" in criteria["A PAR - BUR"], "codes are expanded to real names"
    assert criteria["A PAR S F BRE"].endswith("."), "prose glosses stay sentences"
    assert criteria["A PAR H"].endswith("own"), "hold ends on its own tally"


def test_convoy_gloss_warns_that_it_needs_an_escort():
    game = Game()
    game.set_orders("ENGLAND", ["A LVP - YOR", "F LON - NTH", "F EDI - NWG"])
    game.process()
    criteria = orders_jev.unit_questions(game, "ENGLAND")["YOR"].criteria
    via = next(o for o in criteria if o.endswith("VIA"))
    assert "convoy" in criteria[via].lower()
    assert "fails" in criteria[via].lower()


# --- state -----------------------------------------------------------------

def test_state_is_json_serializable_text_only():
    """Jev accepts text only — no image path may leak into the state."""
    state = orders_jev.build_state(Game(), "FRANCE")
    encoded = json.dumps(state)          # raises if anything is not JSON
    assert ".png" not in encoded.lower()
    assert state["you_are"] == "FRANCE"
    assert state["phase"] == "S1901M"


def test_extra_state_is_merged_for_issue_37():
    state = orders_jev.build_state(Game(), "FRANCE",
                                   extra={"your_notes": "hold the Channel"})
    assert state["your_notes"] == "hold the Channel"


# --- assembly --------------------------------------------------------------

def test_choose_orders_validates_and_reports_clean_set():
    game = Game()
    picks = {"PAR": "A PAR - BUR", "MAR": "A MAR - SPA", "BRE": "F BRE - MAO"}
    result = orders_jev.choose_orders(game, "FRANCE", ask=_ask_returning(picks))
    assert sorted(result.orders) == sorted(picks.values())
    assert result.errors == []
    assert result.coherent
    assert result.confidence["PAR"] == 0.9
    assert result.usage["input_tokens"] == 1234


def test_batch_incoherence_is_reported_not_hidden():
    """The known v1 failure: an unescorted convoy. Legal, but it cannot execute."""
    game = Game()
    game.set_orders("ENGLAND", ["A LVP - YOR", "F LON - NTH", "F EDI - NWG"])
    game.process()
    legal = validate.legal_orders(game, "ENGLAND")
    via = next(o for o in legal["YOR"] if o.endswith("VIA"))
    picks = {"YOR": via}
    picks.update({loc: next(o for o in opts if o.endswith(" H"))
                  for loc, opts in legal.items() if loc != "YOR"})

    result = orders_jev.choose_orders(game, "ENGLAND", ask=_ask_returning(picks))
    assert via in result.orders, "the order is legal and is kept"
    assert result.errors == [], "the engine accepts it"
    assert not result.coherent, "but it cannot execute"
    assert any("no convoy" in i.message for i in result.issues)
    assert "no convoy" in result.report()


def test_state_and_questions_reach_the_caller_together():
    game = Game()
    capture = {}
    orders_jev.choose_orders(
        game, "FRANCE",
        ask=_ask_returning({"PAR": "A PAR H", "MAR": "A MAR H", "BRE": "F BRE H"},
                           capture=capture))
    assert set(capture["questions"]) == {"PAR", "MAR", "BRE"}, "one request, all units"
    assert capture["state"]["you_are"] == "FRANCE"


def test_no_orderable_units_makes_no_request():
    game = Game()
    called = []

    def ask(state, questions):          # pragma: no cover - must not run
        called.append(1)
        raise AssertionError("should not call Jev with nothing to order")

    game.clear_units("FRANCE")
    result = orders_jev.choose_orders(game, "FRANCE", ask=ask)
    assert result.orders == [] and not called


# --- credentials -----------------------------------------------------------

def test_api_key_read_from_secrets_local(tmp_path, monkeypatch):
    monkeypatch.delenv(jev.ENV_VAR, raising=False)
    (tmp_path / "secrets.local").write_text("# comment\nTYPESAFE_API_KEY=from-file\n")
    assert jev.resolve_api_key(tmp_path) == "from-file"


def test_process_env_beats_the_file(tmp_path, monkeypatch):
    (tmp_path / "secrets.local").write_text("TYPESAFE_API_KEY=from-file\n")
    monkeypatch.setenv(jev.ENV_VAR, "from-env")
    assert jev.resolve_api_key(tmp_path) == "from-env"


def test_available_explains_a_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv(jev.ENV_VAR, raising=False)
    # No secrets.local anywhere — including this checkout's own root, which
    # resolve_api_key falls back to for out-of-tree game directories.
    monkeypatch.setattr(jev, "_key_from_file", lambda path: None)
    ok, why = jev.available(tmp_path)
    assert not ok and "secrets.local" in why


def test_key_falls_back_to_this_checkout(tmp_path, monkeypatch):
    """A scratch game root still finds the key in the repo it was run from."""
    monkeypatch.delenv(jev.ENV_VAR, raising=False)
    repo = pathlib.Path(jev.__file__).resolve().parent.parent
    monkeypatch.setattr(jev, "_key_from_file",
                        lambda path: "repo-key" if path == repo else None)
    assert jev.resolve_api_key(tmp_path) == "repo-key"


def test_move_options_are_distinguishable_by_what_they_reach():
    """The failure this fixes: every empty destination read identically.

    F LON's moves were all '(empty)' — nothing separated the North Sea, which
    borders four unclaimed centres, from Yorkshire, which borders none.
    """
    criteria = orders_jev.unit_questions(Game(), "ENGLAND")["LON"].criteria
    # Yorkshire borders three centres, all England's own; the North Sea borders
    # six of which four are not. Counting absolutes made those read 3 against 6
    # — close. Counting what changes hands makes them 0 against 4.
    assert criteria["F LON - NTH"].endswith("next to 4 you do not own")
    assert criteria["F LON - ENG"].endswith("next to 2 you do not own")
    assert criteria["F LON - YOR"].endswith("next to 0 you do not own")


def test_gain_is_marginal_not_absolute():
    """What a province is worth is what it changes, not what exists there.

    Paris is a supply centre but worth nothing to take — France holds it.
    Gascony borders four centres, all French, so it is worth nothing either.
    Portugal is one unclaimed centre and is worth exactly that.
    """
    game = Game()
    assert orders_jev.gain_of(game, "PAR", "FRANCE")[0] == 0, "already yours"
    assert orders_jev.gain_of(game, "POR", "FRANCE")[0] == 1, "unclaimed"
    assert orders_jev.gain_of(game, "MUN", "FRANCE")[0] == 1, "a rival's counts"
    # Gascony is no centre itself; of its four neighbouring centres only Spain
    # is not France's at the opening, so it is worth 0 to take and borders 1.
    assert orders_jev.gain_of(game, "GAS", "FRANCE") == (0, 1)


def test_the_count_is_computed_here_not_asked_of_the_model():
    """Jev does not count reliably, so the arithmetic is done in code."""
    game = Game()
    for prov in ["NTH", "BUR", "POR", "LON"]:
        takes, borders = orders_jev.gain_of(game, prov, "ENGLAND")
        assert takes in (0, 1) and borders >= 0
        text = orders_jev._adjacent_scs(game, prov, set(), "ENGLAND")
        assert f"next to {borders}" in text


def test_a_province_worth_nothing_says_so_rather_than_saying_nothing():
    """A consistent field beats an absent one when the model is indexing on it."""
    game = Game()
    text = orders_jev.gloss(game, "F LON - NTH", orders_jev._names(game),
                            orders_jev._unit_owners(game), "ENGLAND", set())
    assert "new centre" in text
    # London borders ENG, NTH, WAL and YOR — not one of them is a centre.
    assert orders_jev._adjacent_scs(game, "LON", set(), "ENGLAND") == \
        "Worth no new centre to you, next to 0 you do not own"


def test_impassable_provinces_never_appear_as_reachable():
    """Switzerland sits in the raw adjacency table but cannot be entered."""
    game = Game()
    graph = orders_jev.board_graph(game)
    assert not any("SWI" in entry["adjacent"] for entry in graph.values())
    assert "SWI" not in graph


def test_cost_is_reported_per_request():
    """Only input tokens are billed, at $0.042 per million."""
    assert jev.cost_usd(1_000_000) == pytest.approx(0.042)
    result = orders_jev.choose_orders(
        Game(), "FRANCE",
        ask=_ask_returning({"PAR": "A PAR H", "MAR": "A MAR H", "BRE": "F BRE H"}))
    assert result.usage["input_tokens"] == 1234
    assert result.usage["cost_usd"] == pytest.approx(1234 / 1e6 * 0.042)
    assert "$" in result.report()


def test_spend_accumulates_across_requests():
    spend = jev.Spend()
    spend.add(_Response({}))
    spend.add(_Response({}))
    assert spend.requests == 2 and spend.input_tokens == 2468
    assert spend.usd == pytest.approx(2468 / 1e6 * 0.042)


# --- province valuation ----------------------------------------------------

def test_province_values_are_percent_of_attention():
    """Probabilities sum to 1, so each province's share is a percent directly."""
    from engine import valuation
    game = Game()
    captured = {}

    def ask(state, questions):
        captured["q"] = questions
        return _Response({"most_important": _Answer(
            "BUL", probabilities={"BUL": 0.53, "BLA": 0.16, "CON": 0.14, "CLY": 0.0})})

    values = valuation.province_values(game, "TURKEY", state={"board_graph":
        orders_jev.board_graph(game)}, ask=ask)
    assert values["BUL"] == 53.0 and values["CLY"] == 0.0
    assert sum(values.values()) == pytest.approx(83.0)
    question = captured["q"]["most_important"]
    assert len(question.criteria) == 75, "one option per province, asked once"
    assert "TURKEY" in question.instructions


def test_hold_is_scored_on_the_same_axis_as_moves():
    """Left unmeasured, hold is the only option that never has to justify itself.

    Annotating every move while leaving hold as prose measurably doubled the
    hold rate, so hold carries the same two fields.
    """
    game = Game()
    criteria = orders_jev.unit_questions(game, "ENGLAND", {"NTH": 51.0})["LON"].criteria
    for order in ("F LON - NTH", "F LON H"):
        assert "new centre" in criteria[order]
        assert "Priority" in criteria[order]
    assert criteria["F LON - NTH"].endswith("Priority 51/100")
    assert criteria["F LON H"].endswith("Priority 0/100")


def test_priorities_are_omitted_entirely_when_no_values_given():
    criteria = orders_jev.unit_questions(Game(), "ENGLAND")["LON"].criteria
    assert not any("Priority" in text for text in criteria.values())


# --- selection policy ------------------------------------------------------

def test_aggregate_beats_argmax_at_vote_splitting():
    """Hold is one option; "move somewhere" is split across every destination.

    Argmax therefore hands the win to hold on a near-tie it should lose.
    """
    probs = {"A PAR H": 0.29, "A PAR - BUR": 0.16, "A PAR - PIC": 0.14,
             "A PAR - GAS": 0.10, "A PAR S F BRE": 0.31}
    assert max(probs, key=probs.get) == "A PAR S F BRE"
    # move mass 0.40 > support 0.31 > hold 0.29
    assert orders_jev._aggregate_pick(probs) == "A PAR - BUR"


def test_aggregate_reduces_to_argmax_when_one_class():
    """Builds, disbands and retreats are all one class — no special case."""
    probs = {"A CON B": 0.6, "F CON B": 0.3, "WAIVE": 0.1}
    assert orders_jev._aggregate_pick(probs) == "A CON B"


def test_choose_orders_uses_aggregation_by_default():
    game = Game()
    probs = {"A PAR H": 0.4, "A PAR - BUR": 0.25, "A PAR - PIC": 0.24,
             "A PAR - GAS": 0.11}

    def ask(state, questions):
        return _Response({"PAR": _Answer("A PAR H", probabilities=probs)})

    aggregated = orders_jev.choose_orders(game, "FRANCE", ask=ask)
    assert aggregated.orders == ["A PAR - BUR"], "move mass 0.60 outweighs hold 0.40"
    raw = orders_jev.choose_orders(game, "FRANCE", ask=ask, select="argmax")
    assert raw.orders == ["A PAR H"]


def test_builds_are_capped_at_what_the_power_is_owed():
    """Every open home centre is offered a build; only so many are allowed."""
    from orchestration.jev_match import _capped_adjustments
    game = Game()
    game.set_orders("TURKEY", ["A CON - BUL", "F ANK - BLA", "A SMY - ARM"])
    game.process(); game.process()          # through F1901M into W1901A
    owed = len(game.powers["TURKEY"].centers) - len(game.powers["TURKEY"].units)
    greedy = ["A CON B", "A SMY B", "F ANK B"][:max(owed + 1, 1)]
    capped = _capped_adjustments(game, "TURKEY", greedy)
    assert sum(o.endswith(" B") for o in capped) <= max(owed, 0)
