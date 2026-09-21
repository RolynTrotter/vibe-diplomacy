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

## 4. Update notes
Overwrite `notes/<POWER>.md` with your updated plan (see **consult-notes**), then:
```bash
scripts/sync.sh "<POWER> notes" notes/<POWER>.md
```

## 5. Wait
Adjudication runs once all live powers submit (or deadline passes). Then repeat from step 1.
