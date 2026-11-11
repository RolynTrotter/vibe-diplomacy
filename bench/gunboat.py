"""Gunboat bench: does a model read the board well enough to play?

Runs short gunboat matches with model seats beside two baselines, random
legal orders (`fake`) and holding everything (`hold`), rotating which powers
each kind plays, then scores every seat from the match files:

    finishing   movement phases whose first reply wasn't clean, so a finishing
                call followed: no orders, cut off, or any order refused
    refused     orders that could not be used (illegal or unparseable)
    held        movement phases that resolved with no orders from it at all
    missed      Fall: an empty centre it doesn't own that only it could reach,
                with a unit that could have moved there doing anything other
                than moving into a centre. An early-competence signal only, to
                retire once seats are basically competent: later, bounces and
                alliances make leaving a centre alone the right play.
    selfbounce  provinces where its own moves bounced off each other, or off
                its own unit that wasn't moving. Not a chain behind a failed
                attack. Ramp-up only, retired with missed: a deliberate
                self-bounce to deny a province is often the best play.
    void        supports that didn't match the supported unit's move
    unbuilt     builds left unused in a winter: open home centres it could have
                built on, up to its surplus of centres over units
    gain        supply centres at the end minus at the start

Nothing here rewards caution: leaving a centre undefended is not counted,
because penalising it pays seats to camp at home.

    .venv/bin/python -m bench.gunboat --model claude:haiku --games 3 --label before
    .venv/bin/python -m bench.gunboat --score game-1111-1700 --root ../host/games

The second form scores matches played anywhere, such as a human's games on
the host (their seats show as `human`), with the same metrics.

Developer tooling only: no seat ever sees any of this. Results are appended
to bench/RESULTS.md.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from vibe.game import MAPS, Match
from vibe.run import Runner, parse_seat

HERE = Path(__file__).resolve().parent
METRICS = ("finishing", "refused", "held", "missed", "selfbounce", "void", "unbuilt")


def _base(loc: str) -> str:
    return loc.split("/")[0]


def _reach(game, unit: str, prov: str) -> bool:
    kind, loc = unit.split()
    return any(game.map.abuts(kind, loc, "-", d) for d in game.map.locs
               if _base(d.upper()) == prov)


def _year(phase: str) -> int:
    return int(phase[1:5])


def score(match: Match, until: int | None = None) -> dict[str, dict]:
    """Per power: its seat kind, raw counts, and how many phases they cover.

    `until` scores only the phases up to the end of that year, with gain
    measured from the centres held then, so games of any length compare at
    the same cutoff.
    """
    game = match.load()
    players = match.config.get("players") or {}
    states = [(str(k), v) for k, v in game.state_history.items()]
    powers = match.powers
    now = {p: list(game.powers[p].centers) for p in powers}
    if until is not None:
        later = [st for ph, st in states if _year(ph) > until]
        states = [(ph, st) for ph, st in states if _year(ph) <= until]
        if later:
            now = later[0]["centers"]
    out = {p: {"kind": players.get(p, "?"), "moves": 0, "falls": 0, "winters": 0,
               **{m: 0 for m in METRICS},
               "gain": len(now.get(p) or []) - len(states[0][1]["centers"].get(p, []))}
           for p in powers}
    for phase, start in states:
        if phase.endswith("A"):
            orders = ((match.history(phase) or {}).get("orders") or {})
            for p in powers:
                centres, units = start["centers"].get(p, []), start["units"].get(p, [])
                taken = {u.split()[1][:3] for us in start["units"].values() for u in us}
                room = [h for h in start["homes"].get(p, []) if h in centres and h not in taken]
                can = min(len(centres) - len(units), len(room))
                if can > 0:
                    built = sum(o.endswith(" B") for o in orders.get(p) or [])
                    out[p]["winters"] += 1
                    out[p]["unbuilt"] += max(0, can - built)
            continue
        if not phase.endswith("M"):
            continue
        hist = match.history(phase) or {}
        results = hist.get("results") or {}
        units = start["units"]
        where = {_base(u.split()[1]): (p, u) for p, us in units.items() for u in us}
        fall = phase.startswith("F")
        for p in powers:
            if not units.get(p):
                continue
            s = out[p]
            s["moves"] += 1
            s["falls"] += fall
            orders = (hist.get("orders") or {}).get(p) or []
            s["refused"] += len((hist.get("refused") or {}).get(p) or [])
            rec = match.path / "log" / phase / f"{p}-orders.json"
            if rec.exists():
                s["finishing"] += len(json.loads(rec.read_text()).get("replies") or []) > 1
            s["held"] += not orders
            moves = {}
            stays = set()
            for o in orders:
                parts = o.split()
                unit = " ".join(parts[:2])
                if " S " in o and "void" in (results.get(unit) or []):
                    s["void"] += 1
                if len(parts) >= 4 and parts[2] == "-":
                    moves[unit] = _base(parts[3])
                else:
                    stays.add(_base(parts[1]))
            for u in units[p]:          # units with no order hold
                if u not in moves:
                    stays.add(_base(u.split()[1]))
            # One per province at most. A unit bouncing behind its own unit's
            # failed attack is that attack failing (a chain), not a self-bounce.
            hit = set()
            for u, dest in moves.items():
                if "bounce" not in (results.get(u) or []):
                    continue
                twin = any(d == dest and v != u for v, d in moves.items())
                blocker = where.get(dest)
                own_held = blocker and blocker[0] == p and blocker[1] not in moves
                if twin or own_held:
                    hit.add(dest)
            s["selfbounce"] += len(hit)
            if not fall:
                continue
            owned = {c for q, cs in start["centers"].items() if q == p for c in cs}
            for c in game.map.scs:
                if c in owned or c in where:
                    continue
                # Only a unit that took no centre this turn could have taken it:
                # one unit can take one centre.
                idle = [u for u in units[p] if moves.get(u) not in game.map.scs]
                mine = any(_reach(game, u, c) for u in idle)
                rivals = any(_reach(game, u, c) for q, us in units.items() if q != p
                             for u in us)
                if mine and not rivals and c not in moves.values():
                    s["missed"] += 1
    return out


def table(rows: list[dict]) -> str:
    """One line per seat kind: rates per movement (or Fall) phase, mean gain."""
    by = defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    head = ("| seats | n | finishing/phase | refused/phase | held/phase "
            "| missed/fall | selfbounce/phase | void/phase | unbuilt/winter | gain |")
    lines = [head, "|" + "---|" * 10]
    for kind, rs in sorted(by.items()):
        moves = sum(r["moves"] for r in rs) or 1
        falls = sum(r["falls"] for r in rs) or 1

        def per(m, n):
            return f"{sum(r[m] for r in rs) / n:.2f}"
        lines.append(f"| {kind} | {len(rs)} | {per('finishing', moves)} | "
                     f"{per('refused', moves)} | {per('held', moves)} | "
                     f"{per('missed', falls)} | "
                     f"{per('selfbounce', moves)} | {per('void', moves)} | "
                     f"{per('unbuilt', sum(r['winters'] for r in rs) or 1)} | "
                     f"{sum(r['gain'] for r in rs) / len(rs):+.2f} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", help="seat spec, e.g. claude:haiku")
    ap.add_argument("--score", nargs="+", metavar="MATCH",
                    help="only score these existing matches")
    ap.add_argument("--root", help="the games directory they are in")
    ap.add_argument("--until", type=int, metavar="YEAR",
                    help="score only up to the end of this year (compare games of any length)")
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--max-year", type=int, default=1902)
    ap.add_argument("--label", help="names this run in RESULTS.md")
    ap.add_argument("--models", type=int, default=3, help="model seats per game")
    ap.add_argument("--map", choices=list(MAPS), default="standard",
                    help="standard_france_austria: the 1v1 sandbox")
    ap.add_argument("--opponents", default="fake,hold",
                    help="baseline kinds for the other seats, in turn (e.g. fake)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--score-only", action="store_true",
                    help="score this label's existing matches again")
    args = ap.parse_args()
    if args.score:
        rows = [r for name in args.score
                for r in score(Match.open(name, root=Path(args.root) if args.root else None),
                               args.until).values()]
        print(table(rows))
        return 0
    if not (args.model and args.label):
        ap.error("--model and --label are needed to run games")
    rows = []
    for i in range(args.games):
        name = f"bench-{args.label}-{i + 1}"
        if args.score_only:
            match = Match.open(name)
        else:
            match = Match.create(name, max_year=args.max_year, map_name=args.map)
            ps = match.powers
            order = ps[i % len(ps):] + ps[:i % len(ps)]
            others = args.opponents.split(",")
            kinds = [args.model] * args.models + others * 7
            seats = {p: parse_seat(k, "", "") for p, k in zip(order, kinds)}
            with open(match.path / "progress.log", "a") as fh:
                def log(line, fh=fh):
                    fh.write(line + "\n")
                    fh.flush()
                Runner(match, seats, seed=args.seed + i, log=log).play()
            print(f"{name}: {match.ended()}", flush=True)
        rows += score(match).values()
    md = table(rows)
    print(md)
    with open(HERE / "RESULTS.md", "a") as fh:
        fh.write(f"\n## {args.label} — {time.strftime('%Y-%m-%d')}, {args.model}, "
                 f"{args.games} games to {args.max_year}"
                 f"{'' if args.map == 'standard' else ', ' + MAPS[args.map]}\n\n{md}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
