"""RawChatAgent: one completion per turn, driven through the real CLIs.

No model server anywhere — the transport is a stub. What matters is that a
parsed reply produces the same signed/sealed artifacts as any other player,
and that a rejected set triggers exactly one corrective retry.
"""
import json
from pathlib import Path

from orchestration.match_spec import MatchSpec
from orchestration.player_agent import (RawChatAgent, extract_messages,
                                        extract_orders, make_agent)

from engine import comms, crypto, state

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Reply parsing
# --------------------------------------------------------------------------- #
def test_extract_orders_prefers_last_fenced_block():
    reply = (
        "Thinking: maybe ```A PAR H``` no wait.\n"
        "Final answer:\n```\nA PAR - BUR\nF BRE - MAO  # to the ocean\n"
        "A MAR S A PAR - BUR\n```\n"
    )
    assert extract_orders(reply) == [
        "A PAR - BUR", "F BRE - MAO", "A MAR S A PAR - BUR"]


def test_extract_orders_falls_back_to_bare_lines():
    reply = "A PAR - BUR\nsome chatter\nF BRE - MAO"
    assert extract_orders(reply) == ["A PAR - BUR", "F BRE - MAO"]


def test_extract_messages_parses_and_caps():
    reply = "\n".join([
        "TO ENGLAND: Channel DMZ?",
        "TO ALL: peace in our time",
        "TO NARNIA: not a power",
        "random prose line",
    ] + [f"TO ITALY: spam {i}" for i in range(10)])
    msgs = extract_messages(reply)
    assert ("ENGLAND", "Channel DMZ?") == msgs[0]
    assert ("ALL", "peace in our time") == msgs[1]
    assert all(r != "NARNIA" for r, _ in msgs)
    assert len(msgs) <= 4


# --------------------------------------------------------------------------- #
# End-to-end turn (stub transport, real CLIs)
# --------------------------------------------------------------------------- #
def _game_root(tmp_path):
    game = state.new_game("raw-test")
    state.save_game(game, tmp_path)
    state.save_config({"name": "raw-test", "press": "full", "powers": {}},
                      tmp_path)
    _, adj_pub = crypto.generate_keypair()
    state.pubkey_file(tmp_path).write_text(adj_pub, encoding="utf-8")
    return tmp_path


def _agent(tmp_path, replies):
    """RawChatAgent whose 'model' pops canned replies; records prompts."""
    spec = MatchSpec.load(None, name="raw-test")
    prompts = []

    def transport(url, headers, payload, timeout):
        prompts.append(payload["messages"][0]["content"])
        return {"choices": [{"message": {"content": replies.pop(0)}}]}

    agent = RawChatAgent("FRANCE", spec.seats["FRANCE"], REPO, tmp_path, spec,
                         transport=transport)
    return agent, prompts


def test_orders_turn_produces_sealed_artifact(tmp_path):
    root = _game_root(tmp_path)
    agent, prompts = _agent(root, ["```\nA PAR - BUR\nA MAR - SPA\nF BRE - MAO\n```"])
    result = agent.dispatch("You are FRANCE. It is S1901M.", kind="orders")
    assert result.ok, result.error
    assert state.power_orders_file(root, "FRANCE", "S1901M").exists()
    assert "FINAL orders" in prompts[0]          # format instruction attached


def test_incoherent_orders_get_one_corrective_retry(tmp_path):
    root = _game_root(tmp_path)
    agent, prompts = _agent(root, [
        "```\nA PAR S A MAR - BUR\nA MAR - SPA\nF BRE - MAO\n```",   # void support
        "```\nA PAR - BUR\nA MAR S A PAR - BUR\nF BRE - MAO\n```",   # fixed
    ])
    result = agent.dispatch("You are FRANCE. It is S1901M.", kind="orders")
    assert result.ok, result.error
    assert len(prompts) == 2
    assert "void support" in prompts[1]          # the error came back verbatim
    assert state.power_orders_file(root, "FRANCE", "S1901M").exists()


def test_negotiation_turn_seals_mail(tmp_path):
    root = _game_root(tmp_path)
    comms.claim_power(root, "ENGLAND")
    agent, _ = _agent(root, ["TO ENGLAND: Channel DMZ?\nTO ALL: hello world"])
    result = agent.dispatch("You are FRANCE. Negotiate.", kind="negotiation")
    assert result.ok, result.error
    # England can decrypt the DM through the normal inbox path.
    eng_priv = comms.load_privkey(root, "ENGLAND")
    bodies = [m["body"] for m in comms.read_inbox(root, "ENGLAND", eng_priv)]
    assert "Channel DMZ?" in bodies
    assert "hello world" in bodies               # broadcast reaches everyone


def test_make_agent_knows_raw_backend(tmp_path):
    spec = MatchSpec.load(None, name="t")
    agent = make_agent("raw", "FRANCE", spec.seats["FRANCE"], REPO, tmp_path, spec)
    assert isinstance(agent, RawChatAgent)
