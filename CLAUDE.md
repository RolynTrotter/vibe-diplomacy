# CLAUDE.md — working in this repo

Vibe Diplomacy: a Diplomacy environment for AI agents. Read `README.md` for the
architecture and `docs/RUNBOOK.md` for running a match.

## Two contexts

1. **Developing the engine/skills** (this kind of session): work on `main` (or a
   feature branch). Run the test suite before committing.
2. **Playing a match** (an in-game session): you are ONE power on ONE
   `game/<name>` branch. Start with `start-playing` (claims a free seat), then
   `play-a-turn` each phase. Commit only your own `players/<POWER>.json`,
   `orders/<POWER>/<phase>.enc`, `notes/<POWER>.md`, and (full-press) the
   `mail/*.enc` you create. Never read or write other powers' files, `state/`,
   `history/`, or `game/`. Your private keys live in `secrets/` (gitignored) —
   never commit them.
3. **Conducting a match** (one session): use the `conduct-match` skill to spawn
   every power as a scoped subagent and run a whole game yourself (self-play /
   evaluation / sandbox). Here isolation between powers is enforced by context
   boundaries, not crypto — use seven `start-playing` sessions for distrusting
   play. The two compose; the signed/sealed pipeline is identical.

## Golden rules

- **Reuse the engine.** All rules logic comes from the `diplomacy` package via
  `engine/`. Do not reimplement adjudication or hand-parse orders.
- **Order secrecy is sacred.** Pending orders are sealed to the adjudicator
  public key (`engine/crypto.py`). The private key exists ONLY in the
  `ADJUDICATOR_PRIVATE_KEY` GitHub Actions secret and is read ONLY by
  `orchestration/run_adjudication.py`. Never log, commit, or expose it.
- **Orders & messages are signed.** Each power signs with its own key
  (`engine/comms.py`); the adjudicator verifies against `players/<POWER>.json`.
  Players' private keys live in `secrets/` (gitignored). Never commit secrets/.
- **`main` is infra-only.** Game state (`state/`, `orders/`, `history/`,
  `players/`, `mail/`, `game/`) exists only on `game/<name>` branches; a
  `guard-main` check blocks it from landing on `main`.

## Setup & tests

```bash
./scripts/setup.sh && source .venv/bin/activate
pytest -q
```

The `diplomacy` package is pinned (`requirements.txt`) and verified to run on
Python 3.11.

## Layout (see README for detail)

- `engine/` — thin wrapper: `state`, `adjudicate`, `validate`, `query`,
  `crypto` (seal + sign), `comms` (full-press), `context` (per-power brief).
- `orchestration/` — CLIs: `new_game`, `join_game`, `submit_orders`,
  `send_message`, `read_messages`, `game_status`, `run_adjudication`,
  `conduct` (conductor roster/brief), `run_match` (programmatic conductor).
- `site/` — the GitHub Pages visualizer (`build_site.py` + `static/`).
- `.claude/skills/` — agent-facing skills (`start-playing` for a single power,
  `conduct-match` to run all powers from one session).
- `.github/workflows/` — `adjudicate.yml` (serverless adjudicator),
  `pages.yml` (visualizer), `guard-main.yml` (keep main infra-only).

## Roadmap

The approved plan lives outside the repo. Current state: **Epics 0–5 built**
(engine wrapper, gunboat git+Actions loop, core skills, human-play ergonomics,
GitHub Pages visualizer with map/text/talk/notes, full-press comms with per-player
encryption + signed orders, self-serve onboarding, single-session conductor mode
with scoped subagents). Next: **real Cicero (Epic 6)**. Open follow-ups: issues
#3 (own map), #8 (tamper-resistant identities), #13 (live conductor run).
