"""Self-play harness: drive a whole match through the real CLIs.

This plays all seven powers itself to generate a plausible order history and to
exercise the full sealed-order pipeline end-to-end:

    new_game  ->  (suggest/curated orders) ->  submit_orders (validate + seal)
              ->  run_adjudication (decrypt + process + reveal)  ->  repeat

It uses hand-authored 1901 openings for plausibility, then falls back to the
heuristic suggester for later phases. The adjudicator private key is generated
by new_game and held only in this process's environment, exactly as the real
GitHub Action holds it as a repo secret.

Usage:
    python scripts/self_play.py --name proving-ground --adjudications 14
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]

# Well-known opening moves — gives the history a realistic feel before the
# heuristic takes over. Some are deliberate bounces (GAL, BLA), as in real play.
OPENINGS = {
    "S1901M": {
        "AUSTRIA": ["A VIE - GAL", "A BUD - SER", "F TRI - ALB"],
        "ENGLAND": ["F LON - NTH", "F EDI - NWG", "A LVP - YOR"],
        "FRANCE":  ["F BRE - MAO", "A PAR - BUR", "A MAR - SPA"],
        "GERMANY": ["A BER - KIE", "A MUN - RUH", "F KIE - DEN"],
        "ITALY":   ["A VEN - TYR", "A ROM - VEN", "F NAP - ION"],
        "RUSSIA":  ["A MOS - UKR", "A WAR - GAL", "F SEV - BLA", "F STP/SC - BOT"],
        "TURKEY":  ["A CON - BUL", "A SMY - CON", "F ANK - BLA"],
    },
}


def run(module: str, args: list[str], stdin: str | None = None,
        env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-m", module, *args],
        cwd=ROOT, input=stdin, text=True, capture_output=True, env=env,
    )


def init_game(name: str) -> str:
    """Initialize the match; return the adjudicator private key."""
    proc = run("orchestration.new_game", ["--name", name])
    print(proc.stdout)
    if proc.returncode != 0:
        sys.exit(f"new_game failed:\n{proc.stderr}")
    for line in proc.stdout.splitlines():
        if line.strip().startswith("Value:"):
            return line.split("Value:", 1)[1].strip()
    sys.exit("Could not find private key in new_game output.")


def status() -> dict:
    proc = run("orchestration.game_status", ["--json"])
    return json.loads(proc.stdout)


def orders_for(power: str, phase: str) -> list[str]:
    """Curated opening if available, else heuristic suggestions."""
    if phase in OPENINGS and power in OPENINGS[phase]:
        return OPENINGS[phase][power]
    proc = run("orchestration.suggest_orders", ["--power", power, "--json"])
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout).get("orders", [])


def play_phase(phase: str, live: list[str]) -> None:
    for power in live:
        orders = orders_for(power, phase)
        if not orders:
            continue
        proc = run("orchestration.submit_orders", ["--power", power],
                   stdin="\n".join(orders))
        tag = "ok" if proc.returncode == 0 else f"SKIP ({proc.returncode})"
        print(f"  {power:<8} {len(orders)} orders -> {tag}")
        if proc.returncode != 0:
            print("    " + proc.stderr.strip().replace("\n", "\n    "))


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-play a full match.")
    parser.add_argument("--name", default="proving-ground")
    parser.add_argument("--adjudications", type=int, default=14,
                        help="How many phases to process.")
    args = parser.parse_args()

    priv = init_game(args.name)
    env = {**os.environ, "ADJUDICATOR_PRIVATE_KEY": priv}

    # Claim every seat so each power can sign its orders (the adjudicator now
    # verifies signatures, so e.g. France can't submit Germany's orders).
    for power in POWERS:
        run("orchestration.join_game", ["--power", power])

    for i in range(args.adjudications):
        st = status()
        if st["done"]:
            print("Game over.")
            break
        phase = st["phase"]
        live = [n for n, p in st["powers"].items() if p["type"] != "idle"]
        print(f"\n=== {phase} ({st['phase_type']}) ===")
        play_phase(phase, live)

        adj = run("orchestration.run_adjudication", ["--force"], env=env)
        print(adj.stdout.strip())
        if adj.returncode != 0:
            sys.exit(f"adjudication failed:\n{adj.stderr}")

    final = status()
    print("\n=== FINAL STANDINGS ===")
    for name, p in sorted(final["powers"].items(),
                          key=lambda kv: -kv[1]["centers"]):
        print(f"  {name:<8} {p['centers']:>2} centers, {p['units']:>2} units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
