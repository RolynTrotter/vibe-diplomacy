---
name: conduct-match
description: Run a whole Diplomacy match from ONE session by spawning each power as a scoped subagent (callstack or native). Use when asked to conduct, run, or self-play a match end-to-end without opening seven separate sessions. Each power gets selective context and plays through the real signed/sealed pipeline; the conductor only slices context, fans out, and adjudicates.
---

# Conduct a Match

One session, seven subagents. You slice context and adjudicate; subagents execute specific tasks. Isolation is by context boundary (not crypto) — right for self-play/eval, not distrusting play.

> **Note on `play-a-turn`**: that skill is for single-power 7-session play where each power manages its own full turn. In conductor mode, you orchestrate the steps directly — subagents get targeted tasks, not `play-a-turn`.

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
Run 1–3 rounds **before** orders. Build a brief per power, then fan out all live powers in parallel with this task:

> You are **P** on `game/<name>`. Brief: «paste brief output».
> This is a **negotiation round only** — do not write orders yet.
> Read your inbox: `python -m orchestration.read_messages --power P`
> Send messages: `echo "..." | python -m orchestration.send_message --power P --to OTHER`
> Commit new mail: `scripts/sync.sh "P <phase> messages" mail/`
> Reply with one line: "P negotiated <phase> round <n>".

Commit between rounds: `git add -A && git commit -m "<phase> press round <n>"`.

### c. Orders round
Build a fresh brief per power (captures inbox after negotiation), then fan out `to_play` in parallel:

> You are **P** on `game/<name>`. Brief: «paste brief output».
> Claim your seat if you haven't: `python -m orchestration.join_game --power P && scripts/sync.sh "P claims seat" players/P.json`
> Negotiation is complete. Submit your orders:
> `echo "your orders here" | scripts/submit.sh P`
> Update your notes (`notes/P.md`, 3-section format, ≤250 words) then:
> `scripts/sync.sh "P notes" notes/P.md`
> Reply with one line: "P submitted <phase>".

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
When `done: true`, push and report the result. Full-press: `mail/revealed.json` has the message transcript for the visualizer post-mortem.
