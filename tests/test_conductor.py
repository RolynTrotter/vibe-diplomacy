"""The programmatic conductor seam: tasks -> collect -> advance.

The conductor used to spend model tokens on work with no judgement in it —
composing seven near-identical prompts, remembering which CLI each subagent
should run, committing after every power. These tests pin the replacement:
one call builds every task, one call turns a plain-text reply into sealed
artifacts, one call closes the phase.
"""
import os

from orchestration import conduct, tasks
from orchestration.match_spec import MatchSpec

from engine import comms, crypto, state


def _game(tmp_path, press="full"):
    game = state.new_game("conductor-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "conductor-test", "press": press,
                       "powers": {p: {"type": "agent"} for p in conduct.POWERS}},
                      tmp_path)
    priv, pub = crypto.generate_keypair()
    state.pubkey_file(tmp_path).write_text(pub, encoding="utf-8")
    return game, priv


def _hold_orders(game, power):
    possible = game.get_all_possible_orders()
    return [next(o for o in possible[loc] if o.endswith(" H"))
            for loc in game.get_orderable_locations(power)]


# --------------------------------------------------------------------------- #
# Task text
# --------------------------------------------------------------------------- #
def test_full_press_movement_defaults_to_one_combined_call(tmp_path):
    _game(tmp_path)
    out = conduct.phase_tasks(tmp_path)
    assert out["kind"] == "combined"
    assert len(out["powers"]) == 7
    task = out["powers"]["FRANCE"]
    # Self-contained: who you are, the brief, and the exact reply format.
    assert "You are FRANCE" in task
    assert "Supply-center standings" in task
    assert "TO <POWER>: <message>" in task and "fenced code block" in task


def test_gunboat_asks_for_orders_only(tmp_path):
    _game(tmp_path, press="none")
    out = conduct.phase_tasks(tmp_path)
    assert out["kind"] == "orders"
    assert "TO <POWER>" not in out["powers"]["FRANCE"]


def test_agentic_style_tells_the_seat_to_run_the_clis(tmp_path):
    _game(tmp_path)
    reply_style = conduct.phase_tasks(tmp_path)["powers"]["FRANCE"]
    agentic = conduct.phase_tasks(tmp_path, style="agentic")["powers"]["FRANCE"]
    assert "submit.sh" in agentic and "submit.sh" not in reply_style
    # A tool-less seat is told exactly what to type back; an agentic one isn't.
    assert reply_style.rstrip().endswith("there is no later round.")


def test_tasks_can_be_limited_to_named_powers(tmp_path):
    _game(tmp_path)
    out = conduct.phase_tasks(tmp_path, powers=["france"])
    assert list(out["powers"]) == ["FRANCE"]


def test_unknown_kind_is_refused(tmp_path):
    _game(tmp_path)
    try:
        conduct.phase_tasks(tmp_path, kind="freestyle")
    except ValueError as exc:
        assert "freestyle" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_builder_is_shared_with_run_match(tmp_path):
    """One wording for every front end — drift means powers play different games."""
    built = tasks.build("FRANCE", "orders", "S1901M", "BRIEF", press="none")
    assert "BRIEF" in built and built.count("You are FRANCE") == 1


# --------------------------------------------------------------------------- #
# Collecting a subagent's reply
# --------------------------------------------------------------------------- #
def test_collect_seals_mail_and_orders_from_one_reply(tmp_path):
    game, adj_priv = _game(tmp_path)
    comms.claim_power(tmp_path, "ENGLAND")
    reply = ("TO ENGLAND: Channel DMZ?\n"
             "TO NOBODY: pass\n"
             "Prose the parser should ignore.\n"
             "```\n" + "\n".join(_hold_orders(game, "FRANCE")) + "\n```")
    out = conduct.collect_reply(tmp_path, "FRANCE", reply)
    assert out["ok"], out["error"]
    assert out["sent"] == ["ENGLAND"] and len(out["orders"]) == 3
    # Sealed orders exist, and England really can read the mail.
    assert state.power_orders_file(tmp_path, "FRANCE", "S1901M").exists()
    eng_priv = comms.load_privkey(tmp_path, "ENGLAND")
    assert "Channel DMZ?" in [m["body"] for m in
                              comms.read_inbox(tmp_path, "ENGLAND", eng_priv)]


def test_collect_claims_an_unclaimed_seat(tmp_path):
    game, _ = _game(tmp_path)
    assert "FRANCE" not in comms.list_players(tmp_path)
    reply = "```\n" + "\n".join(_hold_orders(game, "FRANCE")) + "\n```"
    assert conduct.collect_reply(tmp_path, "FRANCE", reply)["ok"]
    assert "FRANCE" in comms.list_players(tmp_path)


def test_collect_returns_the_rejection_as_retry_text(tmp_path):
    """The error IS the next prompt — the conductor shouldn't re-derive it."""
    _game(tmp_path)
    reply = "```\nA PAR S A MAR - BUR\nA MAR - SPA\nF BRE - MAO\n```"
    out = conduct.collect_reply(tmp_path, "FRANCE", reply)
    assert not out["ok"]
    assert "void" in out["error"].lower()


def test_collect_flags_an_empty_reply(tmp_path):
    _game(tmp_path)
    out = conduct.collect_reply(tmp_path, "FRANCE", "I'd rather not say.")
    assert not out["ok"] and "parseable orders" in out["error"]


def test_collect_ignores_mail_in_a_gunboat_game(tmp_path):
    game, _ = _game(tmp_path, press="none")
    reply = ("TO ENGLAND: psst\n```\n"
             + "\n".join(_hold_orders(game, "FRANCE")) + "\n```")
    out = conduct.collect_reply(tmp_path, "FRANCE", reply)
    assert out["ok"] and out["sent"] == []


# --------------------------------------------------------------------------- #
# Advancing the phase
# --------------------------------------------------------------------------- #
def _git(tmp_path, *args):
    from orchestration._common import git
    return git(tmp_path, *args)


def test_advance_commits_once_adjudicates_and_moves_on(tmp_path, monkeypatch):
    game, adj_priv = _game(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    for power in conduct.POWERS:
        reply = "```\n" + "\n".join(_hold_orders(game, power)) + "\n```"
        assert conduct.collect_reply(tmp_path, power, reply)["ok"]

    monkeypatch.setenv("ADJUDICATOR_PRIVATE_KEY", adj_priv)
    result = conduct.advance(tmp_path, push=False)
    assert result["adjudicated"], result.get("error")
    assert result["phase"] == "S1901M" and result["next_phase"] == "F1901M"
    assert not result["done"]
    # Two commits for the whole phase, not one per power per round.
    log = _git(tmp_path, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 2
    assert "Adjudicate S1901M" in log[0]


def test_advance_says_plainly_when_the_key_is_missing(tmp_path, monkeypatch):
    _game(tmp_path)
    monkeypatch.delenv("ADJUDICATOR_PRIVATE_KEY", raising=False)
    result = conduct.advance(tmp_path, push=False)
    assert not result["adjudicated"]
    assert "ADJUDICATOR_PRIVATE_KEY" in result["error"]


def test_collect_never_leaks_the_adjudicator_key(tmp_path, monkeypatch):
    """A player subprocess must never see the key that opens sealed orders."""
    game, adj_priv = _game(tmp_path)
    monkeypatch.setenv("ADJUDICATOR_PRIVATE_KEY", adj_priv)
    seen = {}

    real_run = conduct.subprocess.run

    def spy(args, **kwargs):
        seen.update(kwargs.get("env") or {})
        return real_run(args, **kwargs)

    monkeypatch.setattr(conduct.subprocess, "run", spy)
    reply = "```\n" + "\n".join(_hold_orders(game, "FRANCE")) + "\n```"
    conduct.collect_reply(tmp_path, "FRANCE", reply)
    assert "ADJUDICATOR_PRIVATE_KEY" not in seen


# --------------------------------------------------------------------------- #
# The schedule that halves the calls
# --------------------------------------------------------------------------- #
def test_combined_final_round_is_the_default():
    spec = MatchSpec.load(None, name="t", press="full")
    assert spec.combined_final_round is True


def test_combined_kind_reaches_the_raw_backend(tmp_path):
    """One reply carries both halves: mail goes out, orders get sealed."""
    from orchestration.player_agent import RawChatAgent
    game, _ = _game(tmp_path)
    comms.claim_power(tmp_path, "ENGLAND")
    spec = MatchSpec.load(None, name="t", press="full")
    spec.seats["FRANCE"].vision = False
    orders = "\n".join(_hold_orders(game, "FRANCE"))

    def transport(url, headers, payload, timeout):
        return {"choices": [{"message": {
            "content": f"TO ENGLAND: peace?\n```\n{orders}\n```"}}]}

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent = RawChatAgent("FRANCE", spec.seats["FRANCE"], repo, tmp_path, spec,
                         transport=transport)
    result = agent.dispatch("task text", kind="combined")
    assert result.ok, result.error
    assert state.power_orders_file(tmp_path, "FRANCE", "S1901M").exists()
    eng_priv = comms.load_privkey(tmp_path, "ENGLAND")
    assert "peace?" in [m["body"] for m in
                        comms.read_inbox(tmp_path, "ENGLAND", eng_priv)]


# --------------------------------------------------------------------------- #
# FINAL_MESSAGES: a power that is done talking stops being asked
# --------------------------------------------------------------------------- #
def test_a_power_that_says_it_is_done_sits_out_later_rounds(tmp_path, monkeypatch):
    """Asking a finished power again buys a near-empty reply at full price."""
    from orchestration.match_spec import MatchSpec
    from orchestration.player_agent import AgentResult
    from orchestration.run_match import Conductor

    spec = MatchSpec.load(None, press="full", negotiation_rounds=3,
                          combined_final_round=False, max_phases=1)
    conductor = Conductor(spec, tmp_path, tmp_path, backend="fake")

    asked: list[tuple[int, str]] = []

    class _Stub:
        def __init__(self, power):
            self.power = power

        def dispatch(self, task, kind="orders"):
            asked.append((len(asked), self.power, kind))
            # FRANCE bows out after the first round; everyone else keeps going.
            return AgentResult(reply="", ok=True,
                               final=(self.power == "FRANCE" and kind == "negotiation"))

    monkeypatch.setattr(conductor, "_agent_for", lambda p: _Stub(p))
    monkeypatch.setattr(conductor, "_build_task", lambda p, k, ph: "task")
    monkeypatch.setattr(conductor, "_write_transcript",
                        lambda *a, **k: None)

    # Drive the real dispatch helper rather than re-implementing its loop.
    done: set[str] = set()
    rounds = []
    for rnd in range(3):
        speaking = [p for p in ("FRANCE", "ENGLAND") if p not in done]
        rounds.append(list(speaking))
        results = conductor._dispatch_round(speaking, "negotiation", "S1901M", rnd)
        done |= {r["power"] for r in results if r.get("final")}

    assert rounds[0] == ["FRANCE", "ENGLAND"]
    assert rounds[1] == ["ENGLAND"], "FRANCE said FINAL_MESSAGES"
    assert rounds[2] == ["ENGLAND"]


def test_final_is_carried_out_of_a_dispatch(tmp_path, monkeypatch):
    from orchestration.match_spec import MatchSpec
    from orchestration.player_agent import AgentResult
    from orchestration.run_match import Conductor

    spec = MatchSpec.load(None, press="full")
    conductor = Conductor(spec, tmp_path, tmp_path, backend="fake")

    class _Stub:
        def dispatch(self, task, kind="orders"):
            return AgentResult(reply="", ok=True, final=True)

    monkeypatch.setattr(conductor, "_agent_for", lambda p: _Stub())
    monkeypatch.setattr(conductor, "_build_task", lambda p, k, ph: "task")
    monkeypatch.setattr(conductor, "_write_transcript", lambda *a, **k: None)
    rows = conductor._dispatch_round(["FRANCE"], "negotiation", "S1901M", 0)
    assert rows[0]["final"] is True
