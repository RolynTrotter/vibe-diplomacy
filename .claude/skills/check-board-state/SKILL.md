---
name: check-board-state
description: Answer questions about the current Diplomacy board — what units are where, who owns which supply centers, province adjacencies, and how many builds/disbands each power owes. Use whenever you need ground-truth board facts before planning or writing orders.
---

# Check Board State

All answers come straight from the live engine, so they can never drift from
the authoritative `state/current.json` on your game branch.

## Setup (once per session)

```bash
./scripts/setup.sh        # creates .venv and installs the engine
source .venv/bin/activate
```

## Commands

Whole-board snapshot (phase, every power's units/centers, build/disband owed):

```bash
python -m orchestration.game_status            # human-readable table
python -m orchestration.game_status --json     # machine-readable
```

Targeted province / board questions:

```bash
python - <<'PY'
from engine import state, query
g = state.load_game(".")

# What is adjacent to a province?
print(query.adjacencies(g, "PAR"))

# Full info on a province (type, SC?, owner, occupier, neighbours)
print(query.province_info(g, "BUR"))

# Who occupies a province right now?
print(query.units_at(g, "MAO"))

# Build/disband owed per power (+build / -disband)
print(query.adjustment_summary(g))
PY
```

## Notes
- Province codes are the standard 3-letter abbreviations (PAR, BUR, MAO…).
  Coasts use a suffix like `SPA/SC`.
- You can read the public history of resolved phases in `history/<phase>.json`
  (every power's revealed orders and results) — useful for reading intentions.
- You can NOT see other powers' *pending* orders for the current phase: they
  are sealed (`orders/<POWER>/<phase>.enc`) and only the adjudicator can open
  them. That secrecy is the whole game.
