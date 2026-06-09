---
name: run-cicero
description: Get cutthroat tactical order suggestions for your power, computed from the public board and order history without regard to negotiation. Use to sanity-check your plan or to find aggressive moves you missed before writing orders.
---

# Run Cicero (tactical suggestions)

Suggests a full set of legal orders for your power this phase. It reads only
public information (the board + revealed `history/`) — never anyone's sealed
orders.

```bash
source .venv/bin/activate
python -m orchestration.suggest_orders --power FRANCE
python -m orchestration.suggest_orders --power FRANCE --json
```

Each suggestion comes with a one-line rationale, e.g. `move on supply center
SPA`. The output is **advice only** — review it, then submit your chosen orders
with the write-orders skill.

## Which engine is running?

- `--engine heuristic` (default, shipping now): a fast, comms-blind greedy
  suggester that favours capturing supply centers and otherwise holds. Good for
  catching obvious captures and undefended centers; it does not coordinate
  supports or model opponents.
- `--engine cicero` (future): Meta's real no-press Diplomacy agent, slotted in
  behind the identical interface once provisioned (needs GPUs + model weights —
  see the plan's Epic 6). Until then it raises a clear "not wired yet" error.

Treat heuristic output as a floor, not a strategy: it tells you the greedy
move, you decide whether your alliances and longer game say otherwise.
