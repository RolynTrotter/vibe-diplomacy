"""What a seat sees and says: the brief, the board, the CLI, and model seats."""
import json

import pytest

from vibe import board, cli, game as gamemod, mapviz, run
from vibe.game import Match
from vibe.run import Runner, Seat, call_openai, parse_reply


@pytest.fixture
def games(tmp_path, monkeypatch):
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    return tmp_path


def token(match, power):
    return match.config["seats"][power]


# -- the brief and the board ------------------------------------------------ #
def test_brief_fits_one_screen_and_hides_the_machinery(games):
    m = Match.create("b", press="full")
    text = cli.brief(m, "FRANCE")
    assert len(text.splitlines()) <= 45
    assert token(m, "FRANCE") in text and token(m, "ENGLAND") not in text
    for word in ("python", "venv", "git", "pending", "games/", "encrypt", "key"):
        assert word not in text.lower().replace("--seat", "")
    for cmd in ("board", "submit", "wait", "send", "inbox"):
        assert f" {cmd} --seat" in text


def test_gunboat_brief_has_three_commands(games):
    text = cli.brief(Match.create("g"), "ITALY")
    assert text.count("--seat") == 3 and "send" not in text


def test_board_shows_legal_moves_and_outcomes(games):
    m = Match.create("o")
    m.submit("FRANCE", ["A PAR - BUR"])
    m.submit("GERMANY", ["A MUN - BUR"])
    m.advance(force=True)
    text = board.render(m, "FRANCE")
    assert "A PAR → BUR, GAS, PIC" in text or "A PAR →" in text
    assert "A PAR - BUR → bounced" in text
    assert "GERMANY: A MUN - BUR" in text


def test_board_never_shows_another_powers_mail(games):
    m = Match.create("m", press="full")
    m.send("ENGLAND", ["GERMANY"], "secret plan")
    assert "secret plan" not in board.render(m, "FRANCE", inbox=True)
    assert "secret plan" in board.render(m, "GERMANY", inbox=True)


# -- the CLI as a player uses it -------------------------------------------- #
def test_cli_submit_wait_loop(games, capsys):
    m = Match.create("c", max_year=1901)
    for p in gamemod.POWERS:
        if p != "FRANCE":
            m.submit(p, [])
    t = token(m, "FRANCE")
    assert cli.main(["submit", "--seat", t, "F BRE - LON"]) == 1
    assert "not legal" in capsys.readouterr().out
    assert cli.main(["submit", "--seat", t, "A PAR - BUR; F BRE - MAO"]) == 0
    assert cli.main(["wait", "--seat", t, "--timeout", "5"]) == 0
    out = capsys.readouterr().out
    assert "S1901M has resolved" in out and "F1901M" in out


def test_cli_wait_refuses_before_submitting(games, capsys):
    m = Match.create("w")
    assert cli.main(["wait", "--seat", token(m, "FRANCE")]) == 1
    assert "not submitted" in capsys.readouterr().out


def test_bad_token_is_a_clean_error(games, capsys):
    Match.create("x")
    assert cli.main(["board", "--seat", "deadbeef"]) == 2
    assert "no seat" in capsys.readouterr().err


# -- reading model replies -------------------------------------------------- #
def test_parse_reply_takes_last_fenced_block_and_routes_lines():
    r = parse_reply("<think>maybe A PAR - PIC</think>\n"
                    "TO ENGLAND: DMZ the channel?\n**TO GERMANY, ITALY:** hello\n"
                    "TO SELF: watch Germany\n"
                    "```\nA PAR - GAS\n```\nfinal:\n```\n1. A PAR - BUR\n- F BRE - MAO  # go\n```")
    assert r.orders == ["A PAR - BUR", "F BRE - MAO"]
    assert r.mail == [(["ENGLAND"], "DMZ the channel?"), (["GERMANY", "ITALY"], "hello")]
    assert r.notes == ["watch Germany"]


def test_parse_reply_bare_lines_and_think_only():
    assert parse_reply("I'll go\nA PAR - BUR\nF BRE H").orders == ["A PAR - BUR", "F BRE H"]
    assert parse_reply("<think>```\nA PAR - BUR\n```</think>").orders == ["A PAR - BUR"]


def test_reasoning_only_reply_is_used():
    seat = Seat("openai", "m", "http://x/v1")
    fake = lambda url, h, p, t: {"choices": [{"message": {
        "content": "", "reasoning_content": "```\nA PAR - BUR\n```"}}]}
    text = call_openai(seat, "sys", "prompt", None, 100, 5, transport=fake)
    assert parse_reply(text).orders == ["A PAR - BUR"]


def test_openai_request_shape():
    seen = {}

    def fake(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    call_openai(Seat("openai", "qwen", "http://h/v1", "k"), "sys", "hi", None, 50, 5,
                transport=fake)
    assert seen["url"] == "http://h/v1/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer k"}
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "sys"}


def test_seat_specs():
    assert run.parse_seat("qwen3:8b", "http://h/v1", "").base_url == "http://h/v1"
    s = run.parse_seat("openai:llama@http://o/v1/", "", "")
    assert (s.model, s.base_url) == ("llama", "http://o/v1")
    assert run.parse_seat("claude:sonnet", "", "").kind == "claude"
    assert run.parse_seat("agent", "", "").kind == "agent"


# -- the runner ------------------------------------------------------------- #
def test_fake_seats_play_a_full_press_game_to_the_cap(games):
    m = Match.create("f", press="full", max_year=1902)
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    Runner(m, seats, seed=3, log=lambda *_: None).play()
    assert m.ended() == "year cap 1902"
    assert (m.path / "history" / "F1902M.json").exists()


def test_a_seat_with_no_usable_reply_holds_after_one_retry(games):
    m = Match.create("h")
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    seats["FRANCE"] = Seat("openai", "m", "http://x/v1")
    calls = []

    def fake(seat, system, prompt, image, max_tokens, timeout):
        calls.append(prompt)
        return "I am not sure what to do."

    runner = Runner(m, seats, seed=1, log=lambda *_: None)
    import vibe.run as r
    orig = r.call_openai
    r.call_openai = fake
    try:
        runner.phase()
    finally:
        r.call_openai = orig
    assert len(calls) == 2 and "could not be used" in calls[1]
    assert json.loads((m.path / "history" / "S1901M.json").read_text())["orders"]["FRANCE"] == []


# -- the picture ------------------------------------------------------------ #
def test_board_svg_is_labelled_and_keyed(games):
    svg = mapviz.board_svg(Match.create("s").load())
    assert 'id="ProvinceLabels"' in svg and "FRANCE — 3" in svg
    assert 'class="labeltext24"' not in svg


# -- hosting ---------------------------------------------------------------- #
def test_check_endpoint_reports_down_and_missing_model(monkeypatch):
    down = run.check_endpoint(Seat("openai", "m", "http://127.0.0.1:9/v1"))
    assert not down[0] and down[1].startswith("endpoint DOWN")

    class Resp:
        def __init__(self, body): self.body = body
        def read(self): return json.dumps(self.body).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(run.urllib.request, "urlopen",
                        lambda req, timeout: Resp({"data": [{"id": "flint"}]}))
    ok, line = run.check_endpoint(Seat("openai", "qwen", "http://h/v1"))
    assert not ok and "It serves: flint" in line
    monkeypatch.setattr(run, "_post", lambda *a: {"choices": []})
    assert run.check_endpoint(Seat("openai", "flint", "http://h/v1")) == \
        (True, "endpoint OK: flint @ http://h/v1")


def test_new_remembers_the_model_for_run(games, monkeypatch, capsys):
    monkeypatch.setattr(run, "check_endpoint", lambda seat: (True, "endpoint OK: x"))
    assert cli.main(["new", "r", "--model", "flint", "--base-url", "http://h/v1/"]) == 0
    out = capsys.readouterr().out
    assert "endpoint OK" in out and out.rstrip().endswith("dip run r")
    assert Match.open("r").config["run"] == {"model": "flint", "base_url": "http://h/v1"}
