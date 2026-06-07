# CLAUDE.md — working in this repo

Vibe Diplomacy: a Diplomacy environment for AI agents. Read `README.md` for the
architecture and `docs/RUNBOOK.md` for running a match.

## Two contexts

1. **Developing the engine/skills** (this kind of session): work on `main` (or a
   feature branch). Run the test suite before committing.
2. **Playing a match** (an in-game session): you are ONE power on ONE
   `game/<name>` branch. Use the `play-a-turn` skill. Commit only your own
   `orders/<POWER>/<phase>.enc` and `notes/<POWER>.md`. Never read or write other
   powers' files, `state/`, `history/`, or `game/`.

## Golden rules

- **Reuse the engine.** All rules logic comes from the `diplomacy` package via
  `engine/`. Do not reimplement adjudication or hand-parse orders.
- **Order secrecy is sacred.** Pending orders are sealed to the adjudicator
  public key (`engine/crypto.py`). The private key exists ONLY in the
  `ADJUDICATOR_PRIVATE_KEY` GitHub Actions secret and is read ONLY by
  `orchestration/run_adjudication.py`. Never log, commit, or expose it.
- **`main` is infra-only.** Game state (`state/`, `orders/`, `history/`, `game/`)
  exists only on `game/<name>` branches.

## Setup & tests

```bash
./scripts/setup.sh && source .venv/bin/activate
pytest -q
```

The `diplomacy` package is pinned (`requirements.txt`) and verified to run on
Python 3.11.

## Layout (see README for detail)

- `engine/` — thin wrapper: `state`, `adjudicate`, `validate`, `query`,
  `crypto`, `suggest`.
- `orchestration/` — CLIs: `new_game`, `submit_orders`, `game_status`,
  `run_adjudication`, `suggest_orders`.
- `.claude/skills/` — agent-facing skills.
- `.github/workflows/adjudicate.yml` — the serverless adjudicator.

## Roadmap

The approved plan lives outside the repo. Current state: **Epics 0–2 built**
(engine wrapper, gunboat git+Actions loop, core skills). Next: human-play
ergonomics (Epic 3), GitHub Pages map (Epic 4), full-press comms with per-player
encryption (Epic 5), real Cicero (Epic 6).
