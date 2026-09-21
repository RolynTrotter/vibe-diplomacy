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
  `crypto` (seal + sign), `comms` (full-press), `context` (per-power brief),
  `mapviz` (labelled board picture per phase), `coherence` (catch order sets
  that are legal but cannot execute).
- `engine/` (Jev order writing, additive — see PR #38): `jev` (TypeSafe
  credentials, one call, spend), `rules` (the ruleset as state),
  `valuation` (one question, province priorities), `orders_jev` (glosses,
  per-unit questions, single-pass), `staged` (who moves, then where, then
  supports), `press` (the power's own notes, DEAL: ledger, inbox and last
  outcomes as Jev state, plus the keep-or-break call on each standing deal).
- `orchestration/` — CLIs: `new_game`, `join_game`, `submit_orders`,
  `send_message`, `read_messages`, `game_status`, `run_adjudication`,
  `conduct` (roster/brief/tasks/collect/advance), `tasks` (shared task text),
  `run_match` (programmatic conductor), `jev_orders` (one power's orders,
  `--dry-run` to inspect the request, `--orders-only` to pipe into
  `scripts/submit.sh`), `jev_match` (gunboat self-play with Jev at all seven
  seats).
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
with scoped subagents). Next: **real Cicero (Epic 6)**. Open follow-ups: issues #3 (own map), #8
(tamper-resistant identities).

### Staff seats: who decides what

A seat with `orders: staff` (`orchestration/staff.py`) splits the turn by what
each model is good at. The playing model negotiates and writes **directions** —
plain English, no engine syntax; Jev turns those into a legal order per unit.

**The playing model is never told any of this.** It is told it has a general
staff. Nothing in `orchestration/tasks.py`, in any `.claude/skill`, or in any
prompt may name Jev, TypeSafe, or the order pipeline — `tests/test_staff.py`
asserts it. Two reasons: a seat that can reason about its own order writer can
try to game it, and every token spent deciding which tool to call is a token
not spent on the game. **Routing is a code decision, never a model decision** —
`run_match` picks the task kind from the seat spec, and the player has no tool
choice to get wrong.

Directions reach Jev twice: as `your_directions_this_turn` (this phase, next to
the board) and persisted to `notes/<POWER>.md` (durable, and what keeps the
`DEAL:` ledger working). So **a staff seat's play is only as good as the
directions it writes**.

Known gap, S1901M, measured: France submitted `F BRE S F LON - ENG`, supporting
*England* into the Channel while its own `DEAL: Channel DMZ` was kept at 0.97.
Capturing the actual request showed this was **not a judgment at all** — the
ballot had exactly one option on it, and the answer came back at confidence
1.0. Brest had four legal supports; `staged._helpers`'s `useful()` filter drops
a support for one of *your own* units whose committed order does not match,
which killed three of them (Paris was going to Burgundy, Marseilles to Spain),
and a support for a *foreign* unit survives unconditionally because you cannot
see that power's orders. Hold is offered only `if not opts`, so with one option
left it never appeared.

So the defect is structural, not a scoring one: **a single-option question is
not a decision**, and the one class of option that always survives filtering is
helping somebody else. Check the option count before blaming the choice.

### Working on the Jev path

One lesson recurred often enough to be worth stating up front: **a fact in
prose loses to a number, every time.** Hold beat scored moves while it carried
no score of its own; a `Priority 2/100` beat the words "neutral supply centre";
an absolute count of neighbouring centres beat the one centre a move would
actually win. Every fix was the same shape — put both sides of the comparison
in the same units, or stop describing the same thing twice. Change one thing at
a time and measure it; several changes that sounded obviously right (a complete
rulebook, an honest owned-versus-gettable split) made play measurably worse.
