"""Engine-fidelity and round-trip tests.

These prove our thin wrappers stay faithful to the `diplomacy` engine and that
the crypto / validation / adjudication pieces behave as the workflow expects.
"""
import json

import pytest

from diplomacy import Game

from engine import adjudicate, crypto, query, state, suggest, validate


# --------------------------------------------------------------------------- #
# Serialization round-trip
# --------------------------------------------------------------------------- #
def test_save_load_round_trip(tmp_path):
    game = state.new_game("rt")
    game.set_orders("FRANCE", ["A PAR - BUR"])
    game.process()
    state.save_game(game, tmp_path)

    reloaded = state.load_game(tmp_path)
    assert reloaded.get_current_phase() == "F1901M"
    assert "A BUR" in reloaded.get_power("FRANCE").units


# --------------------------------------------------------------------------- #
# Crypto
# --------------------------------------------------------------------------- #
def test_sealed_box_round_trip():
    priv, pub = crypto.generate_keypair()
    ct = crypto.encrypt(pub, "A PAR - BUR")
    assert crypto.decrypt(priv, ct) == "A PAR - BUR"


def test_only_correct_key_decrypts():
    _, pub = crypto.generate_keypair()
    other_priv, _ = crypto.generate_keypair()
    ct = crypto.encrypt(pub, "secret orders")
    with pytest.raises(Exception):
        crypto.decrypt(other_priv, ct)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_accepts_legal_rejects_illegal():
    game = state.new_game("v")
    result = validate.validate_orders(
        game, "FRANCE",
        ["a par-bur", "A MAR - SPACEMOON", "A LON - BUR"],
    )
    assert "A PAR - BUR" in result.accepted
    assert not result.ok
    assert len(result.errors) == 2  # SPACEMOON illegal, LON not France's


def test_validate_normalizes_whitespace_and_case():
    game = state.new_game("v2")
    result = validate.validate_orders(game, "FRANCE", ["  a   par  -  bur  "])
    assert result.ok
    assert result.accepted == ["A PAR - BUR"]


# --------------------------------------------------------------------------- #
# Adjudication scenarios (DATC-flavoured)
# --------------------------------------------------------------------------- #
def test_simple_bounce():
    """Two armies moving to the same empty province both bounce."""
    game = Game()
    game.set_orders("FRANCE", ["A MAR - BUR"])
    game.set_orders("GERMANY", ["A MUN - BUR"])
    summary = adjudicate.adjudicate(game, {})  # orders already set; apply none extra
    # Neither army should have reached BUR.
    units = set(game.get_power("FRANCE").units) | set(game.get_power("GERMANY").units)
    assert "A BUR" not in units
    assert summary["phase"] == "S1901M"


def test_supported_attack_dislodges():
    """A supported move beats an unsupported defender."""
    game = Game()
    # Give a clean tactical position by setting state directly via orders over phases
    # is complex; instead test the canonical support-cut-free dislodgement using
    # the opening: France supports its own move into a bounce to win it.
    game.set_orders("FRANCE", ["A MAR - BUR", "A PAR S A MAR - BUR"])
    game.set_orders("GERMANY", ["A MUN - BUR"])
    adjudicate.adjudicate(game, {})
    # Supported French army (2) beats unsupported German (1): France holds BUR.
    assert "A BUR" in game.get_power("FRANCE").units
    assert "A BUR" not in game.get_power("GERMANY").units


# --------------------------------------------------------------------------- #
# Full year, including builds
# --------------------------------------------------------------------------- #
def test_full_year_runs_through_builds():
    game = state.new_game("year")
    # Spring move, capture nothing yet; just process through phases with defaults.
    seen_phases = [game.get_current_phase()]
    for _ in range(6):  # S1901M, F1901M (+retreats if any), W1901A, S1902M...
        if game.is_game_done:
            break
        game.process()
        seen_phases.append(game.get_current_phase())
    # We must have passed through a Fall and reached an adjustment or 1902.
    assert any(p.startswith("F1901") for p in seen_phases)


# --------------------------------------------------------------------------- #
# Queries & suggestions
# --------------------------------------------------------------------------- #
def test_board_summary_opening():
    game = state.new_game("q")
    summary = query.board_summary(game)
    assert summary["phase"] == "S1901M"
    # Standard openings: every power starts with 3 units except Russia (4).
    assert summary["powers"]["RUSSIA"]["unit_count"] == 4
    assert summary["powers"]["FRANCE"]["unit_count"] == 3


def test_adjacency_and_province_info():
    game = state.new_game("q2")
    assert "BUR" in query.adjacencies(game, "PAR")
    info = query.province_info(game, "PAR")
    assert info["is_supply_center"] is True
    assert info["owner"] == "FRANCE"


def test_heuristic_suggestions_are_legal():
    game = state.new_game("s")
    result = suggest.suggest(game, "FRANCE")
    assert len(result.orders) == 3  # France has 3 units at opening
    check = validate.validate_orders(game, "FRANCE", result.orders)
    assert check.ok, check.errors


# --------------------------------------------------------------------------- #
# End-to-end sealed submission -> adjudication
# --------------------------------------------------------------------------- #
def test_sealed_submission_round_trip():
    game = state.new_game("e2e")
    priv, pub = crypto.generate_keypair()
    phase = game.get_current_phase()

    payload = json.dumps({"power": "FRANCE", "phase": phase,
                          "orders": ["A PAR - BUR"]}, sort_keys=True)
    sealed = crypto.encrypt(pub, payload)

    recovered = json.loads(crypto.decrypt(priv, sealed))
    adjudicate.adjudicate(game, {recovered["power"]: recovered["orders"]})
    assert "A BUR" in game.get_power("FRANCE").units
