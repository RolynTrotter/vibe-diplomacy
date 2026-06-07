---
name: play-a-turn
description: Play one full Diplomacy turn end-to-end for your power — orient on the board, recall your plan, get tactical suggestions, decide, then validate, seal, and submit your orders. Use this as the top-level loop each time it is your turn.
---

# Play a Turn

You are one power on one `game/<name>` branch. Run this loop each phase.

## 0. First time in the session
```bash
./scripts/setup.sh && source .venv/bin/activate
```
Confirm which power and branch you are. Make sure your working tree is on your
game branch and up to date.

## 1. Orient — check-board-state
```bash
python -m orchestration.game_status
```
Note the phase, your units/centers, and your build/disband count. Inspect key
provinces and read the latest `history/` to see what opponents just did.

## 2. Recall your plan — consult-notes
```bash
cat notes/<POWER>.md 2>/dev/null
```

## 3. Get options — run-cicero
```bash
python -m orchestration.suggest_orders --power <POWER>
```
Use it as a floor (obvious captures / threats), not a strategy.

## 4. Decide and submit — write-orders
Validate + seal:
```bash
echo "<your orders>" | python -m orchestration.submit_orders --power <POWER>
```
Fix any rejected orders, then commit `orders/<POWER>/<phase>.enc` to your
branch via GitHub MCP.

## 5. Record — consult-notes
Update `notes/<POWER>.md` with what changed (new reads on opponents, next-phase
reminders) and commit it.

## 6. Wait
Adjudication runs automatically once all live powers submit (or at the
deadline). When the phase advances, start again at step 1.

Remember: you can never see opponents' pending orders — only the public board
and revealed history. Plan under uncertainty.
