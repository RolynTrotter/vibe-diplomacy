"""The board picture: labelled render, per-phase cache, and how seats get it.

The picture exists to fix a specific failure — agents reasoning about a map
they can only read as prose — so these tests pin the properties that make it
usable: province names present, the cairosvg-hostile CSS class gone, a legend
that says which colour is which power, and a graceful "no picture" when
cairosvg has no system cairo behind it.
"""
from pathlib import Path

from orchestration.match_spec import MatchSpec
from orchestration.player_agent import RawChatAgent

from engine import context, crypto, mapviz, state

REPO = Path(__file__).resolve().parent.parent


def _game_root(tmp_path, press="none"):
    game = state.new_game("map-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "map-test", "press": press, "powers": {}},
                      tmp_path)
    _, adj_pub = crypto.generate_keypair()
    state.pubkey_file(tmp_path).write_text(adj_pub, encoding="utf-8")
    return game


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_board_svg_is_labelled_and_keyed(tmp_path):
    game = _game_root(tmp_path)
    svg = mapviz.board_svg(game)
    # Province names: the stock render hides these, which is the whole problem.
    assert ">BUR<" in svg and ">MAO<" in svg and ">STP<" in svg
    # No element may still USE the class cairosvg mis-applies (it paints the
    # whole map black); the unused rule left in the stylesheet is harmless.
    assert 'class="labeltext24"' not in svg
    assert 'class="labeltext18"' not in svg
    # A colour key, since nothing on the stock map says who is who.
    assert "FRANCE" in svg and "royalblue" in svg


def test_board_svg_legend_is_optional(tmp_path):
    game = _game_root(tmp_path)
    assert "Legend" not in mapviz.board_svg(game, legend=False)


def test_phase_image_renders_once_per_phase(tmp_path):
    game = _game_root(tmp_path)
    first = mapviz.phase_image(tmp_path, game)
    if first is None:                       # no system cairo on this machine
        assert not mapviz.available()[0]
        return
    assert first.name == "S1901M.png" and first.stat().st_size > 0
    stamp = first.stat().st_mtime_ns
    assert mapviz.phase_image(tmp_path, game).stat().st_mtime_ns == stamp


def test_phase_image_is_none_without_cairo(tmp_path, monkeypatch):
    game = _game_root(tmp_path)
    monkeypatch.setattr(mapviz, "available", lambda: (False, "no libcairo"))
    assert mapviz.phase_image(tmp_path, game) is None


def test_brief_explains_a_missing_picture(tmp_path, monkeypatch):
    _game_root(tmp_path)
    monkeypatch.setattr(mapviz, "available", lambda: (False, "no libcairo"))
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "no board image" in brief and "cairosvg" in brief


def test_brief_points_at_the_picture_and_names_your_colour(tmp_path):
    _game_root(tmp_path)
    if not mapviz.available()[0]:
        return
    brief = context.power_brief(tmp_path, "FRANCE")
    assert ".board/S1901M.png" in brief
    assert "royalblue" in brief             # which colour on the map is you


# --------------------------------------------------------------------------- #
# Topology text (the same facts for a seat that cannot see)
# --------------------------------------------------------------------------- #
def test_topology_lists_nearby_centers_with_routes(tmp_path):
    game = _game_root(tmp_path)
    game.set_orders("FRANCE", ["A PAR - BUR", "F BRE - MAO", "A MAR - SPA"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Board topology" in brief
    assert "**BEL** (neutral) — 1 move" in brief          # BUR is adjacent
    assert "**MUN** (GERMANY) — 1 move" in brief          # owner named
    # A 2-hop target names the province you step into first — the door someone
    # else can shut — not the province your unit already stands in.
    assert "**BER** (GERMANY) — 2 moves in through MUN" in brief
    # Standing on an unowned center is the fact that decides a Fall order.
    assert "**SPA** (neutral) — you occupy it" in brief


def test_topology_names_the_powers_touching_you(tmp_path):
    game = _game_root(tmp_path)
    game.set_orders("FRANCE", ["A PAR - BUR"])
    game.set_orders("GERMANY", ["A MUN - RUH"])
    game.process()
    state.save_game(game, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "**GERMANY**: BUR–RUH" in brief


def test_topology_can_be_switched_off(tmp_path):
    _game_root(tmp_path)
    config = state.load_config(tmp_path)
    config["brief"] = {"topology": False, "image": False}
    state.save_config(config, tmp_path)
    brief = context.power_brief(tmp_path, "FRANCE")
    assert "Board topology" not in brief
    assert "The board, drawn" not in brief


# --------------------------------------------------------------------------- #
# Delivery to a raw seat
# --------------------------------------------------------------------------- #
def _raw_agent(tmp_path, endpoint="local", vision=True):
    spec = MatchSpec.load(None, name="map-test")
    seat = spec.seats["FRANCE"]
    seat.endpoint, seat.vision = endpoint, vision
    sent = []

    def transport(url, headers, payload, timeout):
        sent.append(payload["messages"][0]["content"])
        if "anthropic" in url:
            return {"content": [{"type": "text", "text": "ok"}]}
        return {"choices": [{"message": {"content": "ok"}}]}

    return RawChatAgent("FRANCE", seat, REPO, tmp_path, spec,
                        transport=transport), sent


def test_local_seat_gets_the_board_as_a_data_uri(tmp_path):
    _game_root(tmp_path)
    if not mapviz.available()[0]:
        return
    agent, sent = _raw_agent(tmp_path)
    agent._complete("your orders please")
    parts = sent[0]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1]["text"] == "your orders please"


def test_api_seat_gets_a_base64_image_block(tmp_path):
    _game_root(tmp_path)
    if not mapviz.available()[0]:
        return
    agent, sent = _raw_agent(tmp_path, endpoint="api")
    agent._complete("your orders please")
    parts = sent[0]
    assert parts[0]["type"] == "image"
    assert parts[0]["source"]["media_type"] == "image/png"
    assert parts[0]["source"]["data"]


def test_vision_false_sends_plain_text(tmp_path):
    _game_root(tmp_path)
    agent, sent = _raw_agent(tmp_path, vision=False)
    agent._complete("your orders please")
    assert sent[0] == "your orders please"


def test_image_rejection_retries_without_the_picture(tmp_path):
    """A model that can't take images must still get to play its turn."""
    _game_root(tmp_path)
    if not mapviz.available()[0]:
        return
    spec = MatchSpec.load(None, name="map-test")
    sent = []

    def transport(url, headers, payload, timeout):
        content = payload["messages"][0]["content"]
        sent.append(content)
        if not isinstance(content, str):
            raise RuntimeError("400: this model does not support images")
        return {"choices": [{"message": {"content": "ok"}}]}

    agent = RawChatAgent("FRANCE", spec.seats["FRANCE"], REPO, tmp_path, spec,
                         transport=transport)
    assert agent._complete("your orders please") == "ok"
    assert len(sent) == 2 and sent[1] == "your orders please"
