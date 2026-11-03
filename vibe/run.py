"""`./dip run` — play some or all seats of a match with models.

Each model seat is one stateless call per decision: the prompt is the seat's
board (plus inbox and its own notes), the reply is free text that we parse.
A seat makes no tool calls and sees no part of this harness. Seats marked
`agent` are left alone: an outside agent plays them through `./dip submit`,
and the phase resolves once they are in, so the two kinds mix freely.

Seat specs (`--seat FRANCE=<spec>`, or `--model` for every unassigned seat):
    <model>                   an OpenAI-compatible model at --base-url
    openai:<model>[@<url>]    the same, with its own URL
    claude:<model>            the `claude` CLI, no tools (uses your login)
    agent                     played from outside by an agent or a human
    fake                      random legal orders (smoke tests)
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from vibe import board as boardmod
from vibe import mapviz
from vibe.game import ALL, POWERS, ROOT, LateOrders, Match, check_orders

FINAL_ROUND_NOTE = "Orders are due now."
SLOW_HINT = ("model too slow: try --reasoning-effort low, a lower --concurrency, "
             "or a higher --timeout")


# --------------------------------------------------------------------------- #
# Seats and backends
# --------------------------------------------------------------------------- #
class ServerError(RuntimeError):
    """The endpoint answered, with an error. Retrying the same call won't help."""


@dataclass
class Seat:
    kind: str                       # openai | claude | agent | fake
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    reasoning_effort: str = ""      # sent only if set; not every server knows it

    @property
    def endpoint(self) -> str:
        return self.base_url if self.kind == "openai" else self.kind

    def label(self) -> str:
        return self.model or self.kind


def parse_seat(spec: str, base_url: str, api_key: str) -> Seat:
    spec = spec.strip()
    if spec in ("agent", "fake"):
        return Seat(spec)
    if spec.startswith("claude:"):
        return Seat("claude", spec.split(":", 1)[1])
    if spec.startswith("openai:"):
        spec = spec.split(":", 1)[1]
    model, _, url = spec.partition("@")
    url = url or base_url
    if not url:
        raise SystemExit(f"seat {spec!r} needs --base-url (or openai:{model}@<url>)")
    return Seat("openai", model, url.rstrip("/"), api_key)


def _post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        # The server's own explanation ("model not loaded", "context too
        # long") is the useful part; a bare "400 Bad Request" is not.
        body = exc.read().decode(errors="replace")
        try:
            body = json.loads(body).get("error", body)
            body = body.get("message", body) if isinstance(body, dict) else body
        except (ValueError, AttributeError):
            pass
        raise ServerError(f"HTTP {exc.code}: {str(body)[:300]}") from None


def _stream(url: str, headers: dict, payload: dict, timeout: float,
            limit: float = 3600) -> dict:
    """POST a streaming chat completion; return it shaped like a plain one.

    `timeout` is how long the server may go without sending anything, so a
    slow model that is still writing is never cut off. `limit` caps the whole
    call; if it is hit, whatever arrived so far is returned. Servers that
    ignore `stream` and answer with plain JSON work too.
    """
    req = urllib.request.Request(url, data=json.dumps({**payload, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    start = time.monotonic()
    content, reasoning = [], []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if "event-stream" not in (resp.headers.get("Content-Type") or ""):
                return json.loads(resp.read().decode())
            for raw in resp:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
                except ValueError:
                    continue
                content.append(delta.get("content") or "")
                reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
                if time.monotonic() - start > limit:
                    break
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            body = json.loads(body).get("error", body)
            body = body.get("message", body) if isinstance(body, dict) else body
        except (ValueError, AttributeError):
            pass
        raise ServerError(f"HTTP {exc.code}: {str(body)[:300]}") from None
    except TimeoutError:
        raise TimeoutError(f"no tokens for {timeout:.0f}s") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError(f"no answer for {timeout:.0f}s") from None
        raise
    return {"choices": [{"message": {"content": "".join(content),
                                     "reasoning_content": "".join(reasoning)}}]}


def check_endpoint(seat: Seat, timeout: float = 180) -> tuple[bool, str]:
    """One line saying whether `seat`'s server will actually answer.

    Lists the models, then makes a one-token call, which also makes a server
    like LM Studio load the model now and report it if it can't.
    """
    where = f"{seat.model} @ {seat.base_url}"
    headers = {"Authorization": f"Bearer {seat.api_key}"} if seat.api_key else {}
    try:
        req = urllib.request.Request(f"{seat.base_url}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            ids = [m.get("id") for m in json.loads(resp.read().decode()).get("data", [])]
    except urllib.error.HTTPError:
        ids = []                    # some servers don't list models; try the call
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"endpoint DOWN: nothing answering at {seat.base_url} ({exc})"
    if ids and seat.model not in ids:
        return False, (f"endpoint UP at {seat.base_url}, but it has no model "
                       f"{seat.model!r}. It serves: {', '.join(map(str, ids))}")
    try:
        _post(f"{seat.base_url}/chat/completions", headers,
              {"model": seat.model, "max_tokens": 1,
               "messages": [{"role": "user", "content": "Say OK."}]}, timeout)
    except ServerError as exc:
        return False, f"endpoint ERROR for {where}: {exc}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"endpoint ERROR for {where}: {exc}"
    return True, f"endpoint OK: {where}"


def call_openai(seat: Seat, system: str, prompt: str, image: str | None,
                max_tokens: int, timeout: float, transport=_stream) -> str:
    content: object = prompt
    if image:
        content = [{"type": "image_url", "image_url": {"url": mapviz.image_data_uri(image)}},
                   {"type": "text", "text": prompt}]
    payload = {"model": seat.model, "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": content}]}
    if seat.reasoning_effort:
        payload["reasoning_effort"] = seat.reasoning_effort
    headers = {"Authorization": f"Bearer {seat.api_key}"} if seat.api_key else {}
    data = transport(f"{seat.base_url}/chat/completions", headers, payload, timeout)
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content") or ""
    # Reasoning models may put everything in a separate field, or leave the
    # answer empty after thinking; the reasoning is still worth parsing.
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    if reasoning and not text.strip():
        return reasoning
    return text


def call_claude(seat: Seat, system: str, prompt: str, image: str | None,
                max_tokens: int, timeout: float) -> str:
    with tempfile.TemporaryDirectory() as empty:
        cmd = ["claude", "-p", "--tools", "", "--no-session-persistence",
               "--system-prompt", system]
        if seat.model:
            cmd += ["--model", seat.model]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              cwd=empty, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or "claude exited non-zero")
    return proc.stdout


def fake_reply(match: Match, power: str, rng: random.Random) -> str:
    """Random legal orders, in the same shape a model would write them."""
    game = match.load()
    possible = game.get_all_possible_orders()
    locs = game.get_orderable_locations(power)
    orders = []
    if game.phase_type == "A":
        n = len(game.powers[power].centers) - len(game.powers[power].units)
        opts = [o for loc in locs for o in possible.get(loc) or []
                if (o.endswith(" B") if n > 0 else o.endswith(" D"))]
        rng.shuffle(opts)
        used = set()
        for o in opts:
            loc = o.split()[1][:3]
            if loc not in used and len(orders) < abs(n):
                orders.append(o)
                used.add(loc)
    else:
        orders = [rng.choice(sorted(possible[loc])) for loc in locs if possible.get(loc)]
    return "TO SELF: playing at random\n```\n" + "\n".join(orders) + "\n```"


# --------------------------------------------------------------------------- #
# Reading a reply
# --------------------------------------------------------------------------- #
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_TO = re.compile(r"^\s*[*_`]*TO\s+([A-Za-z][A-Za-z ,]*?)\s*[*_`]*:\s*(.+)$")
_ORDER = re.compile(r"^[AF]\s+[A-Z]{3}", re.I)


@dataclass
class Reply:
    orders: list[str] = field(default_factory=list)
    mail: list[tuple[list[str], str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_reply(text: str) -> Reply:
    """Orders from the last fenced block (else bare order lines), plus TO lines."""
    out = Reply()
    answer = _THINK.sub("", text)
    if not answer.strip():
        answer = text

    for line in answer.splitlines():
        m = _TO.match(line)
        if not m:
            continue
        targets = [t for t in re.split(r"[,\s]+", m.group(1).upper()) if t]
        body = m.group(2).strip().lstrip("*_` ").strip()
        if targets == ["SELF"]:
            out.notes.append(body)
        elif all(t in POWERS or t == ALL for t in targets):
            out.mail.append((targets, body))

    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)```", answer, re.S)
    source = blocks[-1] if blocks else answer
    for line in source.splitlines():
        line = line.split("#")[0].strip().strip("`*-• ").strip()
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if _ORDER.match(line) and not _TO.match(line):
            out.orders.append(line)
    return out


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def system_prompt(match: Match, power: str) -> str:
    press = ("This is full press: you can send private messages to the other "
             "powers. Nothing said is binding." if match.full_press
             else "This is gunboat: no messages, only orders.")
    return (f"You are playing the board game Diplomacy as {power}, against six other "
            f"players. {press} Aim to win: control 18 supply centres, or as many "
            "as you can by the end.")


def orders_format(match: Match, power: str) -> str:
    examples = "\n".join(boardmod.example_orders(match.load(), power)) or "A <at> H"
    return (
        "Reply with your orders for this phase in ONE fenced code block, one "
        "order per line, written exactly like the orders listed above. This "
        "shows the format only; choose your own moves:\n"
        f"```\n{examples}\n```\nThink first if you like; only the last "
        "code block counts. Optionally add lines `TO SELF: <note>` to remember "
        "plans for later turns.")


MAIL_FORMAT = (
    "Write each message on its own line as `TO ENGLAND: <message>`, "
    "`TO ENGLAND, GERMANY: <message>` or `TO ALL: <message>`.")


def task(kind: str, orders: str = "", round_no: int = 0, rounds: int = 0) -> str:
    if kind == "talk":
        return (f"Negotiation round {round_no} of {rounds}. Orders come after the "
                f"last round. {MAIL_FORMAT} You may also write `TO SELF: <note>` "
                "lines. Do not write orders yet.")
    if kind == "final":
        return f"{FINAL_ROUND_NOTE} You may send last messages first. {MAIL_FORMAT}\n\n{orders}"
    return orders


# --------------------------------------------------------------------------- #
# The runner
# --------------------------------------------------------------------------- #
class Runner:
    def __init__(self, match: Match, seats: dict[str, Seat], *, rounds: int = 2,
                 concurrency: int = 4, images: bool = False, max_tokens: int = 8000,
                 timeout: float = 180, call_limit: float = 3600,
                 seed: int | None = None, log=print):
        self.match, self.seats = match, seats
        self.rounds, self.images = rounds, images
        self.max_tokens, self.timeout, self.call_limit = max_tokens, timeout, call_limit
        self.log = log
        self.rng = random.Random(seed)
        self._gates: dict[str, threading.Semaphore] = {}
        self._gate_lock = threading.Lock()
        self.concurrency = concurrency

    def _gate(self, seat: Seat) -> threading.Semaphore:
        with self._gate_lock:
            return self._gates.setdefault(seat.endpoint,
                                          threading.Semaphore(self.concurrency))

    def _complete(self, power: str, prompt: str) -> str:
        seat = self.seats[power]
        if seat.kind == "fake":
            return fake_reply(self.match, power, self.rng)
        system = system_prompt(self.match, power)
        image = None
        if self.images and self.match.load().phase_type == "M":
            image = mapviz.phase_image(self.match.path, self.match.load())
        with self._gate(seat):
            for attempt in (1, 2):
                try:
                    if seat.kind == "openai":
                        return call_openai(seat, system, prompt, image, self.max_tokens,
                                           self.timeout, transport=functools.partial(
                                               _stream, limit=self.call_limit))
                    return call_claude(seat, system, prompt, image, self.max_tokens,
                                       self.call_limit)
                except ServerError:
                    if image:          # a text-only model may reject the picture
                        image = None
                        continue
                    raise
                except (urllib.error.URLError, TimeoutError, OSError, RuntimeError,
                        subprocess.TimeoutExpired) as exc:
                    if image:          # a text-only model may reject the picture
                        image = None
                        continue
                    if attempt == 2:
                        if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
                            raise TimeoutError(f"{exc} — {SLOW_HINT}") from None
                        raise
                    self.log(f"  {power}: call failed ({exc}); retrying")
                    time.sleep(3)
        return ""

    def _prompt(self, power: str, kind: str, **kw) -> str:
        board = boardmod.render(self.match, power, inbox=True, notes=True)
        return f"{board}\n\n---\n\n{task(kind, orders_format(self.match, power), **kw)}"

    def _record(self, power: str, phase: str, kind: str, data: dict) -> None:
        d = self.match.path / "log" / phase
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{power}-{kind}.json").write_text(json.dumps(data, indent=2))

    def _deliver(self, power: str, reply: Reply) -> int:
        self.match.add_notes(power, reply.notes)
        sent = 0
        if self.match.full_press:
            for to, body in reply.mail[:10]:
                if self.match.send(power, to, body):
                    sent += 1
        return sent

    def talk(self, power: str, phase: str, round_no: int) -> None:
        start = time.monotonic()
        try:
            text = self._complete(power, self._prompt(
                power, "talk", round_no=round_no, rounds=self.rounds))
        except Exception as exc:
            self.log(f"  {power} talk {round_no}: failed — {exc}")
            return
        reply = parse_reply(text)
        sent = self._deliver(power, reply)
        self._record(power, phase, f"talk{round_no}", {"reply": text})
        self.log(f"  {power} talk {round_no}: {sent} message(s) "
                 f"({time.monotonic() - start:.0f}s)")

    def orders(self, power: str, phase: str) -> None:
        start = time.monotonic()
        game = self.match.load()
        kind = "final" if self.match.full_press and game.phase_type == "M" else "orders"
        prompt = self._prompt(power, kind)
        replies, orders, note = [], [], ""
        for attempt in (1, 2):
            try:
                text = self._complete(power, prompt)
            except Exception as exc:
                note = f"call failed: {exc}"
                break
            replies.append(text)
            reply = parse_reply(text)
            if attempt == 1:
                self._deliver(power, reply)
            else:
                self.match.add_notes(power, reply.notes)
            checked = check_orders(game, power, reply.orders)
            orders = checked.accepted
            if reply.orders and checked.ok:
                note = ""
                break
            problem = ("\n".join(f"- {e}" for e in checked.errors) if checked.errors
                       else "- no orders found: put them in one fenced code block")
            note = f"retry: {problem.splitlines()[0][2:]}"
            units = ", ".join(game.powers[power].units) or "none"
            examples = "\n".join(boardmod.example_orders(game, power))
            prompt = (f"{self._prompt(power, 'orders')}\n\nYour last reply could not "
                      f"be used:\n{problem}\n\nYou are {power}. Your units: {units}. "
                      "Write one order per unit, each exactly like a line from the "
                      f"list above, for example:\n```\n{examples}\n```\nReply again with "
                      "your complete orders in one fenced code block. Messages were "
                      "already sent.")
        try:
            self.match.submit(power, orders, partial=True, phase=phase)
        except LateOrders as exc:
            self._record(power, phase, "orders", {"replies": replies, "late": str(exc)})
            self.log(f"  {power}: too late — {exc}")
            return
        self._record(power, phase, "orders", {"replies": replies, "submitted": orders})
        held = "" if orders else " — holding"
        self.log(f"  {power} ({self.seats[power].label()}): {len(orders)} order(s){held}"
                 f"{' [' + note + ']' if note else ''} ({time.monotonic() - start:.0f}s)")

    def phase(self) -> None:
        game = self.match.load()
        phase = game.get_current_phase()
        played = [p for p in POWERS if self.seats[p].kind != "agent"]
        alive = [p for p in played if game.powers[p].units or game.powers[p].centers]
        owing = [p for p in self.match.owing(game) if p in played
                 and p not in self.match.submitted(game)]
        self.log(f"{phase}")
        busy = self.match.path / "busy"
        busy.write_text(str(os.getpid()))
        try:
            with ThreadPoolExecutor(max_workers=7) as pool:
                if self.match.full_press and game.phase_type == "M":
                    for r in range(1, self.rounds + 1):
                        list(pool.map(lambda p: self.talk(p, phase, r), alive))
                list(pool.map(lambda p: self.orders(p, phase), owing))
        finally:
            busy.unlink(missing_ok=True)
        waiting = False
        while not self.match.ended() and self.match.phase() == phase:
            if not waiting:
                g = self.match.load()
                missing = [p for p in self.match.owing(g) if p not in self.match.submitted(g)]
                self.log(f"  waiting for {', '.join(missing)}")
                waiting = True
            self.match.advance()
            time.sleep(2)
        if hist := self.match.history(phase):
            if hist.get("missing"):
                self.log(f"  {phase} resolved ({hist.get('resolved', 'deadline')}) with "
                         f"{len(hist['missing'])} missing, who held: {', '.join(hist['missing'])}")

    def play(self, max_phases: int | None = None) -> None:
        n = 0
        while not self.match.ended() and (max_phases is None or n < max_phases):
            self.phase()
            n += 1
        game = self.match.load()
        if self.match.ended():
            self.log(f"\nGame over: {self.match.ended()}. Centres: " + ", ".join(
                f"{p} {len(game.powers[p].centers)}" for p in
                sorted(POWERS, key=lambda p: -len(game.powers[p].centers))))


def add_arguments(p) -> None:
    p.add_argument("name", help="the match (create it with `./dip new`)")
    p.add_argument("--model", help="model for every seat not set with --seat "
                                   "(default: the one given to `new`)")
    p.add_argument("--base-url", help="OpenAI-compatible base URL, e.g. "
                                      "http://127.0.0.1:1234/v1 (default: the one given to `new`)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY",
                   help="environment variable holding the API key, if any")
    p.add_argument("--seat", action="append", default=[], metavar="POWER=SPEC",
                   help="per-seat spec: <model>, openai:<model>@<url>, claude:<model>, agent, fake")
    p.add_argument("--agents", default="", help="POWER,POWER played from outside")
    p.add_argument("--rounds", type=int, default=2,
                   help="negotiation rounds per movement phase (full press)")
    p.add_argument("--concurrency", type=int, default=4,
                   help="simultaneous calls per endpoint")
    p.add_argument("--images", action="store_true", help="attach the board picture")
    p.add_argument("--max-tokens", type=int, default=8000,
                   help="per call; reasoning models spend most of it thinking")
    p.add_argument("--reasoning-effort", choices=["low", "medium", "high"],
                   help="ask the server for less (or more) thinking, if it supports it")
    p.add_argument("--timeout", type=float, default=180,
                   help="give up on a call after this many seconds with no tokens at all")
    p.add_argument("--call-limit", type=float, default=3600,
                   help="longest any one call may run, even while still writing")
    p.add_argument("--phases", type=int, help="stop after this many phases")
    p.add_argument("--seed", type=int)
    p.add_argument("--foreground", action="store_true",
                   help="stay attached instead of running in the background")
    p.add_argument("--no-check", action="store_true", help=argparse.SUPPRESS)


def seats_from_args(args) -> dict[str, Seat]:
    key = os.environ.get(args.api_key_env, "")
    specs = {}
    for item in args.seat:
        power, _, spec = item.partition("=")
        if power.upper() not in POWERS or not spec:
            raise SystemExit(f"bad --seat {item!r}; use e.g. FRANCE=qwen3:8b")
        specs[power.upper()] = spec
    for power in filter(None, args.agents.upper().replace(" ", "").split(",")):
        specs[power] = "agent"
    seats = {}
    for power in POWERS:
        spec = specs.get(power) or args.model
        if not spec:
            raise SystemExit(f"no model for {power}. Pass --model <name> --base-url <url> "
                             f"(or give them to `./dip new`), or --seat {power}=...")
        seats[power] = parse_seat(spec, args.base_url, key)
        seats[power].reasoning_effort = args.reasoning_effort or ""
    return seats


def runner_pid(match: Match) -> int | None:
    """The pid of this match's background runner, if one is alive."""
    f = match.path / "run.pid"
    if not f.exists():
        return None
    try:
        pid = int(f.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def main(args) -> int:
    match = Match.open(args.name)
    saved = match.config.get("run") or {}
    args.model = args.model or saved.get("model")
    args.base_url = (args.base_url or saved.get("base_url")
                     or os.environ.get("OPENAI_BASE_URL", ""))
    seats = seats_from_args(args)

    if not args.no_check:
        checked = set()
        for seat in seats.values():
            if seat.kind == "openai" and seat.endpoint + seat.model not in checked:
                checked.add(seat.endpoint + seat.model)
                ok, line = check_endpoint(seat)
                print(line, flush=True)
                if not ok:
                    return 1

    if not args.foreground:
        if pid := runner_pid(match):
            print(f"Already running (pid {pid}). `./dip status {match.name}` to check, "
                  f"`./dip stop {match.name}` to stop.")
            return 1
        log = match.path / "run.log"
        argv = [a for a in sys.argv[1:] if a != "--detach"] + ["--foreground", "--no-check"]
        with open(log, "a") as out:
            proc = subprocess.Popen([sys.executable, "-m", "vibe", *argv], cwd=ROOT,
                                    stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        (match.path / "run.pid").write_text(str(proc.pid))
        print(f"Running in the background (pid {proc.pid}); it stops by itself when "
              f"the game ends.\n  check:  {ROOT / 'dip'} status {match.name}\n"
              f"  log:    {log}\n  stop:   {ROOT / 'dip'} stop {match.name}")
        return 0

    progress = match.path / "progress.log"

    def log(line: str) -> None:
        # Also to a file, so whoever started the run can check on it with
        # `./dip status` instead of watching the terminal.
        print(line, flush=True)
        with open(progress, "a") as fh:
            fh.write(line + "\n")

    log(f"Match {match.name}: " + ", ".join(f"{p} {s.label()}" for p, s in seats.items()))
    Runner(match, seats, rounds=args.rounds, concurrency=args.concurrency,
           images=args.images, max_tokens=args.max_tokens, timeout=args.timeout,
           call_limit=args.call_limit,
           seed=args.seed, log=log).play(args.phases)
    return 0
