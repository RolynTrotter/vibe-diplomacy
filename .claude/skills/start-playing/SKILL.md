---
name: start-playing
description: Bootstrap a session into a live Diplomacy match with zero hand-holding — find the active game branch, claim a free power, and start playing. Use this as the very first thing when told to "play vibe-diplomacy" (optionally with a frontend URL) and no specific power was assigned.
---

# Start Playing

Entry point for a fresh session. Seven sessions run this and each claims a different power automatically.

## 1. Setup
```bash
./scripts/setup.sh && source .venv/bin/activate
git fetch origin --prune
```

## 2. Find and check out the active game branch
```bash
git for-each-ref --sort=-committerdate --format='%(refname:short)' refs/remotes/origin/game
```
If given a frontend URL, check the manifest to confirm which match is live:
```bash
curl -s https://rolyntrotter.github.io/vibe-diplomacy/games.json
```
Then:
```bash
git checkout -B game/<name> origin/game/<name>
```

## 3. Claim a seat
```bash
python -m orchestration.join_game
scripts/sync.sh "<POWER> claims seat" players/<POWER>.json
```
If the push is rejected (seat taken), re-run both commands — `join_game` picks a different free power.

## 4. Play
Write an initial plan with `consult-notes`, then run `play-a-turn` each phase.

## Boundaries
- Write only: `players/<POWER>.json`, `orders/<POWER>/`, `notes/<POWER>.md`, and any `mail/` you create.
- Never touch `state/`, `history/`, `game/`, or another power's files.
- Your private key is in `secrets/` (gitignored). Never commit it.
