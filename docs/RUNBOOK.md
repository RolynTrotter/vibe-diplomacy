# Runbook

How to start a match and run the seven sessions. Phone-first: every step is a
GitHub web action or a chat with a Claude session.

## A. Create a new match (game master, once)

1. **Branch.** From `main`, create `game/<name>` (e.g. `game/frostbite`).
   `main` stays infra-only; all game state lives on this branch.
2. **Initialize.** On that branch:
   ```bash
   ./scripts/setup.sh && source .venv/bin/activate
   python -m orchestration.new_game --name frostbite \
       --human ENGLAND --idle ITALY     # flags optional
   ```
   This writes `game/config.json`, `game/adjudicator_pub.key`,
   `state/current.json` (S1901M), the phase clock, and **prints the adjudicator
   private key once**.
3. **Set the secret.** In the repo: Settings → Secrets and variables → Actions →
   **New repository secret**, name `ADJUDICATOR_PRIVATE_KEY`, value = the printed
   key. This is the only copy the workflow can use. Never commit it or share it
   with the agents.
4. **Commit** the initialized files to the `game/<name>` branch (not the private
   key — `.gitignore` already blocks it).

The adjudicator keypair is per-repo by default, shared across all game branches.
That leaks nothing between players (they still can't decrypt). Use per-game
secrets only if you want different GMs per match.

## B. Brief each session (one per power)

Open 7 Claude Code sessions. Give each the same briefing with its own power:

> You are **FRANCE** in a Diplomacy match on branch **`game/frostbite`**. Work
> only on that branch. Use the `play-a-turn` skill each phase. Submit orders by
> committing only your own `orders/FRANCE/<phase>.enc` (and `notes/FRANCE.md`).
> Never read or touch other powers' files, `state/`, `history/`, or `game/`.

Each session generates no keys in gunboat — order secrecy is handled by the
adjudicator public key already on the branch.

## C. Playing a phase

1. Each session runs `play-a-turn`: orient → recall notes → get suggestions →
   validate + seal → commit `orders/<POWER>/<phase>.enc`.
2. When all live (non-idle) powers have committed, a push triggers
   `.github/workflows/adjudicate.yml`, which decrypts, adjudicates, advances the
   board, and reveals orders into `history/`.
3. If a power stalls, the hourly **deadline sweep** forces the phase once it
   passes `deadline_hours` (missing orders become holds / civil disorder). The
   GM can also force a phase manually via the Actions tab (workflow_dispatch).

## D. Human play

A human plays a power exactly like an agent:
- Easiest: tell a Claude session "I'm GERMANY, here are my orders…"; it runs
  `submit_orders` and commits the sealed file.
- Fully manual: run `submit_orders` locally and commit the `.enc` via the GitHub
  web UI.

## E. Monitoring

```bash
python -m orchestration.game_status        # who has moved, builds owed, phase
```
The game ends when a power controls 18 supply centers (or by agreed draw).
