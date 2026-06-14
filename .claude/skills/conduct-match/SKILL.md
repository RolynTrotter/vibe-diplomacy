---
name: conduct-match
description: Run a whole Diplomacy match from ONE session by spawning each power as a scoped subagent (callstack or native). Use when asked to conduct, run, or self-play a match end-to-end without opening seven separate sessions. Each power gets selective context and plays through the real signed/sealed pipeline; the conductor only slices context, fans out, and adjudicates.
---

# Conduct a Match

One session, seven subagents. You slice context and adjudicate; subagents do the real playing. Isolation is by context boundary (not crypto) — right for self-play/eval, not distrusting play.

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

### a. Check roster
```bash
python -m orchestration.conduct roster
```
- `done: true` → go to **Finish**
- `to_play: []` → trivial phase (no dislodgements / all-zero adjustment) → skip to **d**
- otherwise → continue

### b. Negotiation rounds (full-press only)
Run 1–3 rounds before orders. Each round: fan out all live powers with task _"read inbox and send messages; do NOT write orders yet."_ Commit after each round.

### c. Fan out
For each `P` in `to_play`, build a brief:
```bash
python -m orchestration.conduct brief --power P
```
Spawn subagents **in parallel** with:
> You are **P** on `game/<name>`. Brief: «paste brief». Claim seat if needed (`join-game --power P`), play this phase (`play-a-turn`), use `scripts/submit.sh P` for orders and `scripts/sync.sh` for notes. Reply: "P submitted <phase>".

- **callstack:** `/call <task for A>, <task for B>, … in parallel` (fresh mode)
- **native:** one `Agent` call per power in a single message (concurrent)

Keep briefs disjoint — never give a power another's brief, notes, or inbox.

### d. Adjudicate
```bash
git add -A && git commit -m "Players submitted <phase>" || true
python -m orchestration.conduct roster          # confirm all_submitted
python -m orchestration.run_adjudication        # or --force for deadline
git add -A && git commit -m "Adjudicate <phase>" || true
```

### e. Publish (optional)
```bash
git push origin game/<name>
```

Loop back to **a**.

## Finish
When `done: true`, push and report the result. Full-press: the adjudicator will have written `mail/revealed.json` for the visualizer post-mortem.
