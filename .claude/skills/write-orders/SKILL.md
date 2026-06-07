---
name: write-orders
description: Validate, seal, and submit your Diplomacy orders for the current phase. Use when it is time to commit your moves. Validates each order against the live board (with readable errors), encrypts the accepted set to the adjudicator so no opponent can read it, and commits it to your game branch.
---

# Write Orders

You play exactly one power on exactly one `game/<name>` branch. You submit your
orders by committing a single sealed file: `orders/<YOUR_POWER>/<phase>.enc`.

**You must have claimed your seat first** (the `join-game` skill). Orders are
**signed with your power's private key** so the adjudicator can prove they came
from you — nobody else can submit your orders, and you can't submit theirs. If
you haven't claimed, `submit_orders` will tell you to run `join_game`.

## 1. Validate + seal locally

```bash
source .venv/bin/activate   # see check-board-state for first-time setup

echo "A PAR - BUR
A MAR - SPA
F BRE - MAO" | python -m orchestration.submit_orders --power FRANCE
```

- Orders may be newline- or semicolon-separated; `#` lines are ignored.
- Every order is checked against the engine's list of legal moves. If any are
  illegal you get a precise message **and the file is not written** — fix and
  retry. Use `--dry-run` to validate without writing.
- On success it writes `orders/FRANCE/<phase>.enc` (orders sealed to the
  adjudicator's public key; opponents cannot read it).

## 2. Commit the sealed file to your branch

Commit ONLY your own `.enc` file to your `game/<name>` branch (use the GitHub
MCP `create_or_update_file` / `push_files`). Do not touch `state/`, `history/`,
`game/`, or other powers' order files — the adjudicator owns those.

When every live power has committed (or the deadline passes), the adjudication
GitHub Action decrypts all orders, resolves the phase, advances the board, and
reveals everyone's orders into `history/`.

## Order syntax cheat-sheet

| Intent           | Syntax                         | Example                  |
|------------------|--------------------------------|--------------------------|
| Hold             | `A <prov> H`                   | `A PAR H`                |
| Move / attack    | `A <prov> - <dest>`            | `A PAR - BUR`            |
| Support a hold   | `A <prov> S A <other>`         | `A PAR S A MAR`          |
| Support a move   | `A <prov> S A <from> - <to>`   | `A PAR S A MAR - BUR`    |
| Convoy (fleet)   | `F <sea> C A <from> - <to>`    | `F ENG C A LON - BRE`    |
| Convoyed move    | `A <prov> - <dest> VIA`        | `A LON - BRE VIA`        |
| Retreat          | `A <prov> R <dest>`            | `A BUR R MAR`            |
| Disband (retreat)| `A <prov> D`                   | `A BUR D`                |
| Build            | `A <home> B` / `F <home> B`    | `A PAR B`                |
| Disband (adjust) | `A <prov> D`                   | `A MAR D`                |

Coasts: `F SPA/SC - WES`. The validator lists the exact legal strings for any
unit if you get the form wrong, so when in doubt, submit and read the errors.
