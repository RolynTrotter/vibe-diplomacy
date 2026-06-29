"""Player-agent backends — how the conductor runs one power's turn.

The conductor never plays a power itself; it hands a task to a `PlayerAgent`
and collects the result. The default backend launches a **separate headless
Claude Code process** (`claude -p`) per seat, which is the only way to give each
power its own model/provider: `ANTHROPIC_BASE_URL` is session-wide, so a real
per-power Qwen needs a real per-process env.

Two properties this module guarantees:

* **Secrets isolation.** A player process NEVER receives
  `ADJUDICATOR_PRIVATE_KEY`. `_player_env` scrubs it and routes `local` seats to
  LM Studio / `api` seats to the ambient Anthropic credentials.
* **Pluggability.** `FakeAgent` ignores the prompt and submits random legal
  orders through the real CLIs, making the whole conductor loop runnable in CI
  with no model server. A future raw `/v1/messages` backend can slot in the same
  way.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestration._common import POWERS  # noqa: F401  (re-exported convenience)
from orchestration.match_spec import MatchSpec, SeatSpec


@dataclass
class AgentResult:
    reply: str = ""
    transcript: object = None          # raw backend payload (dict or text)
    session_id: str | None = None
    ok: bool = True
    duration: float = 0.0
    error: str | None = None

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "reply": self.reply,
            "session_id": self.session_id,
            "duration": self.duration,
            "error": self.error,
            "transcript": self.transcript,
        }


def _player_env(seat: SeatSpec) -> dict[str, str]:
    """The scrubbed, per-seat environment handed to a player process.

    Always drops the adjudicator key. Routes `local` seats to their LM Studio
    endpoint and `api` seats to the ambient Anthropic credentials.
    """
    env = dict(os.environ)
    # Secrets isolation: a player must never see the adjudicator private key.
    env.pop("ADJUDICATOR_PRIVATE_KEY", None)
    env["CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING"] = "1"
    env["CLAUDE_CODE_ATTRIBUTION_HEADER"] = "0"

    if seat.endpoint == "local":
        env["ANTHROPIC_BASE_URL"] = seat.base_url or ""
        env["ANTHROPIC_AUTH_TOKEN"] = seat.token or ""
    else:  # api: use the subscription/Anthropic credentials, no base-url override
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


class PlayerAgent:
    """One power's turn-taker. Subclasses implement `dispatch`."""

    def __init__(self, power: str, seat: SeatSpec, repo_root: Path,
                 game_root: Path, spec: MatchSpec):
        self.power = power.upper()
        self.seat = seat
        self.repo_root = Path(repo_root)
        self.game_root = Path(game_root)
        self.spec = spec
        self.session_id: str | None = None

    def dispatch(self, task: str, kind: str = "orders") -> AgentResult:
        raise NotImplementedError

    # Shared helper for backends that shell out to the real CLIs.
    def _run_cli(self, module: str, args: list[str], stdin: str | None = None,
                 env: dict | None = None) -> subprocess.CompletedProcess:
        import sys
        return subprocess.run(
            [sys.executable, "-m", module, "--root", str(self.game_root), *args],
            cwd=self.repo_root, input=stdin, text=True, capture_output=True,
            env=env if env is not None else _player_env(self.seat),
        )


class HeadlessClaudeAgent(PlayerAgent):
    """Runs `claude -p` as an independent, supervised subprocess per call.

    This is the programmatic, supervised equivalent of setup_lm_studio/ask-local:
    a scrubbed per-seat env, JSON output so we can capture `session_id` for
    `persistent` mode, plus timeout + retry handling.
    """

    def dispatch(self, task: str, kind: str = "orders") -> AgentResult:
        argv = [
            "claude", "-p",
            "--model", self.seat.model,
            "--dangerously-skip-permissions",
            "--output-format", "json",
        ]
        if self.spec.session_mode == "persistent" and self.session_id:
            argv += ["--resume", self.session_id]

        env = _player_env(self.seat)
        last_err = None
        for attempt in range(self.spec.retries + 1):
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    argv, cwd=self.repo_root, input=task, text=True,
                    capture_output=True, env=env,
                    timeout=self.spec.per_call_timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                last_err = f"timeout after {self.spec.per_call_timeout_s}s"
                if attempt < self.spec.retries:
                    continue
                return AgentResult(ok=False, error=last_err,
                                   duration=time.monotonic() - start,
                                   transcript=str(exc))
            duration = time.monotonic() - start

            if proc.returncode != 0:
                last_err = f"exit {proc.returncode}: {proc.stderr.strip()[:500]}"
                if attempt < self.spec.retries:
                    continue
                return AgentResult(ok=False, error=last_err, duration=duration,
                                   transcript=proc.stdout or proc.stderr)

            reply, session_id, payload = self._parse_output(proc.stdout)
            if self.spec.session_mode == "persistent" and session_id:
                self.session_id = session_id
            return AgentResult(reply=reply, transcript=payload,
                               session_id=session_id, ok=True, duration=duration)

        return AgentResult(ok=False, error=last_err or "unknown failure")

    @staticmethod
    def _parse_output(stdout: str) -> tuple[str, str | None, object]:
        """Pull (reply, session_id, raw) from `--output-format json` output."""
        text = stdout.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text, None, text
        if isinstance(payload, dict):
            reply = payload.get("result") or payload.get("response") or ""
            return reply, payload.get("session_id"), payload
        return text, None, payload


class FakeAgent(PlayerAgent):
    """Deterministic, server-free backend used in tests and `--dry-run` smoke.

    It ignores the natural-language task entirely and instead does what a real
    player would do through the same CLIs: claim its seat, then (on an orders
    task) submit a random pick of legal orders. Negotiation tasks are a no-op.
    """

    def dispatch(self, task: str, kind: str = "orders") -> AgentResult:
        start = time.monotonic()
        self._ensure_seat()
        if kind == "negotiation":
            return AgentResult(reply="(fake: no negotiation)", ok=True,
                               duration=time.monotonic() - start)
        orders = self._orders()
        if not orders:
            return AgentResult(reply="(fake: no orders this phase)", ok=True,
                               duration=time.monotonic() - start)
        proc = self._run_cli("orchestration.submit_orders", ["--power", self.power],
                             stdin="\n".join(orders))
        ok = proc.returncode == 0
        return AgentResult(
            reply=proc.stdout.strip(),
            transcript={"orders": orders, "stdout": proc.stdout, "stderr": proc.stderr},
            ok=ok,
            duration=time.monotonic() - start,
            error=None if ok else proc.stderr.strip()[:500],
        )

    def _ensure_seat(self) -> None:
        from engine import comms
        if self.power in comms.list_players(self.game_root):
            return
        self._run_cli("orchestration.join_game", ["--power", self.power])

    def _orders(self) -> list[str]:
        """One random legal order per orderable location.

        No strategy whatsoever — this exists only to drive real sealed/signed
        orders through the pipeline in tests. The RNG is seeded from the phase
        and power so a run is reproducible.
        """
        from engine import state
        game = state.load_game(self.game_root)
        phase = game.get_current_phase()
        possible = game.get_all_possible_orders()
        rng = random.Random(f"{phase}:{self.power}")
        orders = []
        for loc in game.get_orderable_locations(self.power):
            choices = possible.get(loc) or []
            if choices:
                orders.append(rng.choice(choices))
        return orders


def make_agent(backend: str, power: str, seat: SeatSpec, repo_root: Path,
               game_root: Path, spec: MatchSpec) -> PlayerAgent:
    """Factory: `headless` (default) or `fake`."""
    cls = {"headless": HeadlessClaudeAgent, "fake": FakeAgent}.get(backend)
    if cls is None:
        raise ValueError(f"Unknown player backend: {backend!r}")
    return cls(power, seat, repo_root, game_root, spec)


__all__ = [
    "AgentResult", "PlayerAgent", "HeadlessClaudeAgent", "FakeAgent",
    "make_agent", "_player_env",
]
