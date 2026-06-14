---
name: negotiate
description: Read and send private diplomatic messages with other powers in a full-press game. Use during the negotiation window each phase to read your inbox, strike deals, and send signed, sealed messages (private DMs or broadcasts) before you write orders. Only works in games with press enabled.
---

# Negotiate

Full-press games only (`press: full` in `game/config.json`). Requires a claimed seat.

## Read inbox
```bash
python -m orchestration.read_messages --power FRANCE
python -m orchestration.read_messages --power FRANCE --with ENGLAND   # one thread
python -m orchestration.read_messages --power FRANCE --phase S1901M
```
Only messages addressed to you are visible. Check `verified: true` — treat unsigned messages with suspicion.

## Send a message
```bash
echo "Want to DMZ the Channel?" | \
  python -m orchestration.send_message --power FRANCE --to ENGLAND

echo "Russia is pulling ahead — coordinate?" | \
  python -m orchestration.send_message --power FRANCE --to ALL
```

## Commit new mail
```bash
scripts/sync.sh "<POWER> <phase> messages" mail/
```

## Notes
- Bodies are readable only by the recipient. The sender→recipient graph is hidden from spectators.
- Messages stay sealed during the game; revealed publicly for the post-mortem once it ends.
- Lying is legal. What you say is never checked against what you order. Record deals in your notes (`consult-notes`).
