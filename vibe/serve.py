"""`./dip serve` — human seats over HTTP: the same powers a seat has at the CLI.

A small JSON API, bound to 127.0.0.1, for the web page that humans play from.
A seat's token is its key, exactly as with `./dip submit --seat`, so a human is
just another seat and mixes with model seats through the same match files.

    GET  /api/matches                 every match: phase, deadline, seats
    POST /api/new                     {humans: [POWER...], model, max_year, deadline}
    POST /api/claim                   {match, power} -> {token}   (open human seats)
    GET  /api/seat/<token>            the seat's board, as data
    GET  /api/seat/<token>/map.svg    the current position
    POST /api/seat/<token>/submit     {orders: [...]}
    POST /api/seat/<token>/ready      {ready: true|false}

Matches created here are hosted: their model seats are played by `./dip run`,
started here and restarted here if it isn't running (after a reboot, say).
"""
from __future__ import annotations

import http.server
import json
import re
import subprocess
import sys
import time
import urllib.parse

from vibe import board as boardmod
from vibe import mapviz
from vibe.game import POWERS, ROOT, LateOrders, Match, MatchError, legal_orders

MODELS = ("claude:haiku", "claude:sonnet", "fake", "hold")
DEADLINES = (3600, 86400)
MAX_MODEL_MATCHES = 3           # live hosted matches with Claude seats: a quota guard
# The page's own homes: the portal on the tailnet and on the LAN door, and this
# server itself. Browsers may POST only from these (no cross-site requests).
ORIGINS = {"https://skandha-1.tailafb97d.ts.net", "http://192.168.1.159:8080",
           "http://skandha-1.local:8080", "http://127.0.0.1:8010", "http://localhost:8010"}


def _summary(match: Match) -> dict:
    cfg = match.config
    game = match.load()
    humans = cfg.get("humans") or {}
    players = cfg.get("players") or {}
    return {
        "name": cfg["name"], "phase": game.get_current_phase(), "ended": match.ended(),
        "press": cfg.get("press", "none"), "max_year": cfg["max_year"],
        "deadline_at": (cfg["phase_started"] + cfg["deadline_s"]
                        if cfg.get("deadline_s") and not match.ended() else None),
        "seats": {p: {"human": p in humans, "open": humans.get(p) == "open",
                      "player": "human" if p in humans else players.get(p, ""),
                      "centres": len(game.powers[p].centers)} for p in POWERS},
    }


def season(phase: str) -> str:
    """'F1901M' -> 'Fall 1901'; 'W1901A' -> 'Winter 1901 builds'."""
    if len(phase) < 6:
        return phase
    name = {"S": "Spring", "F": "Fall", "W": "Winter"}.get(phase[0], phase[0])
    kind = {"M": "", "R": " retreats", "A": " builds"}.get(phase[-1], "")
    return f"{name} {phase[1:5]}{kind}"


def seat_state(match: Match, power: str) -> dict:
    game = match.load()
    cfg = match.config
    options = {}
    units = {u.split()[1].split("/")[0]: u for u in game.powers[power].units}
    retreating = {u.split()[1].split("/")[0]: u
                  for u in (game.powers[power].retreats or {})}
    for loc, orders in legal_orders(game, power).items():
        options[loc] = {"unit": units.get(loc) or retreating.get(loc) or loc,
                        "orders": orders}
    pending = match.path / "pending" / f"{power}.json"
    submitted = None
    if pending.exists():
        data = json.loads(pending.read_text())
        if data.get("phase") == game.get_current_phase():
            submitted = data["orders"]
    owing = match.owing(game)
    adjust = (len(game.powers[power].centers) - len(game.powers[power].units)
              if game.phase_type == "A" else 0)
    return {
        **_summary(match),
        "power": power, "season": season(game.get_current_phase()),
        "phase_type": game.phase_type,
        "units": list(game.powers[power].units), "centres": sorted(game.powers[power].centers),
        "options": options, "adjust": adjust, "owes": power in owing,
        "submitted": submitted, "ready": power in match.readied(game),
        "ready_count": len([p for p in match.readied(game) if p in owing]),
        "owing_count": len(owing),
        "last": boardmod._my_outcomes(match, game, power),
        "standings": boardmod._standings(game, power),
        "now": time.time(), "deadline_s": cfg.get("deadline_s", 0),
        "names": {abbr: name.title() for name, abbr in game.map.loc_name.items()},
    }


def start_runner(match: Match) -> None:
    """Have `./dip run` play the model seats; it returns once it has started."""
    hosted = match.config.get("hosted") or {}
    humans = sorted(match.config.get("humans") or {})
    cmd = [str(ROOT / "dip"), "run", match.name, "--model", hosted.get("model", "fake")]
    if humans:
        cmd += ["--agents", ",".join(humans)]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if done.returncode:
        sys.stderr.write(f"runner for {match.name} did not start: "
                         f"{(done.stdout + done.stderr).strip()[-500:]}\n")


def resume_all() -> None:
    from vibe.run import runner_pid
    for m in Match.all():
        if m.config.get("hosted") and not m.ended() and not runner_pid(m):
            start_runner(m)


def create(body: dict) -> Match:
    humans = [p.upper() for p in body.get("humans") or []]
    model = body.get("model") or "claude:haiku"
    deadline = int(body.get("deadline") or DEADLINES[0])
    max_year = int(body.get("max_year") or 1904)
    if not humans or any(p not in POWERS for p in humans):
        raise MatchError("pick at least one power for humans")
    if model not in MODELS or deadline not in DEADLINES or not 1901 <= max_year <= 1930:
        raise MatchError("bad settings")
    if model.startswith("claude:") and sum(
            1 for m in Match.all() if m.config.get("hosted") and not m.ended()
            and str((m.config.get("hosted") or {}).get("model", "")).startswith("claude:")
    ) >= MAX_MODEL_MATCHES:
        raise MatchError(f"already {MAX_MODEL_MATCHES} matches with model seats running; "
                         "finish one first, or use Random or Hold")
    name = body.get("name") or time.strftime("game-%m%d-%H%M")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise MatchError("names are letters, digits, - and _")
    match = Match.create(name, press="none", max_year=max_year, deadline_s=deadline)
    match._set_config(humans={p: "open" for p in humans}, hosted={"model": model})
    start_runner(match)
    return match


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        line = re.sub(r"/api/seat/[0-9a-f]+", "/api/seat/…", fmt % args)  # tokens are keys
        sys.stderr.write(f"{self.log_date_time_string()} {line}\n")

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise MatchError("bad Content-Length") from None
        if not 0 <= n <= 100_000:
            raise MatchError("bad Content-Length")
        body = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise MatchError("expected a JSON object")
        return body

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _seat(self, token: str) -> tuple[Match, str]:
        if not re.fullmatch(r"[0-9a-f]{4,64}", token):
            raise MatchError("no such seat")
        match, power = Match.by_token(token)
        if power not in (match.config.get("humans") or {}):
            raise MatchError("no such seat")      # only human seats are served
        return match, power

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                page = (ROOT / "vibe" / "static" / "play.html").read_bytes()
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/matches":
                return self._json(200, [_summary(m) for m in reversed(Match.all())
                                        if m.config.get("hosted")])
            if m := re.fullmatch(r"/api/seat/([^/]+)", path):
                match, power = self._seat(m[1])
                match.advance()                    # a passed deadline resolves on a look
                return self._json(200, seat_state(match, power))
            if m := re.fullmatch(r"/api/seat/([^/]+)/map\.svg", path):
                match, _ = self._seat(m[1])
                svg = mapviz.board_svg(match.load(), orders=False)
                return self._send(200, svg.encode(), "image/svg+xml")
            return self._json(404, {"error": "not found"})
        except MatchError as exc:
            return self._json(400, {"error": str(exc)})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        # No cross-site POSTs: a browser always sends Origin on a POST, and a
        # JSON content type can't be sent cross-site without a preflight.
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ORIGINS:
            return self._json(403, {"error": "not from this site"})
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "send JSON"})
        try:
            body = self._body()
            if path == "/api/new":
                return self._json(200, _summary(create(body)))
            if path == "/api/claim":
                match = Match.open(str(body.get("match", "")))
                power = str(body.get("power", "")).upper()
                with match._lock():
                    humans = match.config.get("humans") or {}
                    if humans.get(power) != "open":
                        raise MatchError("that seat is taken")
                    match._set_config(humans={**humans, power: "taken"})
                return self._json(200, {"token": match.config["seats"][power]})
            if m := re.fullmatch(r"/api/seat/([^/]+)/submit", path):
                match, power = self._seat(m[1])
                phase = body.get("phase") or None
                try:
                    checked = match.submit(power, [str(o) for o in body.get("orders") or []],
                                           phase=phase)
                except LateOrders as exc:
                    return self._json(409, {"error": str(exc)})
                if not checked.ok:
                    return self._json(400, {"error": "; ".join(checked.errors)})
                return self._json(200, seat_state(match, power))
            if m := re.fullmatch(r"/api/seat/([^/]+)/ready", path):
                match, power = self._seat(m[1])
                if not match.set_ready(power, bool(body.get("ready")),
                                       phase=body.get("phase") or None):
                    return self._json(409, {"error": "that phase has already resolved"})
                return self._json(200, seat_state(match, power))
            return self._json(404, {"error": "not found"})
        except (MatchError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})


class Server(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # http.server's bind does a reverse-DNS lookup that can hang; skip it.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


def main(args) -> int:
    resume_all()
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"serving human seats on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
    return 0
