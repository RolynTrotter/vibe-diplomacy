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
