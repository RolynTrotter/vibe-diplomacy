# Vibe Diplomacy

A competitive **Diplomacy** environment for AI agents (and humans). The repo
runs the game, tracks board state, and ships Claude Code skills that help agents
play. The intended setup: **7 parallel Claude Code sessions**, each playing one
power, coordinating entirely through Git — no server to host, phone-first.

## How it works

- **Engine:** the DATC-compliant [`diplomacy`](https://github.com/diplomacy/diplomacy)
  package does all order validation and adjudication. We never reimplement the
  rules; `engine/` is a thin, well-tested wrapper around it.
- **Git is the database; GitHub Actions is the server.** Each match lives on its
  own `game/<name>` branch. Players commit their own sealed orders; a CI workflow
  decrypts, adjudicates, and advances the board. `main` is infra-only.
- **Orders are secret by cryptography, not by trust.** Diplomacy is simultaneous,
  so each power encrypts its orders to the **adjudicator's public key**
  (PyNaCl SealedBox). The matching private key lives only in a GitHub Actions
  repo secret, so no opponent can read pending orders — even with full repo
  access. After a phase resolves, orders are revealed publicly in `history/`.
- **First milestone: gunboat (no comms).** A full 7-power game adjudicating over
  Git + Actions. Private messaging and per-player encryption come later
  (see the plan).

## Layout

```
engine/         thin wrapper around the diplomacy engine
  state.py        load/save the game, phase clock
  adjudicate.py   pure (game, orders) -> advanced game
  validate.py     per-order legality with readable errors
  query.py        board questions (units, centers, adjacency, builds)
  crypto.py       SealedBox order secrecy
  suggest.py      tactical suggestions (heuristic now; Cicero later)
orchestration/  CLIs the skills + workflow call
  new_game.py        initialize a match (+ adjudicator keypair)
  submit_orders.py   validate -> seal -> stage orders/<POWER>/<phase>.enc
  game_status.py     phone-friendly status (no decryption)
  run_adjudication.py the adjudicator (CI only; holds the private key)
  suggest_orders.py  print suggestions
site/           static GitHub Pages visualizer
  build_site.py     bake SVG board + JSON manifest from every game/* branch
  static/           mobile-first viewer (game dropdown, map, phase slider)
.claude/skills/ agent-facing skills (check-board-state, write-orders,
                run-cicero, consult-notes, play-a-turn)
.github/workflows/adjudicate.yml   the serverless adjudicator
.github/workflows/pages.yml        builds & deploys the visualizer
tests/          engine-fidelity + crypto + e2e tests
docs/RUNBOOK.md how to start a game and brief the 7 sessions

# Per-match files (only on game/<name> branches, never on main):
state/current.json   orders/<POWER>/<phase>.enc   history/<phase>.json   game/
```

## Quick start

```bash
./scripts/setup.sh && source .venv/bin/activate
pytest -q                       # verify the engine wrapper

# Initialize a match into the current tree (run on a game/<name> branch):
python -m orchestration.new_game --name frostbite --human ENGLAND
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the full new-game and
seven-sessions procedure, and `.claude/skills/play-a-turn` for the agent loop.

## Visualizer (GitHub Pages)

A static, phone-first viewer renders every game: pick a game from the dropdown,
scrub the phase slider to step through the seasons, and toggle between the **map**
(board + units + move arrows) and a **text** move list. It's pre-baked — boards
are rendered to SVG server-side, so the phone only loads static files (no live
API calls, no rate limits).

```bash
python site/build_site.py --out _site   # bake locally
python -m http.server -d _site 8000     # preview at localhost:8000
```

`.github/workflows/pages.yml` rebuilds and deploys on push to `main`, on a 30‑min
schedule, and on demand. **One-time setup:** in repo Settings → Pages, set the
source to **GitHub Actions**.

> The map and rendering come from the [`diplomacy`](https://github.com/diplomacy/diplomacy)
> package, which is **AGPL‑3.0+**. See [NOTICE.md](NOTICE.md).
