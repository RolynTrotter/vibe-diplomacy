"""A match on disk, and everything that changes it.

Each match is one directory, `games/<name>/` (gitignored):

    config.json          press, deadline, year cap, the seat tokens  (host only)
    game.json            the engine's saved-game format: every phase so far
    pending/<POWER>.json this phase's orders, until it resolves     (host only)
    ready/<POWER>        the phase a power has declared itself done with
    history/<phase>.json what was ordered and what happened, once resolved
    mail.jsonl           every message, revealed to the site when the game ends
    notes/<POWER>.md     a seat's private notebook, shown back to it on its board
    notes.jsonl          every notebook as written, by phase (for log.md)
    log.md               the readable record: press, orders, results, notes, lore
    briefs/<POWER>.md    the one page a seat is handed

Lore outlives a match: `_lore/<POWER>.md`, beside the matches, is what earlier
players of each power left for the next one.

Order secrecy is by not telling: a seat acts through its token, and nothing a
seat is shown names another seat's files. Submitting and being Ready are
separate: orders can be in while the talking goes on. A phase resolves the
moment every power that owes orders is Ready, or when its deadline passes
(missing orders hold) — whichever process notices first does the work, under a
file lock, so there is no daemon.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from diplomacy import Game
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"
POWERS = ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY")
# Maps from the engine. A match plays the powers its map has: the 1v1 variant
# leaves every other centre empty and unowned.
MAPS = {"standard": "Standard", "standard_france_austria": "France vs Austria"}
ALL = "ALL"
NOTES_MAX = 2000                # a notebook, not a diary: it is on every board
LORE_MAX = 1500                 # one game's lore entry


# --------------------------------------------------------------------------- #
# Orders: normalize and validate against the engine's own enumeration
# --------------------------------------------------------------------------- #
def normalize(order: str) -> str:
    """'a par-bur' -> 'A PAR - BUR', so any spacing/case compares equal."""
    text = order.split("#")[0].upper().strip().rstrip(".,;")
    # "F LON: F LON - NTH" / "F LON: H" — a unit written as a label
    label = re.match(r"^([AF]\s+[A-Z/]+)\s*:\s*(.*)$", text)
    if label:
        text = label[2] if re.match(r"^[AF]\s", label[2]) else f"{label[1]} {label[2]}"
    text = text.replace("→", "-").replace("->", "-")
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
    refused: list[str] = field(default_factory=list)   # short, for the seat's next board

    @property
    def ok(self) -> bool:
        return not self.errors


def check_orders(game: Game, power: str, orders: list[str]) -> Checked:
    """Accepted canonical orders, and one readable error per rejected one.

    One order per unit. A unit given two different orders is not guessed at
    (a model that pastes the whole list of legal moves names every one of
    them): it holds, and the error says so. Repeating the same order is fine.
    """
    legal = legal_orders(game, power)
    canon = {normalize(o): o for opts in legal.values() for o in opts}
    out = Checked()
    per_unit: dict[str, list[str]] = {}
    for raw in orders:
        if not raw.strip():
            continue
        norm = normalize(raw)
        if norm in canon:
            order = canon[norm]
            parts = order.split()
            key = parts[1].split("/")[0] if parts[0] in ("A", "F") else order
            if order not in per_unit.setdefault(key, []):
                per_unit[key].append(order)
            continue
        parts = norm.split()
        loc = (parts[1] if len(parts) > 1 and parts[0] in ("A", "F")
               else parts[0]).split("/")[0]
        if loc in legal:
            shown = legal[loc] if len(legal[loc]) <= 25 else legal[loc][:25] + ["..."]
            out.errors.append(f"{raw!r} is not legal. Legal orders for {loc}: "
                              + ", ".join(shown))
            why = "not a legal order"
            if len(parts) == 4 and parts[2] == "-":
                dest = parts[3].split("/")[0]
                if not game.map.abuts(parts[0], parts[1], "-", parts[3]):
                    why += f": {loc} does not border {dest}"
            out.refused.append(f"{norm} — {why}")
        else:
            out.errors.append(f"{raw!r}: you have nothing to order at {loc} this "
                              f"phase. You can order: {', '.join(sorted(legal)) or 'nothing'}")
            out.refused.append(f"{norm} — you had nothing to order at {loc}")
    for loc, given in per_unit.items():
        # Two builds offered for one centre ("A BER B", "F BER B"): the last
        # one written is the choice. Any other unit with two orders holds.
        if len(given) == 1 or all(o.endswith(" B") for o in given):
            out.accepted.append(given[-1])
            continue
        shown = given if len(given) <= 4 else given[:4] + ["..."]
        out.errors.append(f"{len(given)} different orders for {loc} ({', '.join(shown)}); "
                          f"it holds. Give exactly one order per unit")
        out.refused.append(f"{len(given)} different orders for {loc} — it held")
    return out


# --------------------------------------------------------------------------- #
# The match
# --------------------------------------------------------------------------- #
class MatchError(Exception):
    pass


class LateOrders(MatchError):
    """Orders written for a phase that has already resolved."""


def _write(path: Path, text: str) -> None:
    """Replace a file in one step, so a reader never sees half of it.

    Several processes and threads read these files while one writes them
    (`status` while the runner plays, seats while a phase resolves).
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


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
               deadline_s: int = 0, root: Path | None = None,
               map_name: str = "standard") -> "Match":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise MatchError("match names are letters, digits, - and _")
        path = Path(root or GAMES) / name
        if path.exists():
            raise MatchError(f"match {name!r} already exists at {path}")
        if map_name not in MAPS:
            raise MatchError(f"unknown map {map_name!r}; try {', '.join(MAPS)}")
        game = Game(map_name=map_name)
        powers = sorted(game.powers)
        path.mkdir(parents=True)
        config = {
            "name": name, "press": press, "max_year": max_year,
            "deadline_s": deadline_s, "phase_started": time.time(),
            "ended": None,
            "map": map_name, "powers": powers,
            "seats": {p: secrets.token_hex(12) for p in powers},
        }
        _write(path / "config.json", json.dumps(config, indent=2))
        match = cls(path)
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
        _write(self.path / "config.json", json.dumps(cfg, indent=2))

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def powers(self) -> tuple[str, ...]:
        """The powers this match is played by (all seven, unless a variant)."""
        return tuple(self.config.get("powers") or POWERS)

    @property
    def full_press(self) -> bool:
        return self.config.get("press") == "full"

    def load(self) -> Game:
        return from_saved_game_format(json.loads((self.path / "game.json").read_text()))

    def save(self, game: Game) -> None:
        _write(self.path / "game.json", json.dumps(to_saved_game_format(game)))

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
        return [p for p in sorted(game.powers) if game.get_orderable_locations(p)]

    def _pending(self, power: str) -> Path:
        return self.path / "pending" / f"{power}.json"

    def submitted(self, game: Game | None = None) -> list[str]:
        game = game or self.load()
        phase = game.get_current_phase()
        out = []
        for p in self.powers:
            f = self._pending(p)
            if f.exists() and json.loads(f.read_text()).get("phase") == phase:
                out.append(p)
        return out

    def readied(self, game: Game | None = None) -> list[str]:
        """Powers that have declared themselves done with this phase."""
        phase = (game or self.load()).get_current_phase()
        d = self.path / "ready"
        return [p for p in self.powers if (d / p).exists() and (d / p).read_text().strip() == phase]

    def set_ready(self, power: str, ready: bool = True, *, phase: str | None = None) -> bool:
        """Declare `power` done with the phase (or not). Ready resolves the
        phase once every power that owes orders is Ready. False if `phase`
        has already resolved."""
        if self.ended():
            raise MatchError(f"the game is over ({self.ended()})")
        with self._lock():
            current = self.load().get_current_phase()
            if phase and phase != current:
                return False
            f = self.path / "ready" / power
            if ready:
                f.parent.mkdir(exist_ok=True)
                _write(f, current)
            else:
                f.unlink(missing_ok=True)
        self.advance()
        return True

    def submit(self, power: str, orders: list[str], *, partial: bool = False,
               phase: str | None = None, refused: list[str] = (),
               ready: bool = False) -> Checked:
        """Check and store `power`'s orders, replacing any earlier set.

        Any error rejects the whole set unless `partial`, in which case the
        legal orders are kept and the rest hold. An empty list is a valid
        submission: everything holds (or, in winter, builds are waived).

        `phase` is the phase the orders were written for. If that phase has
        already resolved they are refused, never applied to the next one:
        spring orders are often still legal in the fall, and would be
        silently accepted there.

        `refused` adds orders the seat wrote earlier that could not be used,
        so its next board can say so; otherwise a corrected set reads as
        though nothing had gone wrong.

        Submitting does not resolve the phase; being Ready does. `ready`
        declares it in the same step, once the orders are stored.
        """
        if self.ended():
            raise MatchError(f"the game is over ({self.ended()})")
        with self._lock():
            game = self.load()
            current = game.get_current_phase()
            if phase and phase != current:
                raise LateOrders(f"{phase} has already resolved (it is now {current}); "
                                 f"these orders were not used")
            checked = check_orders(game, power, orders)
            if checked.ok or partial:
                f = self._pending(power)
                f.parent.mkdir(exist_ok=True)
                _write(f, json.dumps({"phase": game.get_current_phase(),
                                         "orders": checked.accepted,
                                         "refused": [*refused, *checked.refused]}))
                if ready:
                    (self.path / "ready").mkdir(exist_ok=True)
                    _write(self.path / "ready" / power, current)
        self.advance()
        return checked

    def advance(self, *, force: bool = False) -> dict | None:
        """Resolve the phase if everyone is Ready, its deadline passed, or forced.

        Returns what resolved, or None if the phase is still open.
        """
        with self._lock():
            if self.ended():
                return None
            game = self.load()
            cfg = self.config
            owing = self.owing(game)
            done = set(self.readied(game))
            late = (cfg.get("deadline_s") and not self.runner_busy() and
                    time.time() - cfg["phase_started"] > cfg["deadline_s"])
            if not (force or late or done >= set(owing)):
                return None
            how = "forced" if force else "everyone ready" if done >= set(owing) else "deadline"
            return self._resolve(game, owing, how)

    def runner_busy(self) -> bool:
        """Whether `dip run` has calls in flight for this phase.

        The deadline is for players who have gone away, not for a model the
        runner is still waiting on, so it does not fire while this is true.
        """
        f = self.path / "busy"
        if not f.exists():
            return False
        try:
            os.kill(int(f.read_text().strip()), 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            return False

    def _resolve(self, game: Game, owing: list[str], how: str = "everyone ready") -> dict:
        phase = game.get_current_phase()
        missing = sorted(set(owing) - set(self.submitted(game)))
        refused = {}
        for power in owing:
            f = self._pending(power)
            if f.exists():
                data = json.loads(f.read_text())
                if data.get("phase") == phase:
                    game.set_orders(power, data["orders"], expand=True, replace=True)
                    if data.get("refused"):
                        refused[power] = data["refused"]
        ordered = {p: list(game.get_orders(p)) for p in self.powers}
        game.process()
        results = {}
        try:
            results = {u: [str(r) for r in res if str(r)]
                       for u, res in game.result_history.last_value().items()}
        except (AttributeError, IndexError, KeyError):
            pass
        summary = {"phase": phase, "orders": ordered,
                   "results": {u: r for u, r in results.items() if r},
                   "missing": missing, "resolved": how, "refused": refused}
        self.save(game)
        hist = self.path / "history"
        hist.mkdir(exist_ok=True)
        _write(hist / f"{phase}.json", json.dumps(summary, indent=2))
        for f in [*(self.path / "pending").glob("*.json"), *(self.path / "ready").glob("*")]:
            f.unlink()

        ended = None
        if game.is_game_done:
            leader = max(self.powers, key=lambda p: len(game.powers[p].centers))
            ended = f"solo {leader}" if len(game.powers[leader].centers) >= 18 else "draw"
        elif _year(game.get_current_phase()) > self.config.get("max_year", 9999):
            ended = f"year cap {self.config['max_year']}"
        self._set_config(phase_started=time.time(), ended=ended)
        self.write_log()
        return summary

    def history(self, phase: str) -> dict | None:
        f = self.path / "history" / f"{phase}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def seen(self, power: str, phase: str | None = None) -> str | None:
        """The last phase shown to a seat; record a new one if given."""
        f = self.path / "seen" / power
        if phase:
            f.parent.mkdir(exist_ok=True)
            _write(f, phase)
            return phase
        return f.read_text().strip() if f.exists() else None

    # -- press --------------------------------------------------------------- #
    def send(self, sender: str, to: list[str], body: str) -> list[str]:
        """Record one message. Returns the recipients it went to."""
        if not self.full_press:
            raise MatchError("this is a gunboat game: no messages")
        to = [t.upper() for t in to]
        bad = [t for t in to if t not in self.powers and t != ALL]
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

    # -- notes and lore -------------------------------------------------------- #
    def notes(self, power: str) -> str:
        f = self.path / "notes" / f"{power}.md"
        return f.read_text() if f.exists() else ""

    def set_notes(self, power: str, text: str) -> None:
        """Replace `power`'s notebook. Only that power is shown it."""
        text = text.strip()[:NOTES_MAX]
        if not text or text == self.notes(power).strip():
            return
        d = self.path / "notes"
        d.mkdir(exist_ok=True)
        _write(d / f"{power}.md", text + "\n")
        with self._lock(), open(self.path / "notes.jsonl", "a") as fh:
            fh.write(json.dumps({"phase": self.phase(), "power": power,
                                 "text": text, "time": time.time()}) + "\n")

    def _lore_file(self, power: str) -> Path:
        return self.path.parent / "_lore" / f"{power}.md"

    def lore(self, power: str) -> str:
        """What earlier players of `power` left, newest last."""
        f = self._lore_file(power)
        return f.read_text() if f.exists() else ""

    def add_lore(self, power: str, text: str) -> bool:
        """After the game, `power`'s lesson for its next player. Once per match."""
        text = text.strip()[:LORE_MAX]
        if not (self.ended() and text):
            return False
        game = self.load()
        f = self._lore_file(power)
        head = f"## {self.name} ("
        with self._lock():
            # Checked under the lock, against the lore file itself, so two callers
            # or a retry after a crash can never leave a second entry.
            if any(line.startswith(head) for line in self.lore(power).splitlines()):
                return False
            f.parent.mkdir(exist_ok=True)
            with open(f, "a") as fh:
                fh.write(f"{head}{self.ended()}; {power} finished with "
                         f"{len(game.powers[power].centers)} centres)\n\n{text}\n\n")
            self._set_config(lore_from=sorted({*self.config.get("lore_from", []), power}))
        self.write_log()
        return True

    # -- the readable record ---------------------------------------------------- #
    def write_log(self) -> None:
        """log.md: the whole match, phase by phase, for whoever studies it after."""
        cfg = self.config
        game = self.load()
        played = [str(k) for k in game.order_history.keys()]
        # Press and notebooks are private until the game is over, like the viewer:
        # a seat that can read the match's files must not find its rivals' plans here.
        mail = self.messages() if self.ended() else []
        notes = []
        if self.ended() and (self.path / "notes.jsonl").exists():
            notes = [json.loads(l) for l in (self.path / "notes.jsonl").read_text().splitlines()
                     if l.strip()]
        players = cfg.get("players") or {}
        out = [f"# {cfg['name']}",
               f"{'Full press' if self.full_press else 'Gunboat'}, ends after "
               f"{cfg['max_year']}."]
        if players:
            out += ["", "Seats: " + ", ".join(f"{p} {players[p]}" for p in self.powers
                                              if p in players)]
        # The centres each phase left behind are the next phase's starting state.
        starts = [(str(k), v.get("centers") or {}) for k, v in game.state_history.items()]
        starts.append((game.get_current_phase(),
                       {p: list(game.powers[p].centers) for p in self.powers}))
        after = {ph: nxt for (ph, _), (_, nxt) in zip(starts, starts[1:])}
        for phase in [*played, *([] if self.ended() else [game.get_current_phase()])]:
            hist = self.history(phase) or {}
            said = [m for m in mail if m["phase"] == phase]
            wrote = [n for n in notes if n["phase"] == phase]
            if not (hist or said or wrote):
                continue
            out += ["", f"## {phase}" + ("" if hist else " (in progress)")]
            if said:
                out += ["", "### Press"] + [
                    f"- {m['sender']} → {', '.join(m['to'])}: {m['body']}" for m in said]
            if hist:
                out += ["", "### Orders"] + [
                    f"- {p}: {', '.join(o)}" for p, o in sorted(hist["orders"].items()) if o]
                if hist.get("results"):
                    out += ["", "Results: " + "; ".join(
                        f"{u} {', '.join(r)}" for u, r in sorted(hist["results"].items()))]
                if hist.get("missing"):
                    out += ["", f"No orders (held): {', '.join(hist['missing'])}"]
                if hist.get("refused"):
                    out += ["", "Refused: " + "; ".join(
                        f"{p}: {', '.join(r)}" for p, r in sorted(hist["refused"].items()))]
            if wrote:
                last = {n["power"]: n["text"] for n in wrote}
                out += ["", "### Notebooks"]
                for p, text in sorted(last.items()):
                    out += [f"- {p}:"] + [f"  > {l}" for l in text.splitlines()]
            if phase.endswith("A") and hist:
                centres = after.get(phase) or {}
                out += ["", "Centres: " + ", ".join(
                    f"{p} {len(centres.get(p) or [])}" for p in
                    sorted(self.powers, key=lambda p: -len(centres.get(p) or [])))]
        if self.ended():
            out += ["", f"## Game over: {self.ended()}", "", ", ".join(
                f"{p} {len(game.powers[p].centers)}" for p in
                sorted(self.powers, key=lambda p: -len(game.powers[p].centers)))]
            for p in cfg.get("lore_from", []):
                entry = self.lore(p).rsplit(f"## {self.name} (", 1)
                if len(entry) == 2:
                    out += ["", f"### Lore from {p}", "", entry[1].split("\n", 1)[1].strip()]
        _write(self.path / "log.md", "\n".join(out) + "\n")
