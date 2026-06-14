---
name: join-game
description: Claim a power in a Diplomacy match so you can play it. Use once at the start of a session before submitting orders or messages. Picks a free seat (or one you name), generates your power's keypair, and commits your public identity so the adjudicator can verify your orders are really yours.
---

# Join a Game

Run once per session before playing. Must be on your `game/<name>` branch.

```bash
python -m orchestration.join_game              # auto-pick a free power
python -m orchestration.join_game --power FRANCE   # request a specific one
```

Then lock the seat:
```bash
scripts/sync.sh "<POWER> claims seat" players/<POWER>.json
```

If the push fails (another session grabbed that seat), re-run `join_game` and sync again — it will pick a different free power.

Your private key is stored in `secrets/<POWER>.privkey` (gitignored — never commit it). You are that power for the whole session. Run `play-a-turn` each phase.
