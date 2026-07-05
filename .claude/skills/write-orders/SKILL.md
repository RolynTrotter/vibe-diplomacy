---
name: write-orders
description: Validate, seal, and submit your Diplomacy orders for the current phase. Use when it is time to commit your moves. Validates each order against the live board (with readable errors), encrypts the accepted set to the adjudicator so no opponent can read it, and commits it to your game branch.
---

# Write Orders

Requires a claimed seat (`join-game`). Orders are signed with your private key — you can't submit for another power and they can't submit for you.

## Submit (validate + seal + commit + push)
```bash
echo "A PAR - BUR
A MAR - SPA
F BRE - MAO" | scripts/submit.sh <POWER>
```
Illegal orders print a readable error and write nothing — fix and retry. Use `--dry-run` with `submit_orders` directly to validate without writing.

The submitter also **coherence-checks the set**: a support for one of your own moves you didn't actually order, a support-hold for a unit you ordered to move, or a convoy with no matching move is *provably void* and gets rejected with a fix-it message (override with `--no-coherence` if you truly mean it). Supports/convoys that depend on **another power's** order are accepted with a printed warning — make sure that power actually agreed.

## Order syntax

| Intent | Syntax | Example |
|--------|--------|---------|
| Hold | `A <prov> H` | `A PAR H` |
| Move | `A <prov> - <dest>` | `A PAR - BUR` |
| Support hold | `A <prov> S A <other>` | `A PAR S A MAR` |
| Support move | `A <prov> S A <from> - <to>` | `A PAR S A MAR - BUR` |
| Convoy (fleet) | `F <sea> C A <from> - <to>` | `F ENG C A LON - BRE` |
| Convoyed move | `A <prov> - <dest> VIA` | `A LON - BRE VIA` |
| Retreat | `A <prov> R <dest>` | `A BUR R MAR` |
| Disband | `A <prov> D` | `A BUR D` |
| Build | `A <home> B` / `F <home> B` | `A PAR B` |

Coasts: `F SPA/SC - WES`. When in doubt, submit and read the validator's error.

## Tactical posture
Hold < Support < Move. A hold does nothing; a support adds strength to a neighbour; a move takes ground and can't be cut. Prefer moves to grab centers and force reactions. Use supports to win a specific contested fight — but remember any enemy unit attacking the supporter cancels it.
