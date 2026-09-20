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
    assert criteria["A PAR H"].endswith("."), "prose glosses stay sentences"


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
    assert criteria["F LON - NTH"].endswith(
        "Adjacent SCs Bel, Den, Edi, Hol, Lon, Nwy (6)")
    assert criteria["F LON - ENG"].endswith("Adjacent SCs Bel, Bre, Lon (3)")
    assert criteria["F LON - WAL"].endswith("Adjacent SCs Lon, Lvp (2)")


def test_adjacent_sc_count_is_computed_not_asked():
    """Jev does not count reliably, so the tally is done here and handed over."""
    game = Game()
    for question in orders_jev.unit_questions(game, "ENGLAND").values():
        for order, text in question.criteria.items():
            if not order.startswith("F LON -") and not order.startswith("A LVP -"):
                continue
            named = text.split("Adjacent SCs ")[1]
            listed, count = named.rsplit(" (", 1)
            count = int(count.rstrip(")"))
            assert count == (0 if listed == "none" else len(listed.split(", ")))


def test_a_province_bordering_no_supply_centre_says_so():
    """A consistent field beats an absent one when the model is indexing on it."""
    game = Game()
    text = orders_jev.gloss(game, "F LON - NTH", orders_jev._names(game),
                            orders_jev._unit_owners(game), "ENGLAND", set())
    assert "Adjacent SCs" in text
    # London itself borders ENG, NTH, WAL and YOR — not one of them is a centre.
    assert orders_jev._adjacent_scs(game, "LON", set()) == "Adjacent SCs none (0)"


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
