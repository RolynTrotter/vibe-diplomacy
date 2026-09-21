---
name: play-a-turn
description: Play one full Diplomacy turn end-to-end for your power — orient on the board, recall your plan, negotiate, decide, then validate, seal, and submit your orders. Use this as the top-level loop each time it is your turn.
---

# Play a Turn

> **Single-power sessions only.** If you're a subagent inside a conductor session, follow the task instructions given to you — the conductor sequences negotiation and orders separately, so don't re-invoke this skill.

## 0. First time in the session
Claim a seat if you haven't: `join-game`. Commit `players/<POWER>.json`.

## 1. Orient
```bash
scripts/turn.sh <POWER>
```
Pulls latest state and prints your full brief: board picture, topology, units, scoreboard, last phase, notes, inbox (full-press). **This is ground truth — skip separate `game_status` or `cat notes` calls.**

The brief ends with a path to a **labelled PNG of the current board** (`.board/<phase>.png`) — every province named, units in their power's colour. **Read that image before you plan**; it is the cheapest way to stop guessing at geometry. The "Board topology" section carries the same geometry in text (who you border, which centers are near and through where) if you can't view images.

## 2. Negotiate (full-press only)
Read inbox and send messages before locking orders. See **negotiate**.

## 3. Submit orders
```bash
echo "A PAR - BUR
F BRE - MAO
A MAR - SPA" | scripts/submit.sh <POWER>
```
Validates, seals, commits, and pushes in one shot. Illegal orders print an error and nothing is written — fix and retry.

### Or: let Jev write them

You can negotiate and set the policy, and hand the tactics to Jev — it picks from the legal orders the engine enumerates, so it cannot emit an illegal one.

```bash
python -m orchestration.jev_orders --power <POWER> --stab --orders-only | scripts/submit.sh <POWER>
```

It reads your `notes/<POWER>.md`, your `DEAL:` lines, your inbox and what happened to your last orders, so **the quality of its play is the quality of your notes**. Before you run it, write down what you actually want this turn — priorities in prose, agreements as `DEAL:` lines. With `--stab` each standing deal is decided keep-or-break once, up front, and the verdict binds the orders.

Read the report on stderr before you accept the result; drop `--orders-only` to see it without submitting.

## 4. Update notes
Overwrite `notes/<POWER>.md` with your updated plan (see **consult-notes**), then:
```bash
scripts/sync.sh "<POWER> notes" notes/<POWER>.md
```

## 5. Wait
Adjudication runs once all live powers submit (or deadline passes). Then repeat from step 1.
