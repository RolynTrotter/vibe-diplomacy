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
- **Orders are authenticated, not just secret.** Each power self-claims a seat
  (`join_game`), generating a signing key. Orders are **signed** and the
  adjudicator verifies them against the power's committed public key, so France
  can't submit Germany's orders. No human hands out auth — agents claim seats and
  divvy up the board themselves.
- **Full-press comms (optional).** With `--press full`, powers exchange private,
  signed messages sealed to each recipient (a `mail/` pool that hides even who's
  talking to whom). Negotiation stays secret during play and is revealed for the
  post-mortem only once the game ends.

## Layout

```
engine/         thin wrapper around the diplomacy engine
  state.py        load/save the game, phase clock
  adjudicate.py   pure (game, orders) -> advanced game
  validate.py     per-order legality with readable errors
  query.py        board questions (units, centers, adjacency, builds)
  crypto.py       SealedBox order secrecy + Ed25519 signing
  comms.py        full-press messaging (claims, sealed mail pool, reveal)
  context.py      per-power selective brief (conductor mode)
  suggest.py      tactical suggestions (heuristic now; Cicero later)
orchestration/  CLIs the skills + workflow call
  new_game.py        initialize a match (--press, adjudicator key reuse)
  join_game.py       claim a free seat (self-serve identity + keys)
  submit_orders.py   validate -> sign -> seal -> stage orders/<POWER>/<phase>.enc
  send_message.py    seal a signed message to a power / broadcast
  read_messages.py   trial-decrypt your inbox
  game_status.py     phone-friendly status (no decryption)
  run_adjudication.py the adjudicator (CI only; holds the private key)
  suggest_orders.py  print suggestions
  conduct.py         conductor helpers (roster + per-power brief)
site/           static GitHub Pages visualizer
  build_site.py     bake SVG board + JSON manifest from every game/* branch
  static/           mobile-first viewer (game dropdown, map/text/talk/notes, slider)
.claude/skills/ agent-facing skills (start-playing, conduct-match, join-game,
                play-a-turn, negotiate, check-board-state, write-orders,
                consult-notes)
.github/workflows/adjudicate.yml   the serverless adjudicator
.github/workflows/pages.yml        builds & deploys the visualizer
scripts/sync.sh push your files past other sessions without conflicts
tests/          engine-fidelity + crypto + comms/auth + e2e tests
docs/RUNBOOK.md how to start a game and brief the 7 sessions

# Per-match files (only on game/<name> branches, never on main):
state/current.json   orders/<POWER>/<phase>.enc   history/<phase>.json
players/<POWER>.json   mail/*.enc   game/   (secrets/ is local + gitignored)
```

## Quick start

```bash
./scripts/setup.sh && source .venv/bin/activate
pytest -q                       # verify the engine wrapper

# Initialize a match into the current tree (run on a game/<name> branch):
python -m orchestration.new_game --name frostbite --human ENGLAND
```

**To drop an agent into a game**, point a session at the repo and say
*"play vibe-diplomacy on branch `game/<name>`"* — the `start-playing` skill finds
the game, claims a free power, and starts. Open seven and they self-organize.

**Or run the whole match from one session** with the `conduct-match` skill: it
spawns each power as a scoped subagent (callstack-first, native subagents as a
toggle), hands each only its own context, and adjudicates between phases. Great
for self-play and evaluation; for distrusting players use the seven-session path
above. The two compose, and both go through the same signed/sealed pipeline.

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the full new-game and
seven-sessions procedure, and `.claude/skills/play-a-turn` for the agent loop.

## Visualizer (GitHub Pages)

A static, phone-first viewer renders every game: pick a game from the dropdown,
scrub the phase slider to step through the seasons, and toggle between the **map**
(board + units + move arrows), a **text** move list, **talk** (the message
threads), and **notes** (each power's private strategy notebook). Like messages,
notebooks stay sealed during play and are revealed for the post-mortem only once
the game ends. It's pre-baked — boards are rendered to SVG server-side, so the
phone only loads static files (no live API calls, no rate limits).

```bash
python site/build_site.py --out _site   # bake locally
python -m http.server -d _site 8000     # preview at localhost:8000
```

`.github/workflows/pages.yml` rebuilds and deploys on push to `main`, on a 30‑min
schedule, and on demand. **One-time setup:** in repo Settings → Pages, set the
source to **GitHub Actions**.

> The map and rendering come from the [`diplomacy`](https://github.com/diplomacy/diplomacy)
> package, which is **AGPL‑3.0+**. See [NOTICE.md](NOTICE.md).
