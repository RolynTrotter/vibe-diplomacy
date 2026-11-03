"""A match on disk, and everything that changes it.

Each match is one directory, `games/<name>/` (gitignored):

    config.json          press, deadline, year cap, the seat tokens  (host only)
    game.json            the engine's saved-game format: every phase so far
    pending/<POWER>.json this phase's orders, until it resolves     (host only)
    history/<phase>.json what was ordered and what happened, once resolved
    mail.jsonl           every message, revealed to the site when the game ends
    notes/<POWER>.md     a model seat's own notebook
    briefs/<POWER>.md    the one page a seat is handed

Order secrecy is by not telling: a seat acts through its token, and nothing a
seat is shown names another seat's files. A phase resolves the moment every
power that owes orders has submitted, or when its deadline passes — whichever
process notices first does the work, under a file lock, so there is no daemon.
"""
from __future__ import annotations

import fcntl
import json
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from diplomacy import Game
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"
POWERS = ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY")
ALL = "ALL"


# --------------------------------------------------------------------------- #
# Orders: normalize and validate against the engine's own enumeration
# --------------------------------------------------------------------------- #
def normalize(order: str) -> str:
    """'a par-bur' -> 'A PAR - BUR', so any spacing/case compares equal."""
    text = order.upper().strip().rstrip(".")
    text = text.replace("-", " - ")
    return re.sub(r"\s+", " ", text)


def legal_orders(game: Game, power: str) -> dict[str, list[str]]:
    """Orderable province -> every legal order there, for `power` this phase."""
    possible = game.get_all_possible_orders()
    out: dict[str, list[str]] = {}
    for loc in game.get_orderable_locations(power):
        opts = possible.get(loc) or []
        if opts:
            out[loc.split("/")[0]] = sorted(opts)
    return out


@dataclass
class Checked:
    accepted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_orders(game: Game, power: str, orders: list[str]) -> Checked:
    """Accepted canonical orders, and one readable error per rejected one."""
    legal = legal_orders(game, power)
    canon = {normalize(o): o for opts in legal.values() for o in opts}
    out = Checked()
    for raw in orders:
        if not raw.strip():
            continue
        norm = normalize(raw)
        if norm in canon:
            out.accepted.append(canon[norm])
            continue
        parts = norm.split()
        loc = (parts[1] if len(parts) > 1 and parts[0] in ("A", "F")
               else parts[0]).split("/")[0]
        if loc in legal:
            shown = legal[loc] if len(legal[loc]) <= 25 else legal[loc][:25] + ["..."]
            out.errors.append(f"{raw!r} is not legal. Legal orders for {loc}: "
                              + ", ".join(shown))
        else:
            out.errors.append(f"{raw!r}: you have nothing to order at {loc} this "
                              f"phase. You can order: {', '.join(sorted(legal)) or 'nothing'}")
    return out


# --------------------------------------------------------------------------- #
# The match
# --------------------------------------------------------------------------- #
class MatchError(Exception):
    pass


def _year(phase: str) -> int:
    return int(phase[1:5]) if len(phase) >= 5 and phase[1:5].isdigit() else 0


class Match:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not (self.path / "config.json").exists():
            raise MatchError(f"no match at {self.path}")

    # -- creating and finding ------------------------------------------------ #
    @classmethod
    def create(cls, name: str, *, press: str = "none", max_year: int = 1910,
               deadline_s: int = 0, root: Path | None = None) -> "Match":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise MatchError("match names are letters, digits, - and _")
        path = Path(root or GAMES) / name
        if path.exists():
            raise MatchError(f"match {name!r} already exists at {path}")
        path.mkdir(parents=True)
        config = {
            "name": name, "press": press, "max_year": max_year,
            "deadline_s": deadline_s, "phase_started": time.time(),
            "ended": None,
            "seats": {p: secrets.token_hex(4) for p in POWERS},
        }
        (path / "config.json").write_text(json.dumps(config, indent=2))
        match = cls(path)
        game = Game()
        game.note = name
        match.save(game)
        return match

    @classmethod
    def open(cls, name: str, root: Path | None = None) -> "Match":
        return cls(Path(root or GAMES) / name)

    @classmethod
    def by_token(cls, token: str, root: Path | None = None) -> tuple["Match", str]:
        """The match and power a seat token belongs to."""
        for cfg in sorted(Path(root or GAMES).glob("*/config.json")):
            seats = json.loads(cfg.read_text()).get("seats", {})
            for power, tok in seats.items():
                if tok == token:
                    return cls(cfg.parent), power
        raise MatchError(f"no seat with token {token!r}")

    @staticmethod
    def all(root: Path | None = None) -> list["Match"]:
        return [Match(c.parent) for c in sorted(Path(root or GAMES).glob("*/config.json"))]

    # -- state --------------------------------------------------------------- #
    @property
    def config(self) -> dict:
        return json.loads((self.path / "config.json").read_text())

    def _set_config(self, **changes) -> None:
        cfg = self.config
        cfg.update(changes)
        (self.path / "config.json").write_text(json.dumps(cfg, indent=2))

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def full_press(self) -> bool:
        return self.config.get("press") == "full"

    def load(self) -> Game:
        return from_saved_game_format(json.loads((self.path / "game.json").read_text()))

    def save(self, game: Game) -> None:
        tmp = self.path / "game.json.tmp"
        tmp.write_text(json.dumps(to_saved_game_format(game)))
        tmp.replace(self.path / "game.json")

    def phase(self) -> str:
        return self.load().get_current_phase()

    def ended(self) -> str | None:
        """Why the game is over ('solo FRANCE', 'year cap 1910'), or None."""
        return self.config.get("ended")

    @contextmanager
    def _lock(self):
        with open(self.path / ".lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    # -- orders -------------------------------------------------------------- #
    @staticmethod
    def owing(game: Game) -> list[str]:
        """Powers that have something to order this phase."""
        return [p for p in POWERS if game.get_orderable_locations(p)]

    def _pending(self, power: str) -> Path:
        return self.path / "pending" / f"{power}.json"

    def submitted(self, game: Game | None = None) -> list[str]:
        game = game or self.load()
        phase = game.get_current_phase()
        out = []
        for p in POWERS:
            f = self._pending(p)
            if f.exists() and json.loads(f.read_text()).get("phase") == phase:
                out.append(p)
        return out

    def submit(self, power: str, orders: list[str], *, partial: bool = False) -> Checked:
        """Check and store `power`'s orders, replacing any earlier set.

        Any error rejects the whole set unless `partial`, in which case the
        legal orders are kept and the rest hold. An empty list is a valid
        submission: everything holds (or, in winter, builds are waived).
        """
        if self.ended():
            raise MatchError(f"the game is over ({self.ended()})")
        with self._lock():
            game = self.load()
            checked = check_orders(game, power, orders)
            if checked.ok or partial:
                f = self._pending(power)
                f.parent.mkdir(exist_ok=True)
                f.write_text(json.dumps({"phase": game.get_current_phase(),
                                         "orders": checked.accepted}))
        self.advance()
        return checked

    def advance(self, *, force: bool = False) -> dict | None:
        """Resolve the phase if everyone is in, its deadline passed, or forced.

        Returns what resolved, or None if the phase is still open.
        """
        with self._lock():
            if self.ended():
                return None
            game = self.load()
            cfg = self.config
            owing = self.owing(game)
            done = set(self.submitted(game))
            late = (cfg.get("deadline_s") and
                    time.time() - cfg["phase_started"] > cfg["deadline_s"])
            if not (force or late or done >= set(owing)):
                return None
            return self._resolve(game, owing)

    def _resolve(self, game: Game, owing: list[str]) -> dict:
        phase = game.get_current_phase()
        missing = sorted(set(owing) - set(self.submitted(game)))
        for power in owing:
            f = self._pending(power)
            if f.exists():
                data = json.loads(f.read_text())
                if data.get("phase") == phase:
                    game.set_orders(power, data["orders"], expand=True, replace=True)
        ordered = {p: list(game.get_orders(p)) for p in POWERS}
        game.process()
        results = {}
        try:
            results = {u: [str(r) for r in res if str(r)]
                       for u, res in game.result_history.last_value().items()}
        except (AttributeError, IndexError, KeyError):
            pass
        summary = {"phase": phase, "orders": ordered,
                   "results": {u: r for u, r in results.items() if r},
                   "missing": missing}
        self.save(game)
        hist = self.path / "history"
        hist.mkdir(exist_ok=True)
        (hist / f"{phase}.json").write_text(json.dumps(summary, indent=2))
        for f in (self.path / "pending").glob("*.json"):
            f.unlink()

        ended = None
        if game.is_game_done:
            leader = max(POWERS, key=lambda p: len(game.powers[p].centers))
            ended = f"solo {leader}" if len(game.powers[leader].centers) >= 18 else "draw"
        elif _year(game.get_current_phase()) > self.config.get("max_year", 9999):
            ended = f"year cap {self.config['max_year']}"
        self._set_config(phase_started=time.time(), ended=ended)
        return summary

    def history(self, phase: str) -> dict | None:
        f = self.path / "history" / f"{phase}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def seen(self, power: str, phase: str | None = None) -> str | None:
        """The last phase shown to a seat; record a new one if given."""
        f = self.path / "seen" / power
        if phase:
            f.parent.mkdir(exist_ok=True)
            f.write_text(phase)
            return phase
        return f.read_text().strip() if f.exists() else None

    # -- press --------------------------------------------------------------- #
    def send(self, sender: str, to: list[str], body: str) -> list[str]:
        """Record one message. Returns the recipients it went to."""
        if not self.full_press:
            raise MatchError("this is a gunboat game: no messages")
        to = [t.upper() for t in to]
        bad = [t for t in to if t not in POWERS and t != ALL]
        if bad:
            raise MatchError(f"unknown recipient(s) {', '.join(bad)}; "
                             f"use power names or ALL")
        if ALL in to:
            to = [ALL]
        to = [t for t in to if t != sender]
        body = body.strip()
        if not body or not to:
            return []
        entry = {"phase": self.phase(), "sender": sender, "to": to,
                 "body": body, "time": time.time()}
        with self._lock(), open(self.path / "mail.jsonl", "a") as fh:
            fh.write(json.dumps(entry) + "\n")
        return to

    def messages(self) -> list[dict]:
        f = self.path / "mail.jsonl"
        if not f.exists():
            return []
        return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]

    def inbox(self, power: str) -> list[dict]:
        """Messages to `power`, to everyone, or from `power`, oldest first."""
        return [m for m in self.messages()
                if m["sender"] == power or power in m["to"] or ALL in m["to"]]

    # -- notes (model seats keep a notebook between stateless calls) ---------- #
    def notes(self, power: str) -> str:
        f = self.path / "notes" / f"{power}.md"
        return f.read_text() if f.exists() else ""

    def add_notes(self, power: str, lines: list[str], keep: int = 20) -> None:
        if not lines:
            return
        f = self.path / "notes" / f"{power}.md"
        f.parent.mkdir(exist_ok=True)
        phase = self.phase()
        old = [l for l in self.notes(power).splitlines() if l.strip()]
        new = old + [f"[{phase}] {l}" for l in lines]
        f.write_text("\n".join(new[-keep:]) + "\n")
