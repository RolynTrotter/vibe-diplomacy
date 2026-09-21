---
name: negotiate
description: Read and send private diplomatic messages with other powers in a full-press game. Use during the negotiation window each phase to read your inbox, strike deals, and send signed, sealed messages (private DMs or broadcasts) before you write orders. Only works in games with press enabled.
---

# Negotiate

Full-press games only (`press: full` in `game/config.json`). Requires a claimed seat.

## Your inbox is already in your brief

Your brief already carries every message addressed to you this phase, plus a
threaded digest of older mail per partner. **Do not re-read it** — that is a
round trip for text you already have.

The only reason to reach for the CLI is a full transcript of one relationship
that the digest has shortened:

```bash
python -m orchestration.read_messages --power FRANCE --with ENGLAND
```

Check `verified: true` — treat unsigned messages with suspicion.

## Send

One command, one message. `--to` takes several powers when the same words go to
each of them:

```bash
echo "Want to DMZ the Channel?" | \
  python -m orchestration.send_message --power FRANCE --to ENGLAND

echo "Burgundy stays empty?" | \
  python -m orchestration.send_message --power FRANCE --to ENGLAND GERMANY

echo "Russia is pulling ahead — coordinate?" | \
  python -m orchestration.send_message --power FRANCE --to ALL
```

Then commit the mail you created:

```bash
scripts/sync.sh "<POWER> <phase> messages" mail/
```

## Notes
- Bodies are readable only by the recipient. The sender→recipient graph is hidden from spectators.
- Messages stay sealed during the game; revealed publicly for the post-mortem once it ends.
- Lying is legal. What you say is never checked against what you order. Record deals in your notes (`consult-notes`).
