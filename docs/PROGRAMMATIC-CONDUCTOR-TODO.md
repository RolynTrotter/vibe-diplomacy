# TODO — Programmatic conductor with independent player-agent sessions

**For the Claude Code instance implementing this.** Goal: replace the manual
"open seven `cc qwen` terminals" workflow with a single programmatic
orchestration layer that *spins off its own independent player sessions*. A
human (or an Opus session) should be able to describe a match variation in plain
language; every knob that variation needs must already exist as a lever in the
script.

Work on a feature branch off `main`. Reuse the engine — do not reimplement rules,
adjudication, sealing, or signing.

## Outcome

```bash
# one command sets up and runs a whole 7-way game; no extra terminals
python -m orchestration.run_match --spec matches/frostbite.yaml
# or with inline overrides
python -m orchestration.run_match --name frostbite --press full \
    --model qwen/qwen3.6-35b-a3b --rounds 2 --max-phases 20
```

Each power runs as a **separate headless Claude Code process** (its own
`claude -p` against LM Studio), launched, supervised, and torn down by the
conductor — effectively independent agents, not in-process subagents. This is
the only way to get a real per-power Qwen, because `ANTHROPIC_BASE_URL` is
session-wide for native/callstack subagents (per-agent provider routing is not a
shipped Claude Code feature).

## Hard constraints

- **Reuse the pipeline.** Players act through the real CLIs (`join_game`,
  `scripts/submit.sh`, `send_message`, `read_messages`, `scripts/sync.sh`) and
  the conductor adjudicates via `orchestration.run_adjudication`. Artifacts must
  be byte-identical to a distrusting 7-session game.
- **Secrets isolation.** Player processes must NEVER receive
  `ADJUDICATOR_PRIVATE_KEY` or anything under `secrets/`. Scrub the env you hand
  to a player. The conductor holds the private key only for the adjudication
  call.
- **Single LM Studio instance** serves all seats by default → dispatch is
  **sequential** unless `max_concurrency > 1` is explicitly set. Do not assume
  parallelism.
- `main` stays infra-only; all game state lives on `game/<name>`.

## Architecture

Add two modules and a spec format. Keep the existing `conduct.py` roster/brief
CLI as the deterministic substrate; the new code orchestrates on top of it.

### 1. `orchestration/match_spec.py` — the levers
A `MatchSpec` dataclass + loader (YAML file, with CLI flags overriding). Every
lever the human might describe in plain language lives here:

- `name`, `press` (`none|full`), `idle` (list of powers)
- `seats`: per-power overrides, each optional:
  - `model` (default `qwen/qwen3.6-35b-a3b`)
  - `endpoint` (`local` → LM Studio from `setup_lm_studio/lmstudio.env`; `api` →
    Anthropic/subscription, no base-url override) and resolved `base_url`/`token`
  - `persona` (free-text system flavor prepended to that seat's prompts)
  - `enabled` (default true)
- `negotiation_rounds` (int; only applied on movement phases, full-press)
- `session_mode`: `oneshot` (stateless, fresh context each call) or
  `persistent` (capture each player's `session_id` from `--output-format json`
  and `--resume` it every turn so the agent keeps its own memory/persona)
- `max_concurrency` (default 1)
- `max_phases`, `adjudication` (`local` using the held key, or `ci` = push and
  let Actions run), `deadline` behavior (`wait|force`)
- `seed_openings` (use the curated S1901M openings from `scripts/self_play.py`
  for realism, or let agents decide from move one)
- `per_call_timeout_s`, `retries`
- `runs_dir` (default `runs/`), `verbosity`, `dry_run`

Provide `MatchSpec.load(path, **overrides)` and a `--print-plan` that dumps the
fully-resolved spec without running.

### 2. `orchestration/player_agent.py` — independent session backend
A `PlayerAgent` abstraction the conductor uses to run one power's task:

- `class PlayerAgent` with `dispatch(task: str) -> AgentResult` where
  `AgentResult` carries `reply`, `transcript`, `session_id`, `ok`, `duration`.
- Default backend `HeadlessClaudeAgent`: runs
  `claude -p --model <model> --dangerously-skip-permissions
  --output-format json` via `subprocess`, `cwd=repo_root`, with a **scrubbed
  per-seat env** (set `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for `local`
  seats, unset them for `api` seats, always drop `ADJUDICATOR_PRIVATE_KEY`, set
  `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1`). Parse the JSON to get `session_id`
  (for `persistent` mode, pass `--resume <id>` on subsequent calls). Enforce
  `per_call_timeout_s` and `retries`.
- Make the backend pluggable (a `FakeAgent` is required for tests — see below).
  Leave room for a future raw `/v1/messages` backend.
- The existing `setup_lm_studio/ask-local` is the reference behavior; this is its
  programmatic, supervised equivalent. You may shell out to it, but a direct
  `subprocess` call you fully control is preferred.

### 3. `orchestration/run_match.py` — the conductor loop
Drives the phase loop using `conduct.roster`, `conduct brief`, and
`run_adjudication`. Per phase:

1. `roster()` → if `done`, finish; if `to_play == []`, adjudicate immediately.
2. (movement + full-press only) run `negotiation_rounds`: for each live power,
   build `brief` + the negotiation task text, `dispatch` via its `PlayerAgent`,
   commit `mail/` between rounds.
3. Orders round: fresh `brief` per power, dispatch the orders task (claim seat →
   `scripts/submit.sh P` → update notes → `scripts/sync.sh`).
4. Adjudicate (`local`: inline `ADJUDICATOR_PRIVATE_KEY` only on this call; `ci`:
   push the branch).
5. Honor `max_concurrency` via a worker pool; honor `dry_run` (print intended
   dispatches, run nothing).
6. Write transcripts to `runs/<name>/<phase>/<power>.json` and a run summary.

Keep a thin CLI (argparse) mirroring the spec fields so everything is reachable
without a YAML file.

## The plain-language UX (why the levers matter)
The human-facing Opus session translates requests into spec edits + a run, e.g.:

- "Give France a cautious persona, 3 talk rounds" → `seats.FRANCE.persona`,
  `negotiation_rounds=3`.
- "Make Germany play on Opus instead of Qwen" → `seats.GERMANY.model=claude-opus-4-8`,
  `endpoint=api`.
- "Gunboat, fast" → `press=none`, `negotiation_rounds=0`.
- "Let them remember between turns" → `session_mode=persistent`.
- "Two Qwens in parallel" → `max_concurrency=2` (and raise LM Studio's max
  concurrent requests).

So: keep flags/spec exhaustive and orthogonal; the NL layer is just mapping.

## Tests (required — must run without LM Studio)
- `FakeAgent` backend that ignores the prompt and submits orders from the
  heuristic suggester (`orchestration.suggest_orders`) / curated openings —
  mirror `scripts/self_play.py`. This makes the full loop deterministic and CI-safe.
- Test: a full short match with `FakeAgent` reaches `done` or `max_phases` and
  produces valid sealed/signed artifacts identical in shape to `self_play.py`.
- Test: env scrubbing — assert `ADJUDICATOR_PRIVATE_KEY` is absent from the env
  passed to any `PlayerAgent`, and that `local` vs `api` seats get the right
  `ANTHROPIC_BASE_URL` (set vs unset).
- Test: `--print-plan` / `--dry-run` dispatch nothing.
- `pytest -q` green before committing.

## Acceptance criteria
- [ ] `python -m orchestration.run_match --spec matches/<name>.yaml` runs a whole
      game, spawning one independent headless session per power, no extra
      terminals.
- [ ] Every lever above is reachable by flag and by YAML.
- [ ] One live smoke run against LM Studio with `qwen/qwen3.6-35b-a3b` completes
      at least S1901M for all seven powers (sequential).
- [ ] Players never see the adjudicator private key; artifacts match the
      distrusting-session format.
- [ ] Heuristic-backed test match is green in CI without any model server.
- [ ] Short note in `docs/RUNBOOK.md` pointing to `run_match` as the
      single-operator path, and an example `matches/example.yaml`.

## Pointers
- Roster/brief: `python -m orchestration.conduct roster|brief --power P`
  (`orchestration/conduct.py`).
- Status JSON shape: `orchestration/game_status.py::collect`.
- Adjudication: `orchestration/run_adjudication.py` (needs
  `ADJUDICATOR_PRIVATE_KEY` for `local`).
- Submit/sync/turn helpers self-activate `.venv` (`scripts/*.sh`).
- Reference headless-Qwen launcher + env handling:
  `~/agentic_work/setup_lm_studio/ask-local` and `cc-launcher.zsh`.
- Curated openings + heuristic fallback: `scripts/self_play.py`.
