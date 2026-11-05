"""What a seat sees and says: the brief, the board, the CLI, and model seats."""
import json
import subprocess

import pytest

from vibe import board, cli, game as gamemod, mapviz, run
from vibe.game import Match
from vibe.game import normalize
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
    assert "\nA PAR - BUR   # empty\n" in text and "\nA PAR H\n" in text
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
                    "```\nA PAR - GAS\n```\nfinal:\n```\n1. A PAR - BUR\n- F BRE - MAO  # go\n```")
    assert r.orders == ["A PAR - BUR", "F BRE - MAO"]
    assert r.mail == [(["ENGLAND"], "DMZ the channel?"), (["GERMANY", "ITALY"], "hello")]


def test_parse_reply_bare_lines_and_think_only():
    assert parse_reply("I'll go\nA PAR - BUR\nF BRE H").orders == ["A PAR - BUR", "F BRE H"]
    assert parse_reply("<think>```\nA PAR - BUR\n```</think>").orders == ["A PAR - BUR"]


def test_fences_on_the_same_line_unclosed_or_after_drafts():
    assert parse_reply("Plan: A BUD - GAL maybe\n```A BUD - SER\nF TRI H```").orders == [
        "A BUD - SER", "F TRI H"]
    assert parse_reply("A VIE - TYR is tempting\n```text\nA VIE - GAL\n```").orders == [
        "A VIE - GAL"]
    cut = "draft:\n```\nA PAR - PIC\n```\nbetter:\n```\nA PAR - BUR\nF BRE"
    assert parse_reply(cut).orders == ["A PAR - BUR"]        # half an order is not one
    assert parse_reply("```\nTO ENGLAND: hi\n```\nA PAR H").orders == ["A PAR H"]


def test_a_unit_written_as_a_label_still_reads():
    assert normalize("F LON: F LON - NTH") == normalize("F LON: - NTH") == "F LON - NTH"
    assert normalize("F LON: H") == "F LON H" and normalize("A PAR - BUR,") == "A PAR - BUR"


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


def test_a_seat_with_no_usable_reply_holds_after_one_finishing_call(games):
    m = Match.create("h")
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    seats["FRANCE"] = Seat("openai", "m", "http://x/v1")
    calls = []

    def fake(seat, system, prompt, image, max_tokens, timeout, **kw):
        calls.append((prompt, max_tokens))
        return run.Answer.of("I am not sure what to do.")

    runner = Runner(m, seats, seed=1, log=lambda *_: None)
    import vibe.run as r
    orig = r.call_openai
    r.call_openai = fake
    try:
        runner.phase()
    finally:
        r.call_openai = orig
    assert len(calls) == 2 and "had no orders in a fenced code block" in calls[1][0]
    assert calls[1][1] == run.FINISH_TOKENS and calls[0][1] == runner.max_tokens
    assert json.loads((m.path / "history" / "S1901M.json").read_text())["orders"]["FRANCE"] == []
    assert runner.stats == {"finishes": 1, "held": 1}


def test_a_cut_off_reply_is_finished_not_redone(games, monkeypatch):
    m = Match.create("cut")
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    seats["ENGLAND"] = Seat("openai", "m", "http://x/v1")
    prompts, lines = [], []

    def fake(seat, system, prompt, image, max_tokens, timeout, **kw):
        prompts.append(prompt)
        if len(prompts) == 1:
            return run.Answer.of("", "Long thought: the fleet should go north. This means",
                                 "length", 8000)
        return run.Answer.of("```\nF LON - NTH\nF EDI - NWG\nA LVP - YOR\n```", tokens=40)

    monkeypatch.setattr(run, "call_openai", fake)
    runner = Runner(m, seats, seed=1, log=lines.append)
    runner.play(max_phases=1)
    finish = prompts[1]
    assert finish.startswith(prompts[0])                    # cache-friendly prefix
    assert "the fleet should go north. This means" in finish   # its reasoning is kept
    assert "cut off at the length limit" in finish
    assert m.history("S1901M")["orders"]["ENGLAND"] == ["F LON - NTH", "F EDI - NWG", "A LVP - YOR"]
    assert any("3 order(s) [+finish 40 tok, cut off]" in l for l in lines)
    assert lines[-1].startswith("Finishing calls: 1 (1 gave usable orders). Seats that held: 0")


def test_stream_reports_finish_reason_and_usage(monkeypatch):
    class Stream:
        headers = {"Content-Type": "text/event-stream"}
        lines = [b'data: {"choices":[{"delta":{"content":"So the plan"}}]}\n',
                 b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
                 b'data: {"choices":[],"usage":{"completion_tokens":8000}}\n',
                 b"data: [DONE]\n"]
        def __iter__(self): return iter(self.lines)
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(run.urllib.request, "urlopen", lambda req, timeout: Stream())
    a = call_openai(Seat("openai", "m", "http://h/v1"), "s", "p", None, 10, 5)
    assert a == "So the plan" and a.cut_off and a.cost() == "8000 tok"
    assert run.Answer.of("x" * 40).cost() == "~10 tok"


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


def test_streamed_reply_is_reassembled_and_idle_timeout_is_explained(monkeypatch):
    class Stream:
        headers = {"Content-Type": "text/event-stream"}
        lines = [b'data: {"choices":[{"delta":{"reasoning_content":"thinking "}}]}\n',
                 b'data: {"choices":[{"delta":{"content":"```\\nA PAR"}}]}\n',
                 b'data: {"choices":[{"delta":{"content":" - BUR\\n```"}}]}\n',
                 b"data: [DONE]\n"]
        def __iter__(self): return iter(self.lines)
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(run.urllib.request, "urlopen", lambda req, timeout: Stream())
    text = call_openai(Seat("openai", "m", "http://h/v1"), "s", "p", None, 10, 5)
    assert parse_reply(text).orders == ["A PAR - BUR"]

    def silent(req, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr(run.urllib.request, "urlopen", silent)
    with pytest.raises(TimeoutError, match="no tokens for 5s"):
        call_openai(Seat("openai", "m", "http://h/v1"), "s", "p", None, 10, 5)


# -- nothing a seat might copy is an illegal order -------------------------- #
def _listed_orders(text):
    section = text.split("## Your orders this phase", 1)[1].split("\n## ", 1)[0]
    return [l for l in section.splitlines() if l[:2] in ("A ", "F ")]


@pytest.mark.parametrize("power", gamemod.POWERS)
def test_every_listed_line_and_example_is_a_legal_order(games, power):
    from vibe.game import check_orders
    m = Match.create(f"l{power}")
    game = m.load()
    lines = _listed_orders(board.render(m, power))
    assert lines and all(check_orders(game, power, [l]).ok for l in lines)
    fmt = run.orders_format(m, power)
    assert "```" not in fmt and not parse_reply(fmt).orders   # nothing to echo back
    assert all(u in fmt for u in game.powers[power].units)


def test_annotated_and_arrow_lines_still_parse(games):
    m = Match.create("a")
    assert m.submit("GERMANY", ["A MUN - BUR   # GERMANY A is there", "A BER → KIE"]).ok


def test_finishing_call_restates_errors_and_units(games, monkeypatch):
    m = Match.create("rr")
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    seats["ITALY"] = Seat("openai", "m", "http://x/v1")
    prompts = []

    def fake(seat, system, prompt, image, max_tokens, timeout, **kw):
        prompts.append(prompt)
        return run.Answer.of("```\nA PAR - BUR\n```" if len(prompts) == 1 else "```\nA VEN H\n```")

    monkeypatch.setattr(run, "call_openai", fake)
    Runner(m, seats, seed=1, log=lambda *_: None).phase()
    tail = prompts[1].split("Your reply so far:")[1]
    assert "could not be used" in tail and "nothing to order at PAR" in tail
    assert "Your units: F NAP, A ROM, A VEN" in tail
    assert "```" not in tail.split(">>>")[1]                 # no example to copy
    assert m.history("S1901M")["orders"]["ITALY"] == ["A VEN H"]
    told = board.render(m, "ITALY").split("## How your last orders went")[1]
    assert "A PAR - BUR — you had nothing to order at PAR" in told
    assert "could not be used" not in board.render(m, "FRANCE")   # private to Italy


def test_a_move_to_a_province_it_does_not_border_says_so(games):
    m = Match.create("adj")
    checked = gamemod.check_orders(m.load(), "FRANCE", ["A PAR - BEL", "F BRE H"])
    assert checked.refused == ["A PAR - BEL — not a legal order: PAR does not border BEL"]
    m.submit("FRANCE", ["F BRE H"], partial=True, refused=checked.refused)
    m.advance(force=True)
    told = board.render(m, "FRANCE").split("## How your last orders went")[1]
    assert "All 1 of your S1901M orders succeeded." in told
    assert "could not be used" in told and "PAR does not border BEL" in told


def test_cli_refuses_orders_written_for_a_phase_that_resolved(games, capsys):
    m = Match.create("late")
    t = token(m, "FRANCE")
    cli.main(["board", "--seat", t])                # FRANCE looks at S1901M
    m.advance(force=True)                           # ...which resolves meanwhile
    capsys.readouterr()
    assert cli.main(["submit", "--seat", t, "A PAR - BUR"]) == 1
    assert "S1901M has already resolved" in capsys.readouterr().out
    assert cli.main(["submit", "--seat", t, "A PAR - BUR"]) == 0   # now it has seen F1901M


def test_status_says_a_phase_resolved_with_seats_missing(games, capsys):
    m = Match.create("miss")
    m.submit("FRANCE", [])
    m.advance(force=True)
    cli.main(["status", "miss"])
    assert "S1901M resolved (forced) with 6 seat(s) missing" in capsys.readouterr().out


def test_board_lists_every_supply_centre_by_owner(games):
    m = Match.create("sc")
    m.submit("FRANCE", ["A MAR - SPA"])
    m.advance(force=True)                            # a French army in neutral Spain
    text = board.render(m, "ITALY").split("## Supply centres (34; 18 wins)\n")[1].split("\n\n")[0]
    rows = text.splitlines()
    assert rows[0].startswith("- RUSSIA: 4 centres, 4 units — MOS, SEV, STP, WAR")
    assert "- ITALY: 3 centres, 3 units ← you — NAP, ROM, VEN" in rows
    assert rows[-1].startswith("- neutral: 12 — BEL, BUL, DEN,") and "SPA (FRANCE A there)" in rows[-1]
    assert sum(len(r.split(" — ")[1].split(", ")) for r in rows) == 34


def test_moves_say_what_is_there_and_which_of_your_units_can_support_them(games):
    text = board.render(Match.create("near"), "AUSTRIA")
    assert "\nA BUD - GAL   # empty\n    A VIE S A BUD - GAL\n" in text
    assert "\nF TRI - VEN   # ITALY centre, ITALY A there\n" in text
    assert "\nA VIE - TRI   # your centre, your F there\n" in text
    assert "## Around you" not in text
    assert board._no_coast("F BLA - BUL/EC") == "F BLA - BUL"

def test_claude_seats_report_real_tokens(monkeypatch):
    out = json.dumps({"result": "```\nA PAR H\n```", "stop_reason": "max_tokens",
                      "total_cost_usd": 0.01, "usage": {
                          "input_tokens": 5, "cache_creation_input_tokens": 100,
                          "cache_read_input_tokens": 900, "output_tokens": 40}})
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout=out, stderr=""))
    a = run.call_claude(run.Seat("claude", "haiku"), "sys", "prompt", None, 100, 10)
    assert a == "```\nA PAR H\n```" and a.cut_off
    assert (a.read, a.tokens, a.usd, a.estimated) == (1005, 40, 0.01, False)


def test_reasoning_lines_are_not_orders():
    thinking = ("A TUS - VEN is legal? List: A TUS - PIE, A TUS - ROM\n"
                "F KIE - BAL? Or F KIE - DEN? Or F KIE H?\n"
                "F EDI: F EDI - CLY, F EDI - NTH, F EDI H\n"
                "A MUN - BUR is in legal list? yes\n")
    assert parse_reply(thinking).orders == []
    assert parse_reply("```\nA MUN - BUR (to bounce)\nF KIE: F KIE - DEN\n"
                       "A ROM S A NAP - APU\nF NAP C A ROM - TUN\n```").orders == [
        "A MUN - BUR", "F KIE: F KIE - DEN", "A ROM S A NAP - APU", "F NAP C A ROM - TUN"]


def test_units_the_finishing_call_leaves_out_keep_their_first_order(games, monkeypatch):
    m = Match.create("merge")
    seats = {p: Seat("fake") for p in gamemod.POWERS}
    seats["ENGLAND"] = Seat("openai", "m", "http://x/v1")
    replies = iter([run.Answer.of("```\nF LON - NTH\nF EDI - LON\nA LVP - YOR\n```"),
                    run.Answer.of("```\nF EDI - NWG\n```")])
    monkeypatch.setattr(run, "call_openai", lambda *a, **k: next(replies))
    Runner(m, seats, seed=1, log=lambda *_: None).play(max_phases=1)
    assert sorted(m.history("S1901M")["orders"]["ENGLAND"]) == [
        "A LVP - YOR", "F EDI - NWG", "F LON - NTH"]


def test_unfenced_reasoning_keeps_each_units_last_mention():
    thinking = ("Maybe F EDI - NWG? Or:\nF EDI - NTH\nF LON - ENG\nA LVP - YOR\n"
                "On reflection the order set:\nF EDI - CLY\nF LON - ENG\nA LVP - WAL\n")
    assert parse_reply(thinking).orders == ["F EDI - CLY", "F LON - ENG", "A LVP - WAL"]
    fenced = "```\nF EDI - NTH\nF EDI - CLY\n```"
    assert parse_reply(fenced).orders == ["F EDI - NTH", "F EDI - CLY"]   # still a conflict


def test_after_a_winter_the_board_still_shows_the_last_moves(games):
    m = Match.create("moves")
    for orders in (["A MAR - SPA"], ["A SPA H"], ["A MAR B"]):
        for p in m.owing(m.load()):
            if p != "FRANCE":
                m.submit(p, [])
        m.submit("FRANCE", orders)
    assert m.phase() == "S1902M"
    last = board.render(m, "GERMANY").split("## Last moves\n")[1].split("\n\n")[0]
    assert last.startswith("_F1901M:_\n- FRANCE: A SPA H")
    assert "_Then W1901A:_ FRANCE A MAR B" in last
