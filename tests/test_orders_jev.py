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
    assert all(text and text[0].isupper() and text.endswith(".")
               for text in criteria.values())
    assert "Burgundy" in criteria["A PAR - BUR"], "codes are expanded to real names"


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
