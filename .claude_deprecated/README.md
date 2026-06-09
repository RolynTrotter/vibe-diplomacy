# Deprecated skills

Skills that have been retired from `.claude/skills/` but kept here for
reference (and easy revival). They are **not** loaded as active skills.

- **run-cicero** — tactical order suggester (heuristic now, real Cicero later).
  On ice: the real Cicero engine isn't being built for a while, and we're
  steering players via the board, notes, and negotiation instead.
- **study-strategy** — look up Diplomacy hobby strategy literature online.
  On ice: the models currently playing aren't getting much from perusing the
  long-form literature mid-game.

To bring one back, `git mv` its folder back under `.claude/skills/` and restore
the references that were removed (README skill list, the `play-a-turn` loop).
