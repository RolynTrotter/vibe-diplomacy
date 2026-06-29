"""The programmatic conductor — run a whole 7-way match from one command.

    python -m orchestration.run_match --spec matches/frostbite.yaml
    python -m orchestration.run_match --name frostbite --press full \
        --model qwen/qwen3.6-35b-a3b --rounds 2 --max-phases 20

This replaces the manual "open seven `cc qwen` terminals" workflow. Each power
runs as a *separate headless Claude Code process* (see `player_agent.py`),
launched and supervised here. The conductor itself only:

  1. initializes the game (`new_game`, holding the adjudicator key for `local`),
  2. per phase: asks `conduct.roster` who must play, runs negotiation +
     orders rounds by dispatching each live power's `PlayerAgent`,
  3. adjudicates via `run_adjudication` (the exact same sealed/signed pipeline a
     distrusting 7-session game uses),
  4. writes transcripts to `runs/<name>/<phase>/<power>.json`.

Players never receive the adjudicator private key (env is scrubbed per seat), so
the produced artifacts are byte-identical to a distrusting game.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orchestration._common import POWERS, repo_root
from orchestration.conduct import roster as conduct_roster
from orchestration.match_spec import MatchSpec, SeatSpec
from orchestration.player_agent import AgentResult, make_agent

from engine import context, state


class Conductor:
    def __init__(self, spec: MatchSpec, repo_root: Path, game_root: Path | None = None,
                 backend: str = "headless", adjudicator_key: str | None = None):
        self.spec = spec
        self.repo_root = Path(repo_root)
        self.game_root = Path(game_root) if game_root else self.repo_root
        self.backend = backend
        self._key = adjudicator_key
        self.runs_base = self.game_root / spec.runs_dir / spec.name

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    def _log(self, msg: str, level: int = 1) -> None:
        if self.spec.verbosity >= level:
            print(msg, flush=True)

    # ------------------------------------------------------------------ #
    # Game setup
    # ------------------------------------------------------------------ #
    def init_game(self) -> None:
        if state.config_file(self.game_root).exists():
            self._log(f"Game already initialized at {self.game_root}.")
            if self.spec.adjudication == "local" and not self._key:
                self._key = os.environ.get("ADJUDICATOR_PRIVATE_KEY", "").strip() or None
            return

        args = ["--name", self.spec.name, "--press", self.spec.press,
                "--deadline-hours", str(self.spec.deadline_hours)]
        idle = self.spec.idle_powers()
        if idle:
            args += ["--idle", *idle]
        if self.spec.human:
            args += ["--human", *self.spec.human]

        proc = self._run_module("orchestration.new_game", args)
        if proc.returncode != 0:
            raise RuntimeError(f"new_game failed:\n{proc.stderr}")
        self._log(proc.stdout, level=2)

        # Capture the private key for local adjudication (held only by us).
        for line in proc.stdout.splitlines():
            if line.strip().startswith("Value:"):
                self._key = line.split("Value:", 1)[1].strip()
                break
        if self.spec.adjudication == "local" and not self._key:
            raise RuntimeError("Could not capture adjudicator private key from new_game.")

    def _run_module(self, module: str, args: list[str], stdin: str | None = None,
                    env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", module, "--root", str(self.game_root), *args],
            cwd=self.repo_root, input=stdin, text=True, capture_output=True, env=env,
        )

    # ------------------------------------------------------------------ #
    # Agents
    # ------------------------------------------------------------------ #
    def _agent(self, power: str) -> "PlayerAgent":  # noqa: F821
        seat = self.spec.seats[power]
        return make_agent(self.backend, power, seat, self.repo_root,
                          self.game_root, self.spec)

    # Persistent-mode agents must outlive a single phase to keep their
    # session_id, so cache them.
    def _persistent_agents(self) -> dict:
        if not hasattr(self, "_agent_cache"):
            self._agent_cache = {p: self._agent(p) for p in self.spec.live_powers()}
        return self._agent_cache

    def _agent_for(self, power: str):
        if self.spec.session_mode == "persistent":
            return self._persistent_agents()[power]
        return self._agent(power)

    # ------------------------------------------------------------------ #
    # The phase loop
    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        if self.spec.dry_run:
            return self._dry_run()

        self.init_game()
        summary = {"name": self.spec.name, "press": self.spec.press,
                   "backend": self.backend, "phases": []}

        for _ in range(self.spec.max_phases):
            rs = conduct_roster(self.game_root)
            if rs["done"]:
                self._log("Game over.")
                break

            phase = rs["phase"]
            self._log(f"\n=== {phase} ({rs['phase_type']}) ===")
            to_play = [p for p in rs["to_play"] if self.spec.seats[p].enabled]

            phase_rec = {"phase": phase, "phase_type": rs["phase_type"],
                         "to_play": to_play, "dispatches": []}

            if to_play:
                if (self.spec.press == "full" and rs["phase_type"] == "M"
                        and self.spec.negotiation_rounds > 0):
                    for rnd in range(self.spec.negotiation_rounds):
                        self._log(f"  -- negotiation round {rnd + 1} --")
                        phase_rec["dispatches"] += self._dispatch_round(
                            to_play, "negotiation", phase, rnd)
                phase_rec["dispatches"] += self._dispatch_round(
                    to_play, "orders", phase)

            self._adjudicate(rs)
            summary["phases"].append(phase_rec)

        summary["final"] = self._final_standings()
        self._write_summary(summary)
        return summary

    def _dispatch_round(self, powers: list[str], kind: str, phase: str,
                        rnd: int | None = None) -> list[dict]:
        """Dispatch one task to each power, honoring max_concurrency."""
        def work(power: str) -> dict:
            agent = self._agent_for(power)
            task = self._build_task(power, kind, phase)
            result = agent.dispatch(task, kind=kind)
            self._write_transcript(phase, power, kind, rnd, result)
            tag = "ok" if result.ok else f"FAIL ({result.error})"
            self._log(f"  {power:<8} {kind:<11} -> {tag}")
            return {"power": power, "kind": kind, "round": rnd,
                    "ok": result.ok, "error": result.error,
                    "duration": round(result.duration, 2)}

        if self.spec.max_concurrency <= 1:
            return [work(p) for p in powers]
        with ThreadPoolExecutor(max_workers=self.spec.max_concurrency) as pool:
            return list(pool.map(work, powers))

    # ------------------------------------------------------------------ #
    # Task text (what a real headless session receives)
    # ------------------------------------------------------------------ #
    def _build_task(self, power: str, kind: str, phase: str) -> str:
        seat = self.spec.seats[power]
        persona = f"Persona: {seat.persona}\n\n" if seat.persona else ""
        brief = context.power_brief(self.game_root, power)
        full = self.spec.press == "full"

        if kind == "negotiation":
            body = (
                f"You are {power} in a Diplomacy match. {persona}"
                f"It is {phase} and the negotiation window is open. Acting ONLY as "
                f"{power}, read your inbox and send any messages you want before "
                "orders lock. Do NOT submit orders yet.\n\n"
                "Use the `negotiate` skill: read with `read_messages`, send with "
                "`send_message`, then `scripts/sync.sh` any mail you create.\n\n"
            )
        else:
            steps = ["1. `scripts/turn.sh {p}` — pull state and read your full brief."]
            if full:
                steps.append("2. (Optional) negotiate first — see the `negotiate` skill.")
            steps.append("3. Decide your moves, then submit them in one shot:\n"
                         "     echo \"A PAR - BUR\\nF BRE - MAO\" | scripts/submit.sh {p}")
            steps.append("4. Update notes/{p}.md with your plan, then `scripts/sync.sh`.")
            body = (
                f"You are {power} in a Diplomacy match. {persona}"
                f"It is {phase}. Play this turn end-to-end acting ONLY as {power}.\n\n"
                + "\n".join(s.format(p=power) for s in steps)
                + "\n\n"
            )
        return body + "Your current brief:\n\n" + brief

    # ------------------------------------------------------------------ #
    # Adjudication
    # ------------------------------------------------------------------ #
    def _adjudicate(self, rs: dict) -> None:
        if self.spec.adjudication == "ci":
            self._adjudicate_ci(rs)
            return

        env = dict(os.environ)
        env["ADJUDICATOR_PRIVATE_KEY"] = self._key or ""
        # Programmatic local runs always force: a power that fails to submit (or
        # submits nothing) falls back to engine defaults (holds / civil disorder)
        # so the sequential loop can never hang waiting on a straggler.
        proc = self._run_module("orchestration.run_adjudication", ["--force"], env=env)
        self._log(proc.stdout.strip(), level=2)
        if proc.returncode != 0:
            raise RuntimeError(f"adjudication failed:\n{proc.stderr}")

    def _adjudicate_ci(self, rs: dict) -> None:
        """Push the branch and let GitHub Actions adjudicate.

        Experimental: assumes the game branch has an origin and the
        `adjudicate.yml` workflow is configured with the repo secret. We push,
        then poll until the phase advances.
        """
        import time
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                cwd=self.game_root, text=True,
                                capture_output=True).stdout.strip()
        subprocess.run(["git", "add", "-A"], cwd=self.game_root)
        subprocess.run(["git", "commit", "-m", f"{rs['phase']} orders"],
                       cwd=self.game_root, capture_output=True)
        subprocess.run(["git", "push", "origin", branch], cwd=self.game_root)
        self._log(f"Pushed {branch}; waiting for Actions to adjudicate {rs['phase']}…")
        for _ in range(60):
            time.sleep(10)
            subprocess.run(["git", "pull", "--rebase", "origin", branch],
                           cwd=self.game_root, capture_output=True)
            if conduct_roster(self.game_root)["phase"] != rs["phase"]:
                return
        raise RuntimeError(f"CI adjudication timed out on {rs['phase']}.")

    # ------------------------------------------------------------------ #
    # Artifacts
    # ------------------------------------------------------------------ #
    def _write_transcript(self, phase: str, power: str, kind: str,
                          rnd: int | None, result: AgentResult) -> None:
        d = self.runs_base / phase
        d.mkdir(parents=True, exist_ok=True)
        suffix = f"-{kind}{rnd}" if kind == "negotiation" else ""
        path = d / f"{power}{suffix}.json"
        path.write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")

    def _final_standings(self) -> dict:
        from engine import query
        game = state.load_game(self.game_root)
        summary = query.board_summary(game)
        return {n: {"centers": i["center_count"], "units": i["unit_count"]}
                for n, i in summary["powers"].items()}

    def _write_summary(self, summary: dict) -> None:
        self.runs_base.mkdir(parents=True, exist_ok=True)
        (self.runs_base / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        self._log(f"\nRun summary -> {self.runs_base / 'summary.json'}")
        for name, p in sorted(summary["final"].items(),
                              key=lambda kv: -kv[1]["centers"]):
            self._log(f"  {name:<8} {p['centers']:>2} centers, {p['units']:>2} units")

    # ------------------------------------------------------------------ #
    # Dry run
    # ------------------------------------------------------------------ #
    def _dry_run(self) -> dict:
        self._log("DRY RUN — resolved plan:\n")
        self._log(self.spec.to_yaml())
        intended = []
        live = self.spec.live_powers()
        if (self.spec.press == "full" and self.spec.negotiation_rounds > 0):
            for rnd in range(self.spec.negotiation_rounds):
                intended += [{"power": p, "kind": "negotiation", "round": rnd}
                             for p in live]
        intended += [{"power": p, "kind": "orders"} for p in live]
        self._log("Intended dispatches for the first movement phase "
                  f"({self.backend} backend):")
        for d in intended:
            r = f" r{d['round']}" if "round" in d else ""
            self._log(f"  {d['power']:<8} {d['kind']}{r}")
        self._log("\n(dry run — nothing dispatched, no game initialized.)")
        return {"dry_run": True, "intended": intended, "plan": self.spec.to_dict()}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_seat_overrides(items: list[str]) -> dict:
    """Parse repeated --seat POWER.field=value into {POWER: {field: value}}."""
    out: dict[str, dict] = {}
    for item in items or []:
        if "." not in item or "=" not in item:
            raise SystemExit(f"--seat must look like POWER.field=value, got {item!r}")
        locator, _, value = item.partition("=")
        power, _, fieldname = locator.partition(".")
        power, fieldname = power.strip().upper(), fieldname.strip()
        if fieldname == "enabled":
            coerced: object = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            coerced = value.strip()
        out.setdefault(power, {})[fieldname] = coerced
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run a whole Diplomacy match programmatically.")
    p.add_argument("--spec", help="Path to a match YAML spec.")
    p.add_argument("--root", help="Game root (default: cwd).")
    p.add_argument("--backend", default="headless", choices=["headless", "fake"],
                   help="Player backend (fake = server-free, random legal orders).")
    p.add_argument("--print-plan", action="store_true",
                   help="Resolve the spec and print it, then exit (run nothing).")

    # Spec fields (all override the YAML; unset flags leave the YAML alone).
    p.add_argument("--name")
    p.add_argument("--press", choices=["none", "full"])
    p.add_argument("--idle", nargs="*")
    p.add_argument("--human", nargs="*")
    p.add_argument("--model")
    p.add_argument("--endpoint", choices=["local", "api"])
    p.add_argument("--rounds", dest="negotiation_rounds", type=int)
    p.add_argument("--session-mode", dest="session_mode", choices=["oneshot", "persistent"])
    p.add_argument("--max-concurrency", dest="max_concurrency", type=int)
    p.add_argument("--max-phases", dest="max_phases", type=int)
    p.add_argument("--adjudication", choices=["local", "ci"])
    p.add_argument("--deadline", choices=["wait", "force"])
    p.add_argument("--per-call-timeout", dest="per_call_timeout_s", type=float)
    p.add_argument("--retries", type=int)
    p.add_argument("--runs-dir", dest="runs_dir")
    p.add_argument("--verbosity", type=int)
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=None)
    p.add_argument("--seat", action="append", default=[],
                   help="Per-seat override, e.g. --seat FRANCE.persona='cautious'.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    spec_overrides = {
        k: getattr(args, k) for k in (
            "name", "press", "idle", "human", "model", "endpoint",
            "negotiation_rounds", "session_mode", "max_concurrency", "max_phases",
            "adjudication", "deadline", "per_call_timeout_s",
            "retries", "runs_dir", "verbosity", "dry_run",
        )
    }
    spec_overrides["seats"] = _parse_seat_overrides(args.seat)
    spec = MatchSpec.load(args.spec, **spec_overrides)

    if args.print_plan:
        print(spec.to_yaml())
        return 0

    # The code repo (where the orchestration modules live) is the subprocess cwd;
    # game state lives at --root (defaults to cwd, which for a real in-repo run is
    # the same directory).
    code_root = Path(__file__).resolve().parent.parent
    conductor = Conductor(spec, code_root, game_root=repo_root(args.root),
                          backend=args.backend)
    conductor.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
