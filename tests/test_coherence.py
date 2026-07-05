"""Order-set coherence: individually legal orders that are jointly wasted.

Grounded in real failures: in game/lm-studio-1, 51% of all orders were void
supports and 11% were convoys that never happened — every one legal per
validate.py. These tests pin the classifier that catches them at submit time.
"""
import subprocess
import sys
from pathlib import Path

from engine import coherence, state

REPO = Path(__file__).resolve().parent.parent


def _errors(issues):
    return [i for i in issues if i.severity == "error"]


def _warnings(issues):
    return [i for i in issues if i.severity == "warning"]


def test_coherent_set_is_clean():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "A PAR - BUR",
        "A MAR S A PAR - BUR",
        "F BRE - MAO",
    ])
    assert issues == []


def test_void_support_of_own_unordered_move_is_error():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "A PAR S A MAR - BUR",   # but MAR goes to SPA
        "A MAR - SPA",
        "F BRE - MAO",
    ])
    errs = _errors(issues)
    assert len(errs) == 1
    assert errs[0].order == "A PAR S A MAR - BUR"
    assert "void support" in errs[0].message


def test_support_hold_of_own_moving_unit_is_error():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "A PAR S A MAR",
        "A MAR - SPA",
    ])
    errs = _errors(issues)
    assert len(errs) == 1
    assert "support-hold" in errs[0].message


def test_support_of_foreign_move_is_warning_not_error():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "F BRE S F LON - ENG",   # England's unit — legitimate coordination
    ])
    assert _errors(issues) == []
    warns = _warnings(issues)
    assert len(warns) == 1
    assert "assumes ENGLAND" in warns[0].message


def test_self_bounce_is_warning():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "A PAR - GAS",
        "A MAR - GAS",
    ])
    warns = _warnings(issues)
    assert any("self-bounce" in w.message for w in warns)
    assert _errors(issues) == []


def test_move_onto_own_stationary_unit_is_warning():
    g = state.new_game("t")
    issues = coherence.check_orders(g, "FRANCE", [
        "A PAR - BRE",   # own fleet in BRE, and it holds
        "F BRE H",
    ])
    warns = _warnings(issues)
    assert any("cannot dislodge" in w.message for w in warns)


def test_convoy_of_own_army_without_matching_move_is_error():
    g = state.new_game("t")
    g.set_orders("ENGLAND", ["F LON - NTH", "A LVP - YOR"])
    g.process()  # F1901M: England now has F NTH + A YOR
    issues = coherence.check_orders(g, "ENGLAND", [
        "F NTH C A YOR - NWY",
        "A YOR - LON",           # army went its own way
    ])
    errs = _errors(issues)
    assert len(errs) == 1
    assert "void convoy" in errs[0].message


def test_via_without_own_convoy_warns_when_foreign_fleets_exist():
    g = state.new_game("t")
    g.set_orders("ENGLAND", ["F LON - NTH", "A LVP - YOR"])
    g.process()
    issues = coherence.check_orders(g, "ENGLAND", [
        "A YOR - NWY VIA",       # no own convoy ordered; F NTH idle
        "F NTH H",
    ])
    # Other powers have fleets at sea? Opening fleets are all in port, but any
    # foreign fleet in a WATER province counts. Here there are none, so this is
    # provably impossible -> error.
    assert _errors(issues) or _warnings(issues)
    tagged = _errors(issues) + _warnings(issues)
    assert any("convoy" in i.message for i in tagged)


def test_non_movement_phases_are_skipped():
    g = state.new_game("t")
    g.set_orders("FRANCE", ["A PAR - PIC"])
    g.process()   # -> F1901M
    g.set_orders("FRANCE", ["A PIC - BEL"])
    g.process()   # -> W1901A (France owes a build)
    assert g.phase_type == "A"
    assert coherence.check_orders(g, "FRANCE", ["A PAR B"]) == []


def test_submit_orders_rejects_incoherent_set(tmp_path):
    """End-to-end: the CLI refuses a provably void support unless overridden."""
    from engine import comms, crypto

    game = state.new_game("coh-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "coh-test", "press": "none", "powers": {}},
                      tmp_path)
    _, adj_pub = crypto.generate_keypair()
    state.pubkey_file(tmp_path).write_text(adj_pub, encoding="utf-8")
    comms.claim_power(tmp_path, "FRANCE")

    bad = "A PAR S A MAR - BUR\nA MAR - SPA\nF BRE - MAO"
    run = lambda extra=(): subprocess.run(
        [sys.executable, "-m", "orchestration.submit_orders",
         "--root", str(tmp_path), "--power", "FRANCE", *extra],
        cwd=REPO, input=bad, text=True, capture_output=True)

    rejected = run()
    assert rejected.returncode == 1
    assert "void support" in rejected.stderr
    assert not state.power_orders_file(tmp_path, "FRANCE", "S1901M").exists()

    overridden = run(["--no-coherence"])
    assert overridden.returncode == 0
    assert state.power_orders_file(tmp_path, "FRANCE", "S1901M").exists()
