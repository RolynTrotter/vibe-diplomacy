---
name: start-playing
description: Bootstrap a session into a live Diplomacy match with zero hand-holding — find the active game branch, claim a free power, and start playing. Use this as the very first thing when told to "play vibe-diplomacy" (optionally with a frontend URL) and no specific power was assigned.
---

# Start Playing

This is the one-shot entry point. Open a session, point it here, and it joins a
game and starts playing — no auth handed to you, no power pre-assigned. Open
seven sessions and they divvy up the seven powers on their own.

## 1. Set up

```bash
./scripts/setup.sh && source .venv/bin/activate
git fetch origin --prune
```

## 2. Find the active game branch

```bash
# Active matches (most recently updated first):
git for-each-ref --sort=-committerdate \
  --format='%(refname:short)' refs/remotes/origin/game
```

If there's exactly one `game/<name>`, use it. If several, prefer the one the
frontend shows as live (if you were given the page, read its manifest):

```bash
curl -s https://rolyntrotter.github.io/vibe-diplomacy/games.json
```

Then check it out:

```bash
git checkout -B game/<name> origin/game/<name>
```

## 3. Claim a free seat (join-game)

```bash
python -m orchestration.join_game            # auto-picks an unclaimed power
```

Lock it in by committing **only** your identity file, rebasing past whoever
else just joined:

```bash
scripts/sync.sh "<POWER> claims seat" players/<POWER>.json
```

**If the push fails or your power was taken** (another session grabbed it first),
re-fetch and try again — `join_game` will pick a different free seat:

```bash
git pull --rebase origin game/<name>
python -m orchestration.join_game
scripts/sync.sh "<POWER> claims seat" players/<POWER>.json
```

You are now that power for the rest of the session. Note it and your branch.

## 4. Set your strategy, then play

Skim the rules in `docs/` and your power's opening ideas, jot an initial plan
with `consult-notes`, then run **`play-a-turn`** every phase. In a full-press
game (`press: full` in `game/config.json`), use **`negotiate`** before locking
orders.

## Boundaries (important)

- Touch only your own files: `players/<POWER>.json`, `orders/<POWER>/…`,
  `notes/<POWER>.md`, and (full-press) the `mail/` additions you create.
- Never edit `state/`, `history/`, `game/`, or another power's files — the
  adjudicator owns those, and your private key stays in `secrets/` (gitignored).
- You can't see opponents' pending orders or their private mail. Play under
  uncertainty; trust nothing you can't verify.
