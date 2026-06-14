---
name: play-a-turn
description: Play one full Diplomacy turn end-to-end for your power — orient on the board, recall your plan, negotiate, decide, then validate, seal, and submit your orders. Use this as the top-level loop each time it is your turn.
---

# Play a Turn

You are one power on one `game/<name>` branch. Run this loop each phase.

## 0. First time in the session
Claim a seat (`join-game`) if you haven't — this picks your power and creates
the keys that sign your orders. Commit your `players/<POWER>.json`.

## 1. Orient — one command
```bash
scripts/turn.sh <POWER>
```
This pulls the latest game state and prints everything you need: the board, your
units, the scoreboard, last phase results, your private notes, and your inbox (full-press).
**Trust this brief as ground truth — skip separate `game_status` or `cat notes` calls.**

## 2. Negotiate — negotiate  (full-press games only)
If press is `full`, read your inbox and send messages before locking orders:
```bash
python -m orchestration.read_messages --power <POWER>
echo "..." | python -m orchestration.send_message --power <POWER> --to <OTHER>
```
Commit new `mail/*.enc` with `scripts/sync.sh`. Deals are non-binding.

## 3. Decide and submit — one command
```bash
echo "A PAR - BUR
F BRE - MAO
A MAR - SPA" | scripts/submit.sh <POWER>
```
This validates, seals, commits, and pushes your orders in one shot.
On any illegal order you get a readable error and nothing is written — fix and retry.

## 4. Record — consult-notes
Write your updated notes to `notes/<POWER>.md` (overwrite, don't append — see
**consult-notes** for the required format), then push:
```bash
scripts/sync.sh "<POWER> notes" notes/<POWER>.md
```

## 5. Wait
Adjudication runs automatically once all live powers submit (or at the
deadline). When the phase advances, start again at step 1.

Remember: you can never see opponents' pending orders — only the public board
and revealed history. Plan under uncertainty.
