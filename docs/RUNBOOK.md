# Runbook

How to start a match and run the seven sessions. Phone-first: every step is a
GitHub web action or a chat with a Claude session.

## One-time repo setup (the only real "auth" step, done once ever)

The adjudicator keypair is **per-repo and reused across every game**, so you set
it up a single time:

1. Generate a keypair and grab its public + private halves (any session):
   ```bash
   python -c "from engine import crypto; p,k=crypto.generate_keypair(); print('PUB',k); print('PRIV',p)"
   ```
2. In the repo: Settings → Secrets and variables → Actions → **New repository
   secret**, name `ADJUDICATOR_PRIVATE_KEY`, value = the `PRIV` line. Never
   commit or share it.
3. Keep the `PUB` value handy (paste it into `new_game --adjudicator-pubkey`
   below). That's it — no per-game secrets after this.

## A. Create a new match (game master, once per game)

1. **Branch.** From `main`, create `game/<name>` (e.g. `game/frostbite`).
   `main` stays infra-only; all game state lives on this branch.
2. **Initialize** on that branch:
   ```bash
   ./scripts/setup.sh && source .venv/bin/activate
   python -m orchestration.new_game --name frostbite \
       --press full \                       # 'full' = negotiation; omit for gunboat
       --adjudicator-pubkey <PUB> \         # reuse the repo key — no new secret
       --idle ITALY                         # optional
   ```
   This writes `game/config.json`, `game/adjudicator_pub.key`,
   `state/current.json` (S1901M), and the phase clock. (Omit
   `--adjudicator-pubkey` to generate a fresh per-game key, which then needs its
   own secret.)
3. **Commit** those files to the `game/<name>` branch.

## B. Get the players in — the easy way

Open **seven Claude Code sessions**. Give each the same one-line briefing — no
power, no keys:

> Play vibe-diplomacy on branch `game/frostbite`. Use the **start-playing** skill.

Each session claims a free power itself (generates its own keys, commits
`players/<POWER>.json`), so the seven sessions **divvy up the board on their
own**. If two grab the same seat, the loser re-picks automatically. You don't
hand out auth or assign powers.

(If you'd rather pin powers, tell a session "you are FRANCE" and it runs
`join_game --power FRANCE`.)

## C. Playing a phase

Each session loops on **`play-a-turn`**: orient → recall notes →
(full-press: `negotiate`) → get suggestions → validate + sign + seal → commit
`orders/<POWER>/<phase>.enc`. Use `scripts/sync.sh "<msg>" <your paths>` to
commit past the other sessions without push conflicts.

- **Authenticated.** Orders are signed with the power's key and verified by the
  adjudicator, so no one can submit another power's orders.
- When all live powers have committed, a push triggers
  `.github/workflows/adjudicate.yml`, which decrypts, adjudicates, advances the
  board, and reveals orders into `history/`.
- If a power stalls, the hourly **deadline sweep** forces the phase once it
  passes `deadline_hours` (missing orders → holds / civil disorder). The GM can
  also force a phase from the Actions tab (workflow_dispatch).

## D. Negotiation (full-press games)

With `press: full`, sessions exchange **sealed, signed** messages via the
`negotiate` skill before orders lock. Messages are private during the game and
the full transcript is revealed on the visualizer **only when the game ends**.
Deals are non-binding — lying is part of the game.

## E. Human play

A human plays a power exactly like an agent: tell a Claude session "I'm GERMANY,
here are my orders / here's my message to France," and it claims the seat (once)
and submits on your behalf. Or run the CLIs yourself and commit via the web UI.

## F. Monitoring

```bash
python -m orchestration.game_status        # who has moved, builds owed, phase
```
Or just open the visualizer: <https://rolyntrotter.github.io/vibe-diplomacy/>.
The game ends when a power controls 18 supply centers (or by agreed draw).

## G. Conductor mode (one session instead of seven)

For self-play, evaluation, or a solo sandbox you don't need seven sessions. Use
the **`conduct-match`** skill: one session spawns each power as a scoped
subagent, hands each only its own context (public board + that power's notes /
inbox), and adjudicates between phases. Each power still plays through the real
signed/sealed pipeline, so the files are the log and the conductor holds almost
no state.

- **Method toggle:** callstack-first — install once with
  `/plugin marketplace add unwind-labs/callstack` then
  `/plugin install callstack@unwind-labs`. Native subagents are the fallback
  (`CONDUCTOR_METHOD=native`).
- **Trust:** here isolation is enforced by context boundaries, not cryptography —
  the conductor sees everything. Fine for self-play; use the seven-session path
  (sections A–E) for distrusting players. The modes compose (some powers as
  subagents, some as independent sessions).
- For a fast local run, export `ADJUDICATOR_PRIVATE_KEY` so the conductor
  adjudicates in-session; push the game branch periodically for the visualizer.

## H. Programmatic conductor (one command, independent player sessions)

When you want each power to run as its **own headless Claude Code process** (the
only way to give each seat a real per-power model, e.g. a local Qwen via LM
Studio), use `run_match` instead of opening seven terminals:

```bash
# whole 7-way game from a spec, no extra terminals
python -m orchestration.run_match --spec matches/example.yaml

# or with inline overrides (flags beat the YAML)
python -m orchestration.run_match --name frostbite --press full \
    --model qwen/qwen3.6-35b-a3b --rounds 2 --max-phases 20
```

Each lever lives in `matches/*.yaml` (see `matches/example.yaml`) and has a
matching flag — `--print-plan` dumps the fully-resolved spec, `--dry-run` prints
intended dispatches without running. The conductor holds the adjudicator key for
local adjudication and **scrubs it from every player's env**, so artifacts are
byte-identical to a distrusting seven-session game. Transcripts land in
`runs/<name>/<phase>/<power>.json`.

- **Server-free smoke / CI:** `--backend fake` plays every seat from the
  heuristic suggester + curated openings — no model server needed.
- **Per-seat tweaks:** `--seat FRANCE.persona='cautious'`,
  `--seat GERMANY.model=claude-opus-4-8 --seat GERMANY.endpoint=api`.
- **Memory across turns:** `--session-mode persistent` resumes each player's
  session every turn. **Parallel seats:** `--max-concurrency 2` (also raise LM
  Studio's max concurrent requests).
