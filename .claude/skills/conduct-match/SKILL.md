---
name: conduct-match
description: Run a whole Diplomacy match from ONE session by spawning each power as a scoped subagent (callstack or native). Use when asked to conduct, run, or self-play a match end-to-end without opening seven separate sessions. Each power gets selective context and plays through the real signed/sealed pipeline; the conductor only slices context, fans out, and adjudicates.
---

# Conduct a Match

One session, seven subagents. **Three commands per phase do all the bookkeeping** — you spend your judgement on nothing but reading replies, because there is no judgement in composing prompts or remembering which CLI to run.

Isolation is by context boundary (not crypto) — right for self-play/eval, not distrusting play.

> **Note on `play-a-turn`**: that skill is for single-power 7-session play. In conductor mode subagents get targeted tasks and reply with **text only** — they need no tools and no CLI knowledge.

## 0. Setup (once)
```bash
./scripts/setup.sh && source .venv/bin/activate
git checkout -B game/<name> origin/game/<name>
export ADJUDICATOR_PRIVATE_KEY=...    # enables local adjudication (no CI wait)
```

## Dispatch method
**Default: `callstack`** (install: `/plugin install callstack@unwind-labs`).
Fall back to **`native`** if unavailable or if `CONDUCTOR_METHOD=native`.

## 1. Phase loop

### a. Get this phase's tasks
```bash
python -m orchestration.conduct tasks --format text
```
One self-contained task per power that still has to act — brief, board picture path, and the exact reply format, already written. The header line tells you the phase and the `kind`:

- **`combined`** (default on full-press movement phases) — messages *and* orders in one reply. This is the whole point: one model call per power per phase instead of two.
- **`orders`** — gunboat, retreats, adjustments.
- Prints `0 power(s) to play` on a trivial phase → skip straight to **c**.
- Want an extra talking round first? Run `--kind negotiation` once, collect those replies, then run `tasks` again for the `combined` round (the fresh brief includes the mail that just arrived).

If `done: true` in `conduct roster`, go to **Finish**.

### b. Fan out, then collect each reply
Spawn all listed powers **in parallel**, one subagent each, passing its task verbatim. Tell each to read the board image the brief names (`.board/<phase>.png`) — a pasted brief carries the path, not the picture — and to reply in the given format and nothing else. Subagents run **no commands**.

Pipe each reply straight back:
```bash
echo "<subagent reply>" | python -m orchestration.conduct collect --power FRANCE
```
This claims the seat if needed, seals and signs the mail, validates and seals the orders — the same artifacts a distrusting session produces. It prints JSON:

- `"ok": true` → done with that power.
- `"ok": false` → `error` is the validation or coherence message. Hand that text back to the same subagent once and collect its corrected reply. Do not fix a power's orders yourself.

### c. Advance
```bash
python -m orchestration.conduct advance
```
Commits what the powers produced, adjudicates locally, commits the new board, and pushes — **two commits per phase**, not one per power per round. Prints `next_phase` and `done`.

- `--no-push` to stay local; `--wait` to refuse to force-adjudicate stragglers (default forces, so one stuck power can't hang the match).
- Needs `ADJUDICATOR_PRIVATE_KEY` exported; it says so plainly if it is missing.

Loop back to **a**.

## Finish
When `done: true`, report the result. Full-press: `mail/revealed.json` holds the message transcript for the visualizer post-mortem.

## Prefer the fully programmatic runner
If nobody needs to watch the game turn by turn, don't conduct it by hand at all:
```bash
python -m orchestration.run_match --name <name> --press full --backend raw
```
Same pipeline, no conductor in the loop. Conduct by hand when you want to read the replies as they come, or to mix in seats a script can't drive.
