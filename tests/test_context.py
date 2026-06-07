"""Conductor mode: selective context must not leak across powers."""
from orchestration import conduct

from engine import comms, context, crypto, state


def _full_press_game(tmp_path):
    game = state.new_game("conduct-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "conduct-test", "press": "full",
                       "powers": {p: {"type": "agent"} for p in
                                  ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY",
                                   "ITALY", "RUSSIA", "TURKEY"]}}, tmp_path)
    _, adj_pub = crypto.generate_keypair()
    pf = state.pubkey_file(tmp_path)
    pf.write_text(adj_pub, encoding="utf-8")
    return adj_pub


def test_brief_is_selective(tmp_path):
    adj_pub = _full_press_game(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    comms.claim_power(tmp_path, "ENGLAND")

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "FRANCE.md").write_text("FRANCE secret plan: stab ENGLAND in fall",
                                     encoding="utf-8")
    (notes / "ENGLAND.md").write_text("ENGLAND plan: trust no one", encoding="utf-8")

    fr_sign = comms.load_keys(tmp_path, "FRANCE")["sign"]
    comms.send_message(tmp_path, "FRANCE", ["ENGLAND"], "Alliance in the Channel?",
                       "S1901M", adj_pub, sign_priv=fr_sign)

    eng = context.power_brief(tmp_path, "ENGLAND")
    assert "Alliance in the Channel?" in eng        # England's inbox
    assert "ENGLAND plan: trust no one" in eng      # England's own notes
    assert "FRANCE secret plan" not in eng          # NOT France's notes

    fr = context.power_brief(tmp_path, "FRANCE")
    assert "FRANCE secret plan" in fr               # France's own notes
    assert "Alliance in the Channel?" not in fr     # France didn't receive it
    assert "ENGLAND plan: trust no one" not in fr    # NOT England's notes


def test_brief_includes_public_standings(tmp_path):
    _full_press_game(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "You are FRANCE" in brief
    assert "Supply-center standings" in brief
    # Opening counts are public knowledge.
    assert "RUSSIA: 4 centers" in brief


def test_roster_lists_who_must_play(tmp_path):
    _full_press_game(tmp_path)
    comms.claim_power(tmp_path, "FRANCE")
    r = conduct.roster(tmp_path)
    assert r["phase"] == "S1901M"
    assert r["press"] == "full"
    assert set(r["to_play"]) == {"AUSTRIA", "ENGLAND", "FRANCE", "GERMANY",
                                 "ITALY", "RUSSIA", "TURKEY"}
    assert r["powers"]["FRANCE"]["claimed"] is True
    assert r["powers"]["ENGLAND"]["claimed"] is False
