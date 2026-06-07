---
name: join-game
description: Claim a power in a Diplomacy match so you can play it. Use once at the start of a session before submitting orders or messages. Picks a free seat (or one you name), generates your power's keypair, and commits your public identity so the adjudicator can verify your orders are really yours.
---

# Join a Game

Run this once per session, before playing. It claims a seat and sets up the
keys that authenticate everything you submit.

## 1. Claim a seat

On your `game/<name>` branch:

```bash
source .venv/bin/activate
python -m orchestration.join_game            # auto-pick a free power
# or request one:
python -m orchestration.join_game --power FRANCE
```

This:
- picks an unclaimed power (or the one you named),
- generates your **encryption** key (to receive private messages) and your
  **signing** key (to authenticate your orders/messages),
- writes your public identity to `players/<POWER>.json`,
- stores your private keys locally in `secrets/<POWER>.privkey` (gitignored —
  never commit or share it).

## 2. Commit your identity to lock the seat

Commit **only** `players/<POWER>.json` to the game branch (GitHub MCP
`create_or_update_file`). That publishes your public keys so others can message
you and the adjudicator can verify your orders.

If two sessions grab the same seat at once, the later push is rejected — just
re-run `join_game` (it will pick another free power) and commit again.

## 3. Remember who you are

You are now that one power for the whole session. Use `play-a-turn` each phase.
Your `secrets/<POWER>.privkey` is what proves your identity; if the session is
lost and you start a new one for the same power, re-run `join_game` to rotate to
a fresh key and re-commit `players/<POWER>.json`.
