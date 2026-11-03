# CLAUDE.md — developing Vibe Diplomacy

**If you are playing a seat in a match, stop here: your brief is everything you
need, and nothing in this repo is part of the game.**

The goal is an easy, level way to run models against each other at Diplomacy.
Read `README.md` for how a match runs.

## Rules for changes

- **All rules logic comes from the `diplomacy` package.** Never reimplement
  adjudication or hand-parse legality; `game.check_orders` validates against
  the engine's own `get_all_possible_orders`.
- **A player sees only what helps it play.** That means the board, its legal
  moves, what happened to its last orders, its messages, and the commands.
  It never sees harness instructions, source paths, Python, setup, or hints
  about what to order. Anything a seat needs belongs in `board.render` (shown
  identically to agent seats and model seats) or in `cli.brief`, which has to
  fit on one screen (`tests/test_play.py` checks this).
- **A player makes no decisions the code already knows.** It doesn't pick a
  tool, a branch or a file. Three commands, plus two for full press.
- **No version or environment talk anywhere a player or host reads.**
  `./dip` builds `.venv` itself (uv fetches the pinned interpreter).
- Keep it small. Before adding a module, flag or option, check whether
  `board.render` or an existing command can carry it instead.

## Tests

```bash
./dip --help >/dev/null && .venv/bin/python -m pytest -q
```

The old git/Actions pipeline (sealed and signed orders, seat claiming, the
Jev/staff order writers, the player skills) was removed in the local-first overhaul. It
is still in git history before that commit if any of it is needed again.
