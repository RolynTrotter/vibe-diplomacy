---
name: consult-notes
description: Read and update your power's private strategy notebook — long-term plans, who you trust, intended alliances, and tactical reminders that must persist across phases and sessions. Use at the start of a turn to recall your plan and at the end to record what changed.
---

# Consult Notes

Your container is ephemeral; your memory is not. Keep durable strategy in
`notes/<YOUR_POWER>.md` on your game branch. The brief you receive at the start
of a turn already includes your latest notes — no extra read needed.

## Read your notes

Your brief (from `scripts/turn.sh`) already includes them. Done.

## Update your notes

**Overwrite the file each phase** — do not append. Keep it under 250 words.

```bash
# Write your updated notes, then push:
scripts/sync.sh "<POWER> notes" notes/<POWER>.md
```

## Required format — three sections only

```markdown
# <POWER> — strategy notebook

## Standing plan
- <3–5 bullets: strategic goals that persist across the game>
- <e.g. "Secure Iberia by F1901, then pivot Atlantic">

## Trust & deals
- ENGLAND: trusted | DMZ: F ENG (mutual no-go both directions)
- FRANCE: suspicious — probed BUR despite pact | non-aggression: BUR/MAR quiet
- GERMANY: neutral | deal: Belgium conceded to GER
- ITALY: reliable | DMZ: PIE mutual, ADR mutual
- RUSSIA: hostile, 4 centers | no deal
- TURKEY: unknown | no deal
- <one line per power: trust read THEN active treaty terms, updated in place>

## Next phase
- <2–3 bullet reminders for the coming phase only>
- <e.g. "Verify Channel DMZ held — if ENG in ENG, treat as hostile">
```

The `|` separator distinguishes your read (left) from binding commitments (right).
Before submitting orders, glance at active deals and confirm none of your moves
violate them. If you're deliberately breaking a deal, note it explicitly so you
remember the diplomatic fallout.

## What NOT to put in notes

- **No orders log** — resolved moves live in `history/<phase>.json`, not here.
- **No board state** — units and centers come from the brief each turn.
- **No diplomatic transcripts** — the mail pool holds what was said.
- **No decision rationale** — think in your head, commit only the conclusion.
- **No stale phase sections** — the "Next phase" block is replaced every turn,
  not appended. Delete reminders once the phase is over.

The goal: a future you can read this in 10 seconds and know exactly what to do.
Fat notes burn tokens every phase and bury the signal.
