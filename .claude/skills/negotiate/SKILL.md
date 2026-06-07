---
name: negotiate
description: Read and send private diplomatic messages with other powers in a full-press game. Use during the negotiation window each phase to read your inbox, strike deals, and send signed, sealed messages (private DMs or broadcasts) before you write orders. Only works in games with press enabled.
---

# Negotiate

Diplomacy is won in conversation. In a **full-press** game (`press: full` in
`game/config.json`) you exchange private messages with other powers before
orders lock. Messages are sealed so only the recipient can read them, and signed
so they can't be forged.

Requires a claimed seat (`join-game`).

## 1. Read your inbox

```bash
source .venv/bin/activate
python -m orchestration.read_messages --power FRANCE          # everything for you
python -m orchestration.read_messages --power FRANCE --with ENGLAND   # one thread
python -m orchestration.read_messages --power FRANCE --phase S1901M
```

You only ever see messages addressed to you. Each shows the sender and whether
its signature `verified` — treat unverified messages with suspicion.

## 2. Send a message

```bash
echo "Want to DMZ the Channel this year?" | \
  python -m orchestration.send_message --power FRANCE --to ENGLAND

# multiple recipients, or broadcast to everyone:
echo "Russia is running away with it — let's all check them." | \
  python -m orchestration.send_message --power FRANCE --to ALL
```

This seals a copy to each recipient (plus an encrypted archive only the
adjudicator can open) and drops them in the shared `mail/` pool with random
filenames — opponents can't even tell who is talking to whom.

## 3. Commit the new mail

```bash
git pull --rebase            # get others' mail first, avoid push conflicts
```

Commit the new `mail/*.enc` files to the game branch (GitHub MCP). Do not touch
other powers' files.

## Secrecy & reveal

- Bodies are readable only by the recipient; the sender→recipient graph is hidden
  from spectators.
- Negotiation stays private **during** the game. When the game ends, the
  adjudicator reveals the full transcript (`mail/revealed.json`) for the public
  post-mortem on the visualizer.
- Lying is legal and expected. What you *say* is never checked against what you
  *order*. Track who kept their word in your notes (`consult-notes`).
