---
name: conduct-match
description: Run a whole Diplomacy match from ONE session by spawning each power as a scoped subagent (callstack or native). Use when asked to conduct, run, or self-play a match end-to-end without opening seven separate sessions. Each power gets selective context and plays through the real signed/sealed pipeline; the conductor only slices context, fans out, and adjudicates.
---

# Conduct a Match

You are the **conductor**: one session that runs an entire match by spawning each
power as a fresh-context subagent. You hold almost no game state in your head —
the files are the log. Each power subagent does the real work (claims a seat,
signs + seals its orders, commits its own files); you only slice context, fan
out, and trigger adjudication.

> Trust note: in conductor mode, isolation between powers is enforced by
> **context boundaries** (what you hand each subagent), not cryptography — you
> can see everything. That's right for self-play / evaluation / a sandbox. For
> distrusting players, use seven independent sessions (`start-playing`) instead.
> The two compose; the signed-orders pipeline is identical either way.

## 0. Setup (once)

```bash
./scripts/setup.sh && source .venv/bin/activate
git checkout -B game/<name> origin/game/<name>     # the match to run
```

For fast local self-play, export the adjudicator key so you can adjudicate in
this session (no waiting on CI):
```bash
export ADJUDICATOR_PRIVATE_KEY=...   # the repo's adjudicator private key
```

## Pick a dispatch method (toggle)

**Default / first choice: `callstack`** — give it a whirl. Install once:
```
/plugin marketplace add unwind-labs/callstack
/plugin install callstack@unwind-labs
```
Use **`native`** instead if the user asks, or if callstack isn't installed.
Honor `CONDUCTOR_METHOD=native` if set. Both produce identical artifacts; only
the fan-out mechanism differs.

## 1. Phase loop

Repeat until the match ends:

### a. Who needs to play?
```bash
python -m orchestration.conduct roster
```
Gives `phase`, `press`, `done`, `to_play` (live powers not yet submitted), and
each power's claimed/submitted status. If `done` is true, go to **Finish**.

### b. (Full-press only) negotiation rounds
If `press` is `full`, run 1–3 negotiation rounds *before* orders so deals can
form. Each round: fan out one subagent per live power (same dispatch as step c)
with the task *"read your inbox (`negotiate`/read_messages) and send any messages
this round; do NOT write orders yet."* Commit after each round
(`git add -A && git commit -m "<phase> press round <n>"`). Messages stay sealed;
they're revealed publicly only at game end.

### c. Fan out the players (this is the toggle)
For each power `P` in `to_play`, build its selective brief:
```bash
python -m orchestration.conduct brief --power P
```
Then spawn one subagent per power **in parallel**, fresh context, each task:

> You are **P** on branch `game/<name>`. Here is your briefing:
> «paste the `brief` output». Claim your seat if you have none
> (`join-game --power P`), then play this phase with **play-a-turn** (full-press:
> you've already negotiated — now decide orders). Validate + sign + seal and
> commit ONLY your own files (`orders/P/…`, `players/P.json`, `notes/P.md`, and
> any `mail/` you created). Reply with one line: "P submitted <phase>".

- **callstack:** one `/call` with parallel fan-out — e.g.
  `/call <task for AUSTRIA>, <task for ENGLAND>, … in parallel`, fresh mode so
  only the task (the brief) crosses the boundary. Each returns a compact result.
- **native:** issue one `Agent` (general-purpose, fresh) per power in a single
  message so they run concurrently; each gets only its task string.

Keep the briefs disjoint — never hand a power another power's brief, notes, or
inbox.

### d. Commit + adjudicate
Capture anything the subagents wrote, then resolve the phase:
```bash
git add -A && git commit -m "Players submitted <phase>" || true
python -m orchestration.conduct roster          # confirm all_submitted
python -m orchestration.run_adjudication        # advances the board locally
git add -A && git commit -m "Adjudicate <phase>" || true
```
If a power failed to submit and you want to proceed anyway, run
`run_adjudication --force` (missing orders become holds).

### e. Publish (optional, periodic)
Push the game branch so the visualizer picks it up on its next build:
```bash
git push origin game/<name>
```

Then loop back to **a**.

## Finish

When `roster` reports `done`, the adjudicator has already written
`mail/revealed.json` (full-press transcript). Push once more so the visualizer
shows the final board and the revealed messages, and report the result.

## Keep the conductor light

- Don't read powers' orders, keys, or inboxes yourself — let the subagents own
  them and let `roster` / `game_status` tell you the state.
- One model playing all powers will homogenize unless you keep contexts fresh
  and briefs distinct; for rigorous head-to-head eval, prefer separate sessions.
