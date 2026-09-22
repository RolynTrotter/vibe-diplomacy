"""The diplomatic half of Jev's state (issue #37).

A power that orders units while ignoring what it agreed to last phase is
playing a different game from everyone else. These tests pin what reaches the
model and, just as importantly, what never does: another power's files.
"""
import json

import pytest
from diplomacy import Game

from engine import orders_jev, press, staged

NOTES = """# FRANCE

Hold the west, take Iberia before 1903.

- DEAL: ENGLAND — Channel DMZ, no fleets in ENG — until end 1903
- DEAL: GERMANY — Burgundy stays empty
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "FRANCE.md").write_text(NOTES, encoding="utf-8")
    (tmp_path / "notes" / "GERMANY.md").write_text(
        "GERMANY's secret plan: stab France in 1902.\n\n"
        "- DEAL: FRANCE — Burgundy stays empty\n", encoding="utf-8")
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "config.json").write_text(
        json.dumps({"name": "t", "press": "full"}), encoding="utf-8")
    return tmp_path


def test_notes_and_deals_reach_the_state(root):
    st = press.diplomatic_state(root, Game(), "FRANCE")
    assert "Take Iberia" in st["your_own_plan"] or "Iberia" in st["your_own_plan"]
    assert st["your_standing_deals"] == [
        "ENGLAND — Channel DMZ, no fleets in ENG — until end 1903",
        "GERMANY — Burgundy stays empty",
    ], "each deal is its own row, not a sentence buried in the notes"


def test_a_deal_is_stated_once(root):
    """Two statements of one fact read as two facts.

    The DEAL: lines have their own scored field, so they come out of the prose
    — otherwise the duplicate competes with the field that is actually read.
    """
    st = press.diplomatic_state(root, Game(), "FRANCE")
    assert "DEAL:" not in st["your_own_plan"]
    assert "Channel DMZ" not in st["your_own_plan"]
    assert "Channel DMZ" in st["your_standing_deals"][0]


def test_never_reaches_another_power(root):
    st = press.diplomatic_state(root, Game(), "FRANCE")
    blob = json.dumps(st)
    assert "secret plan" not in blob, "GERMANY's notebook is not France's business"


def test_absent_sections_are_absent_not_empty(tmp_path):
    """An empty section reads as 'there is nothing to honour'. Omit it."""
    st = press.diplomatic_state(tmp_path, Game(), "FRANCE")
    assert "your_standing_deals" not in st
    assert "your_own_plan" not in st
    assert "your_inbox" not in st


def test_gunboat_state_is_unchanged_by_this(tmp_path):
    game = Game()
    with_root = orders_jev.build_state(game, "FRANCE", root=tmp_path)
    without = orders_jev.build_state(game, "FRANCE", root=tmp_path,
                                     include_press=False)
    assert with_root == without, "no notes, no mail — nothing is added"


def test_build_state_carries_press(root):
    st = orders_jev.build_state(Game(), "FRANCE", root=root)
    assert st["your_standing_deals"], "a real game root brings the deals along"
    assert st["you_are"] == "FRANCE"


def test_stab_questions_lead_with_keep(root):
    deals = press.standing_deals(root, "FRANCE")
    questions = press.stab_questions(deals, "FRANCE")
    assert len(questions) == 2
    first = questions["deal_0"]
    assert list(first.criteria) == [press.KEEP, press.BREAK], (
        "option order biases the answer; a stab should have to win the argument")
    assert "Channel DMZ" in first.instructions


class _Answer:
    def __init__(self, choice, probabilities=None):
        self.choice = choice
        self.probabilities = probabilities or {choice: 1.0}
        self.confidence = 0.9


class _Response:
    def __init__(self, answers):
        self.answers = answers
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 0})()


def test_stab_policy_rows_name_the_decision(root):
    deals = press.standing_deals(root, "FRANCE")

    def ask(state, questions):
        return _Response({"deal_0": _Answer(press.KEEP, {"keep": 0.8, "break": 0.2}),
                          "deal_1": _Answer(press.BREAK, {"keep": 0.3, "break": 0.7})})

    rows = press.stab_policy(deals, {"you_are": "FRANCE"}, ask=ask)
    assert [r["this_turn"] for r in rows] == ["keep", "break"]
    assert rows[0]["confidence"] == pytest.approx(0.8)
    assert "must not violate" in rows[0]["instruction"]
    assert "fair game" in rows[1]["instruction"]


def test_stab_policy_is_a_no_op_without_deals():
    called = []
    rows = press.stab_policy([], {}, ask=lambda s, q: called.append(q))
    assert rows == [] and not called, "no deals, no request, no spend"


# --------------------------------------------------------------------------- #
# The inbox, end to end through the real sealed pipeline
# --------------------------------------------------------------------------- #
def _press_game(tmp_path):
    from engine import comms, crypto, state as state_mod
    priv, pub = crypto.generate_keypair()
    pf = state_mod.pubkey_file(tmp_path)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(pub, encoding="utf-8")
    (tmp_path / "game").mkdir(exist_ok=True)
    (tmp_path / "game" / "config.json").write_text(
        json.dumps({"name": "t", "press": "full"}), encoding="utf-8")
    for p in ("FRANCE", "ENGLAND", "GERMANY"):
        comms.claim_power(tmp_path, p)
    return pub


def test_inbox_arrives_decrypted_and_only_for_the_recipient(tmp_path):
    from engine import comms
    pub = _press_game(tmp_path)
    eng = comms.load_keys(tmp_path, "ENGLAND")
    comms.send_message(tmp_path, "ENGLAND", ["FRANCE"], "Channel DMZ, agreed?",
                       "S1901M", pub, sign_priv=eng["sign"])

    st = press.diplomatic_state(tmp_path, Game(), "FRANCE")
    bodies = [m["body"] for m in st["your_inbox"]["recent_messages"]]
    assert bodies == ["Channel DMZ, agreed?"]
    assert st["your_inbox"]["recent_messages"][0]["from"] == "ENGLAND"

    # GERMANY was not a recipient and sees nothing at all.
    assert "your_inbox" not in press.diplomatic_state(tmp_path, Game(), "GERMANY")


def test_old_mail_collapses_to_a_gist_per_partner(tmp_path):
    from engine import comms
    pub = _press_game(tmp_path)
    eng = comms.load_keys(tmp_path, "ENGLAND")
    for phase in ("S1901M", "F1901M", "S1902M", "F1902M"):
        comms.send_message(tmp_path, "ENGLAND", ["FRANCE"], f"word from {phase}",
                           phase, pub, sign_priv=eng["sign"])
    inbox = press.diplomatic_state(tmp_path, Game(), "FRANCE")["your_inbox"]
    assert [m["phase"] for m in inbox["recent_messages"]] == ["S1902M", "F1902M"]
    older = inbox["earlier_by_partner"]["ENGLAND"]
    assert older["messages"] == 2 and older["span"] == "S1901M–F1901M"
    assert "word from S1901M" in older["last"][0]["gist"]


def test_gunboat_config_keeps_mail_out_of_the_state(tmp_path):
    from engine import comms
    pub = _press_game(tmp_path)
    (tmp_path / "game" / "config.json").write_text(
        json.dumps({"name": "t", "press": "none"}), encoding="utf-8")
    eng = comms.load_keys(tmp_path, "ENGLAND")
    comms.send_message(tmp_path, "ENGLAND", ["FRANCE"], "hello", "S1901M",
                       pub, sign_priv=eng["sign"])
    assert "your_inbox" not in press.diplomatic_state(tmp_path, Game(), "FRANCE")


# --------------------------------------------------------------------------- #
# Turning a written constraint into a removed option
# --------------------------------------------------------------------------- #
class _Noul:
    def __init__(self, value):
        self.noul = value


def _constraints(game, bar: dict, gift: dict):
    """Drive `province_constraints` with canned per-province probabilities."""
    from engine import valuation

    calls = []

    def ask(state, questions):
        calls.append(len(questions))
        # The bar question runs first, then the gift question.
        table = bar if len(calls) == 1 else gift
        return _Response({p: _Noul(table.get(p, 0.05)) for p in questions})

    out = valuation.province_constraints(game, "GERMANY", ask=ask)
    return out, calls


def test_six_dmzs_are_all_found():
    """The failure that killed the one-Choice version: mass split six ways.

    A pick-one primitive cannot answer a many-of-N question. One yes/no per
    reachable province can, and costs the same whether one province is
    forbidden or six.
    """
    game = Game()
    six = {"BUR": 0.71, "TYR": 0.76, "BOH": 0.78, "SIL": 0.76, "PRU": 0.78,
           "BAL": 0.75, "KIE": 0.29, "MUN": 0.29}
    (keep_out, gifts), calls = _constraints(game, six, {})
    assert keep_out == {"BUR", "TYR", "BOH", "SIL", "PRU", "BAL"}
    assert gifts == set()
    assert len(calls) == 2, "one request for the bar, one for the gift"
    assert calls[0] > 6, "every reachable province is asked about, not just six"


def test_an_agreement_to_enter_is_not_a_bar():
    """"Bounce in the Black Sea" is an agreement to move there."""
    game = Game()
    (keep_out, gifts), _ = _constraints(game, {"BLA": 0.27}, {"BLA": 0.10})
    assert keep_out == set() and gifts == set()


def test_a_province_promised_to_a_friend_is_a_gift_not_a_dmz():
    """Told "England takes Holland, not me": stay out, but escort them in."""
    game = Game()
    (keep_out, gifts), _ = _constraints(game, {"HOL": 0.22}, {"HOL": 0.95})
    assert gifts == {"HOL"}, "you stay out"
    assert keep_out == set(), "but it is not sealed — you may help them in"


def test_only_provinces_a_unit_could_reach_are_asked_about():
    """The question set is bounded by the board, not by the agreement count.

    Belgium is not adjacent to any German unit at S1901M, so it is not on the
    ballot and cannot be constrained — there is nothing to constrain.
    """
    from engine import valuation

    reach = valuation._reachable(Game(), "GERMANY")
    assert "BEL" not in reach and "HOL" in reach
    assert len(reach) < 20, "a bounded set, not all 75 provinces"


def test_a_province_cannot_be_both():
    game = Game()
    (keep_out, gifts), _ = _constraints(game, {"BUR": 0.8}, {"BUR": 0.8})
    assert keep_out == {"BUR"} and gifts == set(), "sealed wins; nobody goes in"
