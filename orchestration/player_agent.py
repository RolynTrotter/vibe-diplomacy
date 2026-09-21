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
import re
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
    #: The seat said it has nothing further to send or read this phase.
    final: bool = False

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "reply": self.reply,
            "session_id": self.session_id,
            "duration": self.duration,
            "error": self.error,
            "final": self.final,
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
#: Every reply uses one syntax, for everything a seat wants to say. Where a
#: line goes is decided in `parse_reply`, in code — so the model has no tool to
#: call, no file to write, and no routing decision it can get wrong.
_TO_SYNTAX = (
    "Write one line per thing you want to say:\n"
    "  `TO <POWER>: <message>`          sealed mail to that power\n"
    "  `TO <POWER>, <POWER>: <message>` the same message to several of them\n"
    "  `TO ALL: <message>`              say it to everyone\n"
    "  `TO SELF: <note>`                your own notebook. It survives the "
    "phase and you are shown it next turn. Anything you have agreed and mean "
    "to keep goes on a line beginning `DEAL:`.\n"
    "  `TO STAFF: <direction>`          what you want done this phase: what to "
    "take, what to hold, whom you are fighting. Plain English, places and "
    "aims — never unit orders; your staff places the units.\n"
    "`TO SELF` and `TO STAFF` each go on a line of their own. At most 4 "
    "messages to other powers; write `TO NOBODY: pass` to send none. Anything "
    "that is not a `TO ...` line is ignored.\n"
    "End with `FINAL_MESSAGES` on its own line if you have nothing further to "
    "send or read this phase."
)

MESSAGES_FORMAT = _TO_SYNTAX

# Messages and orders in one reply. The two formats do not collide — a `TO X:`
# line is never an order, and only the fenced block is read for orders — so one
# call can carry both, halving the model calls a full-press movement phase costs.
COMBINED_FORMAT = (
    _TO_SYNTAX
    + "\nThen, after those lines, give your FINAL orders in one fenced code "
      "block (```), one order per line in engine syntax (e.g. `A PAR - BUR`, "
      "`F BRE S A PAR - PIC`). They are binding — there is no later round."
)


# A seat whose orders are written by its staff (see `orchestration.staff`).
# The model is told it commands through subordinates and never writes an order;
# nothing here names the model that does, and nothing should.
DIRECTIVES_FORMAT = _TO_SYNTAX

SELF = "SELF"
STAFF = "STAFF"
NOBODY = "NOBODY"
#: A bare line meaning "nothing further to send or read this phase".
FINAL_MESSAGES = "FINAL_MESSAGES"

#: Diplomatic mail is capped so a seat cannot spend its whole turn writing
#: letters. SELF and STAFF are capped separately: sharing one budget would let
#: a chatty phase silently eat the power's own notes, which is the one thing it
#: cannot afford to lose.
MAIL_CAP = 4
NOTE_CAP = 12

_TO_RE = re.compile(r"^\s*TO\s+([A-Za-z][A-Za-z,\s]*?)\s*:\s*(.+)$")
_ORDER_RE = re.compile(r"^[AF] [A-Z]{3}\b")


@dataclass
class Reply:
    """One model reply, already routed.

    Every line a seat writes takes the same shape — `TO <TARGET>: <body>` — and
    the target decides where it lands: sealed mail, the power's own notebook,
    or its staff. The seat needs no tools and makes no routing decision; it
    writes sentences and this turns them into artifacts.
    """
    mail: list[tuple[list[str], str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    final: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def flat_mail(self) -> list[tuple[str, str]]:
        """(recipient, body) — one pair per recipient of each message."""
        return [(r, body) for targets, body in self.mail for r in targets]


def parse_reply(reply: str) -> Reply:
    """Route every `TO ...` line in a reply. One parser, every task kind.

    SELF and STAFF must each appear alone on a line. Their routing is not mail,
    so a line mixing them with a power is refused rather than guessed at —
    silently mailing a rival your private notes is the worst failure available
    here, and it should not be one bad regex away.

    An order-shaped line is dropped from SELF and STAFF. A seat that writes
    `A PAR - BUR` is doing its staff's job, and letting it through would put an
    unreviewed order into the notes.
    """
    out = Reply()
    for raw in reply.splitlines():
        line = raw.strip()
        if line.strip("*_` ").upper() == FINAL_MESSAGES:
            out.final = True
            continue
        match = _TO_RE.match(line)
        if not match:
            continue
        targets = [t for t in re.split(r"[,\s]+", match.group(1).upper()) if t]
        body = match.group(2).strip()
        if not body:
            continue

        private = [t for t in targets if t in (SELF, STAFF)]
        if private and len(targets) > 1:
            out.errors.append(
                f"`TO {match.group(1).strip()}:` mixes {private[0]} with another "
                f"target; {private[0]} must be on a line of its own.")
            continue
        if private:
            if _ORDER_RE.match(body.upper()):
                continue
            bucket = out.notes if private[0] == SELF else out.directions
            if len(bucket) < NOTE_CAP:
                bucket.append(body)
            continue
        if NOBODY in targets:
            continue
        good = [t for t in targets if t in POWERS or t == "ALL"]
        unknown = [t for t in targets if t not in POWERS and t != "ALL"]
        if unknown:
            out.errors.append(f"unknown recipient(s): {', '.join(unknown)}")
        if good and len(out.mail) < MAIL_CAP:
            out.mail.append((["ALL"] if "ALL" in good else good, body))
    return out


def extract_orders(reply: str) -> list[str]:
    """Orders from the last fenced code block (or bare `A/F ...` lines)."""
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", reply, flags=re.DOTALL)
    text = blocks[-1] if blocks else reply
    orders = []
    for line in text.splitlines():
        line = line.split("#")[0].strip().strip("`")
        if re.match(r"^[AF] [A-Z]{3}", line.upper()):
            orders.append(line)
    return orders


def extract_messages(reply: str) -> list[tuple[str, str]]:
    """(recipient, body) pairs — the name every existing caller already uses."""
    return parse_reply(reply).flat_mail


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
            elif kind == "directives":
                result = self._directives(task)
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
        from orchestration import staff

        prompt = f"{task}\n\n{COMBINED_FORMAT}"
        reply = self._complete(prompt)
        parsed = parse_reply(reply)
        sent, errors = self._send_all(parsed.mail)
        if parsed.notes:
            staff.save_notes(self.game_root, self.power, parsed.notes)

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

    def _directives(self, task: str) -> AgentResult:
        """Send this phase's mail, then hand the staff its directions.

        One model call for the whole phase, and it is spent entirely on
        language: what to say, and what the power wants. The order writing is
        not a decision this model makes or is told about, so there is no tool
        choice to get wrong and no retry loop to pay for — an illegal order is
        impossible by construction on the other side of this handoff.
        """
        from orchestration import staff

        prompt = f"{task}\n\n{DIRECTIVES_FORMAT}"
        reply = self._complete(prompt)
        parsed = parse_reply(reply)
        sent, errors = self._send_all(parsed.mail)
        result = staff.write_and_submit(self.game_root, self.power,
                                        parsed.directions, notes=parsed.notes,
                                        repo=self.repo_root)
        return AgentResult(
            reply=reply, ok=result.ok and not errors,
            error="; ".join(filter(None, [result.error, *errors,
                                          *parsed.errors]))[:500] or None,
            final=parsed.final,
            transcript={"reply": reply, "sent": sent,
                        "directions": parsed.directions, "notes": parsed.notes,
                        "orders": result.orders, "issues": result.issues,
                        "usage": result.usage})

    def _send_all(self, messages) -> tuple[list, list]:
        """Drive parsed mail through the real send CLI.

        Accepts either `Reply.mail` (recipient *lists*) or the flat
        `(recipient, body)` pairs older callers pass. A multi-recipient line
        becomes ONE call — `send_message --to` is already variadic — so one
        body addressed to three powers costs one invocation, not three.
        """
        sent, errors = [], []
        for targets, body in messages:
            targets = [targets] if isinstance(targets, str) else list(targets)
            targets = [t for t in targets if t != NOBODY]
            if not targets:
                continue
            proc = self._run_cli("orchestration.send_message",
                                 ["--power", self.power, "--to", *targets],
                                 stdin=body)
            (sent if proc.returncode == 0 else errors).append(
                f"{', '.join(targets)}: {body[:80]}")
        return sent, errors

    def _negotiate(self, task: str) -> AgentResult:
        """Send this round's mail, and keep any notes the seat wrote itself.

        A negotiation round can produce `TO SELF:` lines — a power works out
        what it thinks during the talking, not after it — so they are saved
        here rather than waiting for an orders call that may never come.
        """
        from orchestration import staff

        prompt = f"{task}\n\n{MESSAGES_FORMAT}"
        reply = self._complete(prompt)
        parsed = parse_reply(reply)
        sent, errors = self._send_all(parsed.mail)
        if parsed.notes:
            staff.save_notes(self.game_root, self.power, parsed.notes)
        return AgentResult(
            reply=reply, ok=not errors,
            error="; ".join(errors + parsed.errors)[:500] or None,
            final=parsed.final,
            transcript={"reply": reply, "sent": sent, "notes": parsed.notes,
                        "failed": errors})


class FakeAgent(PlayerAgent):
    """Deterministic, server-free backend used in tests and `--dry-run` smoke.

    It ignores the natural-language task entirely and instead does what a real
    player would do through the same CLIs: claim its seat, then (on an orders
    task) submit a random pick of legal orders. Negotiation tasks are a no-op.
    It cannot hold an `orders: staff` seat: the staff is a real model, and a
    stand-in for it would report a pipeline this backend never ran.
    """

    def dispatch(self, task: str, kind: str = "orders") -> AgentResult:
        start = time.monotonic()
        self._ensure_seat()
        if kind == "negotiation":
            return AgentResult(reply="(fake: no negotiation)", ok=True,
                               duration=time.monotonic() - start)
        if kind == "directives":
            # No stand-in here on purpose. A staff seat's orders come from the
            # real order writer, and faking that would make this backend report
            # a working staff pipeline it never exercised.
            return AgentResult(
                reply="", ok=False, duration=time.monotonic() - start,
                error="the fake backend cannot hold an `orders: staff` seat — "
                      "the staff is a real model; use --backend raw or headless")
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
    "COMBINED_FORMAT", "DIRECTIVES_FORMAT", "MESSAGES_FORMAT", "ORDERS_FORMAT",
    "extract_directives",
    "FakeAgent", "make_agent", "_player_env",
    "extract_orders", "extract_messages",
]
