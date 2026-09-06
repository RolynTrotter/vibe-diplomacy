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


ORDERS_FORMAT = (
    "Reply with your FINAL orders in one fenced code block (```), one order "
    "per line, engine syntax (e.g. `A PAR - BUR`, `F BRE S A PAR - PIC`). "
    "Only the fenced block is read — no commands, no tools, no prose inside it."
)
MESSAGES_FORMAT = (
    "Reply with the messages you want to send (at most 4), one per line, as\n"
    "`TO <POWER>: <message>` or `TO ALL: <message>`.\n"
    "Lines in any other format are ignored. Reply `TO NOBODY: pass` to stay "
    "silent."
)
# Messages and orders in one reply. The two formats do not collide — a `TO X:`
# line is never an order, and only the fenced block is read for orders — so one
# call can carry both, halving the model calls a full-press movement phase costs.
COMBINED_FORMAT = (
    "Reply with BOTH, in this order:\n"
    "1. Your messages (at most 4), one per line, as `TO <POWER>: <message>` or "
    "`TO ALL: <message>`. Write `TO NOBODY: pass` to send none.\n"
    "2. Then your FINAL orders in one fenced code block (```), one order per "
    "line, engine syntax (e.g. `A PAR - BUR`, `F BRE S A PAR - PIC`).\n"
    "Only `TO ...` lines and the fenced block are read; prose between them is "
    "ignored. The orders are binding — there is no later round."
)


def extract_orders(reply: str) -> list[str]:
    """Orders from the last fenced code block (or bare `A/F ...` lines)."""
    import re
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", reply, flags=re.DOTALL)
    text = blocks[-1] if blocks else reply
    orders = []
    for line in text.splitlines():
        line = line.split("#")[0].strip().strip("`")
        if re.match(r"^[AF] [A-Z]{3}", line.upper()):
            orders.append(line)
    return orders


def extract_messages(reply: str) -> list[tuple[str, str]]:
    """(recipient, body) pairs from `TO <POWER>: ...` lines."""
    import re
    out = []
    for line in reply.splitlines():
        m = re.match(r"^\s*TO\s+([A-Za-z]+)\s*:\s*(.+)$", line.strip())
        if not m:
            continue
        recipient, body = m.group(1).upper(), m.group(2).strip()
        if recipient in POWERS or recipient == "ALL":
            out.append((recipient, body))
    return out[:4]


def _default_transport(url: str, headers: dict, payload: dict,
                       timeout: float) -> dict:
    """POST JSON, return parsed JSON. Kept tiny + injectable for tests."""
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class RawChatAgent(PlayerAgent):
    """One direct chat-completion call per turn — no agentic loop, no tools.

    This is the cheap seat for weak local models: the task (which embeds the
    full brief plus the engine-verified tactical annex) goes up as a single
    user message; the reply is parsed for a fenced orders block (or `TO X:`
    message lines) and driven through the SAME join/submit/send CLIs the
    skills use, so the artifacts stay byte-identical to a distrusting game.

    `local` seats hit the OpenAI-compatible `/v1/chat/completions` (LM Studio);
    `api` seats hit Anthropic `/v1/messages` with the ambient `ANTHROPIC_API_KEY`.
    On a validation/coherence rejection the model gets ONE retry with the
    error text appended.
    """

    max_tokens = 2000

    def __init__(self, power, seat, repo_root, game_root, spec, transport=None):
        super().__init__(power, seat, repo_root, game_root, spec)
        self.transport = transport or _default_transport

    # ------------------------------------------------------------------ #
    # Model call
    # ------------------------------------------------------------------ #
    def _board_image(self):
        """The current phase's board picture, or None if there isn't one.

        The brief already rendered and cached it, so this is a lookup in the
        common case. Seats can opt out with `vision: false` (a text-only
        model would just reject the content block).
        """
        if not self.seat.vision:
            return None
        try:
            from engine import mapviz, state
            return mapviz.phase_image(self.game_root,
                                      state.load_game(self.game_root))
        except Exception:
            return None

    def _content(self, prompt: str, image) -> object:
        """The user message body: plain text, or text plus the board image.

        The two endpoints spell an inline image differently — OpenAI-compatible
        servers (LM Studio) take a data URI in an `image_url` part, Anthropic
        takes base64 in an `image` block. Image first in both: a model reads
        the instructions better with the picture already in view.
        """
        if image is None:
            return prompt
        from engine import mapviz
        if self.seat.endpoint == "local":
            return [{"type": "image_url",
                     "image_url": {"url": mapviz.image_data_uri(image)}},
                    {"type": "text", "text": prompt}]
        import base64
        return [{"type": "image",
                 "source": {"type": "base64", "media_type": "image/png",
                            "data": base64.b64encode(
                                Path(image).read_bytes()).decode("ascii")}},
                {"type": "text", "text": prompt}]

    def _complete(self, prompt: str) -> str:
        """One completion, with the board picture attached when we have one.

        A model that can't take images fails the whole call, so a request that
        carried one is retried as plain text before giving up — losing the
        picture beats losing the turn.
        """
        image = self._board_image()
        try:
            return self._post(self._content(prompt, image))
        except Exception:
            if image is None:
                raise
            return self._post(prompt)

    def _post(self, content: object) -> str:
        if self.seat.endpoint == "local":
            url = f"{(self.seat.base_url or '').rstrip('/')}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.seat.token or ''}"}
            payload = {"model": self.seat.model,
                       "messages": [{"role": "user", "content": content}],
                       "max_tokens": self.max_tokens}
            data = self.transport(url, headers, payload,
                                  self.spec.per_call_timeout_s)
            return data["choices"][0]["message"]["content"]
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                   "anthropic-version": "2023-06-01"}
        payload = {"model": self.seat.model, "max_tokens": self.max_tokens,
                   "messages": [{"role": "user", "content": content}]}
        data = self.transport(url, headers, payload,
                              self.spec.per_call_timeout_s)
        return "".join(b.get("text", "") for b in data.get("content", []))

    # ------------------------------------------------------------------ #
    # Turn logic
    # ------------------------------------------------------------------ #
    def dispatch(self, task: str, kind: str = "orders") -> AgentResult:
        start = time.monotonic()
        try:
            self._ensure_seat()
            if kind == "negotiation":
                result = self._negotiate(task)
            elif kind == "combined":
                result = self._combined(task)
            else:
                result = self._orders(task)
        except Exception as exc:  # transport/HTTP/parse failures
            result = AgentResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        result.duration = time.monotonic() - start
        return result

    def _ensure_seat(self) -> None:
        from engine import comms
        if self.power not in comms.list_players(self.game_root):
            self._run_cli("orchestration.join_game", ["--power", self.power])

    def _orders(self, task: str) -> AgentResult:
        prompt = f"{task}\n\n{ORDERS_FORMAT}"
        transcript = []
        for attempt in range(2):
            reply = self._complete(prompt)
            transcript.append(reply)
            orders = extract_orders(reply)
            if not orders:
                error = "reply contained no parseable orders"
            else:
                proc = self._run_cli("orchestration.submit_orders",
                                     ["--power", self.power],
                                     stdin="\n".join(orders))
                if proc.returncode == 0:
                    return AgentResult(reply=reply, ok=True,
                                       transcript={"attempts": transcript,
                                                   "orders": orders,
                                                   "stdout": proc.stdout})
                error = proc.stderr.strip()
            if attempt == 0:
                prompt += (f"\n\nYour previous reply was rejected:\n{error}\n"
                           f"Fix the problem and reply again — same format.")
        return AgentResult(reply=transcript[-1], ok=False, error=error[:500],
                           transcript={"attempts": transcript})

    def _combined(self, task: str) -> AgentResult:
        """One call that both sends this phase's mail and submits its orders.

        The messages go out first — they are what the orders were agreed
        against — and a rejected order set still gets its single corrective
        retry, asking only for the orders back so the mail is never sent twice.
        """
        prompt = f"{task}\n\n{COMBINED_FORMAT}"
        reply = self._complete(prompt)
        sent, errors = self._send_all(extract_messages(reply))

        orders = extract_orders(reply)
        error = None
        for attempt in range(2):
            if orders:
                proc = self._run_cli("orchestration.submit_orders",
                                     ["--power", self.power],
                                     stdin="\n".join(orders))
                if proc.returncode == 0:
                    return AgentResult(reply=reply, ok=not errors,
                                       error="; ".join(errors)[:500] or None,
                                       transcript={"reply": reply, "sent": sent,
                                                   "orders": orders,
                                                   "stdout": proc.stdout})
                error = proc.stderr.strip()
            else:
                error = "reply contained no parseable orders"
            if attempt == 0:
                retry = (f"{prompt}\n\nYour messages were sent. Your ORDERS were "
                         f"rejected:\n{error}\nReply with corrected orders only, "
                         "in one fenced block.")
                orders = extract_orders(self._complete(retry))
        return AgentResult(reply=reply, ok=False, error=(error or "")[:500],
                           transcript={"reply": reply, "sent": sent})

    def _send_all(self, messages) -> tuple[list, list]:
        """Drive parsed `TO X: ...` pairs through the real send CLI."""
        sent, errors = [], []
        for recipient, body in messages:
            if recipient == "NOBODY":
                continue
            proc = self._run_cli("orchestration.send_message",
                                 ["--power", self.power, "--to", recipient],
                                 stdin=body)
            (sent if proc.returncode == 0 else errors).append(
                f"{recipient}: {body[:80]}")
        return sent, errors

    def _negotiate(self, task: str) -> AgentResult:
        prompt = f"{task}\n\n{MESSAGES_FORMAT}"
        reply = self._complete(prompt)
        sent, errors = self._send_all(extract_messages(reply))
        return AgentResult(
            reply=reply, ok=not errors,
            error="; ".join(errors)[:500] or None,
            transcript={"reply": reply, "sent": sent, "failed": errors})


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
        # Random per-location picks are naturally incoherent (void supports,
        # unmatched convoys) — that's fine here, the point is exercising the
        # sealed/signed pipeline, so skip the coherence gate.
        proc = self._run_cli("orchestration.submit_orders",
                             ["--power", self.power, "--no-coherence"],
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
    """Factory: `headless` (default), `raw` (one completion, no tools), `fake`."""
    cls = {"headless": HeadlessClaudeAgent, "raw": RawChatAgent,
           "fake": FakeAgent}.get(backend)
    if cls is None:
        raise ValueError(f"Unknown player backend: {backend!r}")
    return cls(power, seat, repo_root, game_root, spec)


__all__ = [
    "AgentResult", "PlayerAgent", "HeadlessClaudeAgent", "RawChatAgent",
    "COMBINED_FORMAT", "MESSAGES_FORMAT", "ORDERS_FORMAT",
    "FakeAgent", "make_agent", "_player_env",
    "extract_orders", "extract_messages",
]
