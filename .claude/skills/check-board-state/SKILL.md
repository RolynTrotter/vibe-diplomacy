---
name: check-board-state
description: Answer questions about the current Diplomacy board — what units are where, who owns which supply centers, province adjacencies, and how many builds/disbands each power owes. Use whenever you need ground-truth board facts before planning or writing orders.
---

# Check Board State

Your brief (from `scripts/turn.sh`) already contains a board snapshot. Only query directly if you need something the brief doesn't cover.

## Full snapshot
```bash
python -m orchestration.game_status          # human-readable table
python -m orchestration.game_status --json   # machine-readable
```

## Targeted queries
```python
from engine import state, query
g = state.load_game(".")

query.adjacencies(g, "PAR")        # provinces adjacent to PAR
query.province_info(g, "BUR")      # type, SC?, owner, occupier, neighbours
query.units_at(g, "MAO")           # who is in MAO
query.adjustment_summary(g)        # build/disband owed per power
query.full_graph(g)                # {PROV: {units, adjacent}} for every province
```

Province codes are 3-letter (PAR, BUR, MAO). Coasts use a suffix: `SPA/SC`.

**You cannot see opponents' pending orders** — only the public board and revealed `history/`. Sealed `.enc` files are unreadable until adjudication.
