"""The brief's tactical annex, center digest, rules crib, and notes cap."""
from engine import comms, context, crypto, state


def _game(tmp_path, press="none"):
    game = state.new_game("annex-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "annex-test", "press": press, "powers": {}},
                      tmp_path)
    _, adj_pub = crypto.generate_keypair()
    state.pubkey_file(tmp_path).write_text(adj_pub, encoding="utf-8")
    return game


def test_annex_lists_engine_verified_moves(tmp_path):
    _game(tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Tactical annex" in brief
    # Opening France: A PAR's real neighbours, annotated with occupancy.
    assert "A PAR can move to:" in brief
    assert "BRE (your F)" in brief
    # The crib that corrects misconceptions seen in real games.
    assert "vacating a center does NOT lose it" in brief


def test_annex_flags_enemy_units_adjacent_to_centers(tmp_path):
    game = _game(tmp_path)
    game.set_orders("GERMANY", ["A MUN - BUR"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Enemy units adjacent to your centers" in brief
    assert "GERMANY A BUR" in brief


def test_adjustment_annex_lists_build_options(tmp_path):
    game = _game(tmp_path)
    game.set_orders("FRANCE", ["A PAR - PIC"])
    game.process()
    game.set_orders("FRANCE", ["A PIC - BEL"])
    game.process()
    assert game.phase_type == "A"
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Build/disband options" in brief
    assert "A PAR B" in brief


def test_center_digest_shows_yearly_changes(tmp_path):
    game = _game(tmp_path)
    game.set_orders("FRANCE", ["A PAR - PIC"])
    game.process()
    game.set_orders("FRANCE", ["A PIC - BEL"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Center changes so far" in brief
    assert "FRANCE +BEL" in brief


def test_outcome_feedback_explains_void_support(tmp_path):
    game = _game(tmp_path)
    game.set_orders("FRANCE", ["A PAR S A MAR - BUR", "A MAR - SPA",
                               "F BRE - MAO"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "what happened and why" in brief
    assert "VOID — your own unit was actually ordered 'A MAR - SPA'" in brief
    assert "2 other order(s) succeeded" in brief


def test_outcome_feedback_explains_foreign_void(tmp_path):
    game = _game(tmp_path)
    game.set_orders("FRANCE", ["A PAR S A MUN - BUR"])   # Germany goes elsewhere
    game.set_orders("GERMANY", ["A MUN - RUH"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "VOID — GERMANY's unit was actually ordered 'A MUN - RUH'" in brief


def test_commitments_ledger_survives_notes_truncation(tmp_path):
    _game(tmp_path, press="full")
    notes = tmp_path / "notes"
    notes.mkdir()
    bloat = "\n".join(f"- filler {i}" for i in range(400))
    (notes / "FRANCE.md").write_text(
        "# FRANCE\n" + bloat +
        "\nDEAL: ENGLAND — Channel DMZ — until end 1903\n",
        encoding="utf-8")
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Your commitments" in brief
    assert "ENGLAND — Channel DMZ — until end 1903" in brief   # past the cap
    assert "notes truncated" in brief


def test_commitments_hint_only_in_full_press(tmp_path):
    _game(tmp_path, press="full")
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "log agreements in your notes as lines like" in brief


def test_inbox_threads_older_phases(tmp_path):
    """Older mail collapses to a per-partner thread that keeps the substance.

    A bare count told a power a relationship existed but not what was agreed
    in it, so a deal struck three phases back went invisible.
    """
    _game(tmp_path, press="full")
    pub = state.pubkey_file(tmp_path).read_text(encoding="utf-8")
    comms.claim_power(tmp_path, "FRANCE")
    comms.claim_power(tmp_path, "ENGLAND")
    sign = comms.load_keys(tmp_path, "ENGLAND")["sign"]
    for phase, body in [("S1901M", "ancient history"),
                        ("F1901M", "Belgium is yours if Burgundy is mine"),
                        ("S1902M", "recent one"),
                        ("F1902M", "current one")]:
        comms.send_message(tmp_path, "ENGLAND", ["FRANCE"], body, phase, pub,
                           sign_priv=sign)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "recent one" in brief and "current one" in brief    # last two, raw
    assert "**ENGLAND** ×2 (S1901M–F1901M)" in brief            # thread header
    # The old terms stay legible instead of collapsing to a count.
    assert "Belgium is yours if Burgundy is mine" in brief


def test_older_thread_trims_long_bodies_and_deep_threads(tmp_path):
    _game(tmp_path, press="full")
    pub = state.pubkey_file(tmp_path).read_text(encoding="utf-8")
    comms.claim_power(tmp_path, "FRANCE")
    comms.claim_power(tmp_path, "ENGLAND")
    sign = comms.load_keys(tmp_path, "ENGLAND")["sign"]
    for i in range(6):
        comms.send_message(tmp_path, "ENGLAND", ["FRANCE"],
                           f"msg{i} " + "filler words " * 30, f"S190{i}M", pub,
                           sign_priv=sign)
    brief = context.power_brief(tmp_path, "FRANCE")
    # Older = msg0..msg3; only the last three of them survive, each as a gist.
    assert "msg0" not in brief                          # beyond thread depth
    assert "msg2" in brief
    assert "msg2 " + "filler words " * 30 not in brief  # trimmed
    assert "…" in brief
    # The two most recent phases are still quoted in full.
    assert "msg5 " + "filler words " * 30 in brief


def test_brief_toggles_disable_sections(tmp_path):
    game = _game(tmp_path)
    game.set_orders("FRANCE", ["A PAR S A MAR - BUR", "A MAR - SPA"])
    game.process()
    state.save_game(game, tmp_path)
    config = state.load_config(tmp_path)
    config["brief"] = {"annex": False, "outcomes": False, "digest": False,
                       "commitments": False}
    state.save_config(config, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Tactical annex" not in brief
    assert "Rules reminders" not in brief
    assert "what happened and why" not in brief
    assert "Your commitments" not in brief
    # The always-on core is untouched.
    assert "Supply-center standings" in brief


def test_notes_are_capped_in_brief(tmp_path):
    _game(tmp_path)
    notes = tmp_path / "notes"
    notes.mkdir()
    bloat = "\n".join(f"- stale plan line {i}" for i in range(400))
    (notes / "FRANCE.md").write_text("# FRANCE\n" + bloat, encoding="utf-8")
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "notes truncated" in brief
    assert "stale plan line 399" not in brief
    # The cap bounds the whole notes section, bloat can't blow up the brief.
    assert len(brief) < len(bloat)
