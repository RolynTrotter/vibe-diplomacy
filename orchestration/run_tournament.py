"""The tournament harness — N games back-to-back, scored on more than centers.

    python -m orchestration.run_tournament --spec matches/example.yaml \
        --games 4 --backend raw --root /tmp/tourney

Each game runs through the ordinary `Conductor` in its own directory
(`<root>/<name>-g<N>/`), producing the same signed/sealed artifacts as any
single match. Between games the seat assignments ROTATE one power (disable
with --no-rotate), so over 7 games no model is stuck opening as Austria.

Scoring reads the revealed `history/` of each finished game and reports,
per power AND per seat (model+persona, stable across rotation):

  centers / survival / solo wins    the classic outcome
  void_rate                         provably wasted orders (void supports +
                                    convoys that never happened) / all orders
  warning_rate                      orders that DEPENDED on someone else's
                                    simultaneous order or self-bounced — the
                                    coherence module's warning class. High is
                                    not necessarily bad (self-bounces are a
                                    real tactic); high AND high void_rate is.
  bounce_rate                       failed moves / all orders

`void_rate` is the play-quality metric that separated weak from capable
models in past games (51% vs 0.7%); watch it fall as prompts improve.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path

from orchestration._common import POWERS, repo_root
from orchestration.match_spec import MatchSpec
from orchestration.run_match import Conductor, build_parser as match_parser

from engine.coherence import parse_order

WIN_CENTERS = 18


def rotated_seats(seats: dict, shift: int) -> dict:
    """Shift the seat specs around the table: game N gives POWERS[i] the seat
    POWERS[(i + shift) % 7] had in game 1."""
    n = len(POWERS)
    return {POWERS[i]: seats[POWERS[(i + shift) % n]] for i in range(n)}


def seat_key(seat) -> str:
    """Stable identity of a seat across rotation: model (+persona)."""
    key = seat.model
    if seat.persona:
        key += f" | {seat.persona[:40]}"
    return key


# --------------------------------------------------------------------------- #
# Order-quality scoring from revealed history
# --------------------------------------------------------------------------- #
def order_quality(game_root: Path) -> dict[str, dict]:
    """Per-power order-quality counters from every resolved movement phase."""
    counters: dict[str, dict] = {
        p: {"orders": 0, "void": 0, "no_convoy": 0, "bounce": 0,
            "dislodged": 0, "self_bounces": 0, "cross_deps": 0}
        for p in POWERS
    }
    hist = sorted((game_root / "history").glob("*.json")) \
        if (game_root / "history").exists() else []
    for path in hist:
        rec = json.loads(path.read_text(encoding="utf-8"))
        if not rec.get("phase", "").endswith("M"):
            continue
        orders = rec.get("orders") or {}
        results = rec.get("results") or {}
        for power, olist in orders.items():
            c = counters.setdefault(power, defaultdict(int))
            own_locs = set()
            parsed = []
            for o in olist or []:
                p = parse_order(o)
                parsed.append(p)
                if p.loc:
                    own_locs.add(p.loc)
            dests: dict[str, int] = defaultdict(int)
            for p in parsed:
                c["orders"] += 1
                unit = " ".join(p.raw.split()[:2])
                tags = [str(t) for t in results.get(unit, []) if str(t)]
                if "void" in tags:
                    c["void"] += 1
                if "no convoy" in tags:
                    c["no_convoy"] += 1
                if "bounce" in tags:
                    c["bounce"] += 1
                if "dislodged" in tags:
                    c["dislodged"] += 1
                if p.kind == "MOVE":
                    dests[p.dest] += 1
                if (p.kind in ("SUP_M", "CONVOY")
                        and p.target and p.target not in own_locs):
                    c["cross_deps"] += 1
            for dest, movers in dests.items():
                if movers > 1:
                    c["self_bounces"] += movers
    return counters


def _rates(c: dict) -> dict:
    n = c["orders"] or 1
    return {
        **c,
        "void_rate": round((c["void"] + c["no_convoy"]) / n, 4),
        "warning_rate": round((c["self_bounces"] + c["cross_deps"]) / n, 4),
        "bounce_rate": round(c["bounce"] / n, 4),
    }


# --------------------------------------------------------------------------- #
# The tournament loop
# --------------------------------------------------------------------------- #
def run_tournament(spec: MatchSpec, games: int, rotate: bool, backend: str,
                   base_root: Path, code_root: Path) -> dict:
    base_root = Path(base_root)
    base_root.mkdir(parents=True, exist_ok=True)
    tournament = {"name": spec.name, "games": [], "backend": backend,
                  "rotate": rotate}

    for g in range(games):
        gspec = copy.deepcopy(spec)
        gspec.name = f"{spec.name}-g{g + 1}"
        if rotate and g:
            gspec.seats = rotated_seats(spec.seats, g)
        groot = base_root / gspec.name
        groot.mkdir(parents=True, exist_ok=True)

        print(f"\n##### game {g + 1}/{games}: {gspec.name} #####", flush=True)
        summary = Conductor(gspec, code_root, game_root=groot,
                            backend=backend).run()

        quality = order_quality(groot)
        final = summary.get("final") or {}
        top = max((v["centers"] for v in final.values()), default=0)
        record = {"name": gspec.name, "root": str(groot), "powers": {}}
        for power in POWERS:
            centers = final.get(power, {}).get("centers", 0)
            record["powers"][power] = {
                "seat": seat_key(gspec.seats[power]),
                "centers": centers,
                "survived": centers > 0,
                "topped": centers == top and top > 0,
                "won": centers >= WIN_CENTERS,
                **_rates(quality.get(power, {"orders": 0})),
            }
        tournament["games"].append(record)

    tournament["by_power"] = _aggregate(tournament["games"], "power")
    tournament["by_seat"] = _aggregate(tournament["games"], "seat")

    out = base_root / f"{spec.name}-tournament.json"
    out.write_text(json.dumps(tournament, indent=2), encoding="utf-8")
    print(f"\nTournament summary -> {out}\n")
    _print_table(tournament["by_seat" if rotate else "by_power"])
    return tournament


def _aggregate(games: list[dict], by: str) -> dict:
    """Average the per-game records, grouped by power name or seat key."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for game in games:
        for power, rec in game["powers"].items():
            groups[power if by == "power" else rec["seat"]].append(rec)
    out = {}
    for key, recs in groups.items():
        n = len(recs)
        orders = sum(r["orders"] for r in recs)
        wasted = sum(r["void"] + r["no_convoy"] for r in recs)
        warned = sum(r["self_bounces"] + r["cross_deps"] for r in recs)
        out[key] = {
            "games": n,
            "wins": sum(r["won"] for r in recs),
            "topped": sum(r["topped"] for r in recs),
            "survival_rate": round(sum(r["survived"] for r in recs) / n, 3),
            "avg_centers": round(sum(r["centers"] for r in recs) / n, 2),
            "orders": orders,
            "void_rate": round(wasted / (orders or 1), 4),
            "warning_rate": round(warned / (orders or 1), 4),
            "bounce_rate": round(sum(r["bounce"] for r in recs) / (orders or 1), 4),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["avg_centers"]))


def _print_table(agg: dict) -> None:
    header = (f"{'seat/power':<44} {'g':>2} {'win':>3} {'top':>3} "
              f"{'surv':>5} {'ctrs':>5} {'void%':>6} {'warn%':>6} {'bnc%':>6}")
    print(header)
    print("-" * len(header))
    for key, a in agg.items():
        print(f"{key:<44} {a['games']:>2} {a['wins']:>3} {a['topped']:>3} "
              f"{a['survival_rate']:>5.0%} {a['avg_centers']:>5.1f} "
              f"{a['void_rate']:>6.1%} {a['warning_rate']:>6.1%} "
              f"{a['bounce_rate']:>6.1%}")


# --------------------------------------------------------------------------- #
# CLI (run_match's flags + tournament levers)
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = match_parser()
    p.description = "Run a whole tournament: N matches, rotated seats, scored."
    p.add_argument("--games", type=int, default=3,
                   help="Number of games to play (default 3).")
    p.add_argument("--no-rotate", dest="rotate", action="store_false",
                   default=True,
                   help="Keep every seat on the same power in every game.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from orchestration.run_match import _parse_seat_overrides

    spec_overrides = {
        k: getattr(args, k) for k in (
            "name", "press", "idle", "human", "model", "endpoint",
            "negotiation_rounds", "session_mode", "max_concurrency", "max_phases",
            "end_year", "adjudication", "deadline", "per_call_timeout_s",
            "retries", "runs_dir", "verbosity", "dry_run",
        )
    }
    spec_overrides["seats"] = _parse_seat_overrides(args.seat)
    spec = MatchSpec.load(args.spec, **spec_overrides)

    if args.print_plan:
        print(spec.to_yaml())
        return 0

    code_root = Path(__file__).resolve().parent.parent
    run_tournament(spec, games=args.games, rotate=args.rotate,
                   backend=args.backend, base_root=repo_root(args.root),
                   code_root=code_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
