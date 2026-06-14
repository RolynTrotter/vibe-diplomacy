---
name: play-a-turn
description: Play one full Diplomacy turn end-to-end for your power — orient on the board, recall your plan, negotiate, decide, then validate, seal, and submit your orders. Use this as the top-level loop each time it is your turn.
---

# Play a Turn

## 0. First time in the session
Claim a seat if you haven't: `join-game`. Commit `players/<POWER>.json`.

## 1. Orient
```bash
scripts/turn.sh <POWER>
```
Pulls latest state and prints your full brief: board, units, scoreboard, last phase, notes, inbox (full-press). **This is ground truth — skip separate `game_status` or `cat notes` calls.**

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
