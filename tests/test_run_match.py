"""Programmatic conductor (Epic: run_match).

All tests run WITHOUT LM Studio or any model server: the `fake` backend submits
heuristic/curated orders through the real CLIs, so the whole conductor loop is
deterministic and CI-safe. We assert the produced artifacts are the same shape a
distrusting seven-session game (or scripts/self_play.py) yields.
"""
import json
import os
from pathlib import Path

from orchestration.match_spec import MatchSpec, SeatSpec, resolve_lm_studio
from orchestration.player_agent import FakeAgent, HeadlessClaudeAgent, _player_env
from orchestration.run_match import Conductor, build_parser, main, _parse_seat_overrides

from engine import state

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Spec resolution
# --------------------------------------------------------------------------- #
def test_spec_defaults_populate_all_seats():
    spec = MatchSpec.load(None, name="t")
    assert set(spec.seats) == {"AUSTRIA", "ENGLAND", "FRANCE", "GERMANY",
                               "ITALY", "RUSSIA", "TURKEY"}
    # local seats get a resolved endpoint; api seats don't.
    assert all(s.base_url for s in spec.seats.values())


def test_spec_overrides_beat_yaml(tmp_path):
    yaml_path = tmp_path / "m.yaml"
    yaml_path.write_text("name: fromfile\npress: full\nnegotiation_rounds: 5\n")
    spec = MatchSpec.load(yaml_path, press="none")  # CLI override
    assert spec.name == "fromfile"
    assert spec.press == "none"               # override won
    assert spec.negotiation_rounds == 5       # untouched by override


def test_seat_overrides_and_endpoint_resolution():
    spec = MatchSpec.load(None, name="t", seats={
        "GERMANY": {"model": "claude-opus-4-8", "endpoint": "api"},
        "ITALY": {"enabled": False},
    })
    assert spec.seats["GERMANY"].endpoint == "api"
    assert spec.seats["GERMANY"].base_url is None      # api: no base-url override
    assert spec.seats["FRANCE"].base_url               # local: resolved
    assert "ITALY" in spec.idle_powers()
    assert "ITALY" not in spec.live_powers()


def test_parse_seat_override_cli():
    out = _parse_seat_overrides(["FRANCE.persona=cautious", "ITALY.enabled=false"])
    assert out["FRANCE"]["persona"] == "cautious"
    assert out["ITALY"]["enabled"] is False


# --------------------------------------------------------------------------- #
# Secrets isolation / env scrubbing  (the headline security property)
# --------------------------------------------------------------------------- #
def test_player_env_never_carries_adjudicator_key(monkeypatch):
    monkeypatch.setenv("ADJUDICATOR_PRIVATE_KEY", "TOPSECRET")
    local = SeatSpec(endpoint="local", base_url="http://host:1234", token="tok")
    api = SeatSpec(endpoint="api")

    env_local = _player_env(local)
    assert "ADJUDICATOR_PRIVATE_KEY" not in env_local
    assert env_local["ANTHROPIC_BASE_URL"] == "http://host:1234"
    assert env_local["ANTHROPIC_AUTH_TOKEN"] == "tok"

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://leak")
    env_api = _player_env(api)
    assert "ADJUDICATOR_PRIVATE_KEY" not in env_api
    # api seats must NOT inherit a base-url override.
    assert "ANTHROPIC_BASE_URL" not in env_api
    assert "ANTHROPIC_AUTH_TOKEN" not in env_api


def test_lm_studio_resolution_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("LM_STUDIO_HOST", raising=False)
    monkeypatch.delenv("LM_API_TOKEN", raising=False)
    host, token = resolve_lm_studio(env_file=str(tmp_path / "missing.env"))
    assert host.startswith("http")
    assert token


# --------------------------------------------------------------------------- #
# print-plan / dry-run dispatch nothing
# --------------------------------------------------------------------------- #
def test_print_plan_runs_nothing(tmp_path, capsys):
    rc = main(["--name", "pp", "--print-plan", "--root", str(tmp_path)])
    assert rc == 0
    # No game was initialized.
    assert not state.config_file(tmp_path).exists()
    assert "name: pp" in capsys.readouterr().out


def test_dry_run_dispatches_nothing(tmp_path):
    spec = MatchSpec.load(None, name="dr", dry_run=True)
    conductor = Conductor(spec, REPO, game_root=tmp_path, backend="fake")
    result = conductor.run()
    assert result["dry_run"] is True
    assert result["intended"]                    # planned dispatches listed
    assert not state.config_file(tmp_path).exists()   # nothing initialized


# --------------------------------------------------------------------------- #
# Full short match with the FakeAgent reaches done / max_phases
# --------------------------------------------------------------------------- #
def test_full_fake_match_produces_valid_artifacts(tmp_path):
    spec = MatchSpec.load(None, name="proving", press="none", max_phases=4,
                          verbosity=0, seed_openings=True)
    conductor = Conductor(spec, REPO, game_root=tmp_path, backend="fake")
    summary = conductor.run()

    # The game advanced past the opening and we have real standings.
    assert summary["phases"], "no phases were played"
    assert summary["final"]
    total_centers = sum(p["centers"] for p in summary["final"].values())
    # 22 home/owned centers at the start; neutrals get claimed over time, never
    # exceeding the board's 34 supply centers.
    assert 22 <= total_centers <= 34

    # Artifacts: sealed orders were produced, history was revealed, players claimed.
    assert (tmp_path / "history" / "S1901M.json").exists()
    assert (tmp_path / "players" / "FRANCE.json").exists()
    # The consumed sealed-order file is removed after adjudication (same as
    # run_adjudication in a distrusting game).
    assert not (tmp_path / "orders" / "FRANCE" / "S1901M.enc").exists()

    # Transcript shape.
    summ = json.loads((tmp_path / "runs" / "proving" / "summary.json").read_text())
    assert summ["final"] == summary["final"]
    france_tr = tmp_path / "runs" / "proving" / "S1901M" / "FRANCE.json"
    assert france_tr.exists()
    assert json.loads(france_tr.read_text())["ok"] is True


def test_idle_power_never_plays(tmp_path):
    spec = MatchSpec.load(None, name="idlegame", press="none", max_phases=2,
                          verbosity=0, idle=["ITALY"])
    conductor = Conductor(spec, REPO, game_root=tmp_path, backend="fake")
    conductor.run()
    # Idle Italy never claims a seat.
    assert not (tmp_path / "players" / "ITALY.json").exists()
    assert (tmp_path / "players" / "FRANCE.json").exists()


# --------------------------------------------------------------------------- #
# CLI surface mirrors the spec
# --------------------------------------------------------------------------- #
def test_cli_flags_map_to_spec_fields():
    args = build_parser().parse_args(
        ["--name", "x", "--press", "full", "--rounds", "3",
         "--session-mode", "persistent", "--max-concurrency", "2",
         "--seat", "FRANCE.persona=bold"])
    assert args.negotiation_rounds == 3
    assert args.session_mode == "persistent"
    assert args.max_concurrency == 2
    assert args.seat == ["FRANCE.persona=bold"]
