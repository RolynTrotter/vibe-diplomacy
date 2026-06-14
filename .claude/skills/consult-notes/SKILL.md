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

## Trust reads
- ENGLAND: <one line — current read, updated in place each phase>
- FRANCE: <one line>
- GERMANY: <one line>
- … (one line per power you care about)

## Next phase
- <2–3 bullet reminders for the coming phase only>
- <e.g. "Verify Channel DMZ held before committing F MAO">
```

## What NOT to put in notes

- **No orders log** — resolved moves live in `history/<phase>.json`, not here.
- **No board state** — units and centers come from the brief each turn.
- **No diplomatic transcripts** — the mail pool holds what was said.
- **No decision rationale** — think in your head, commit only the conclusion.
- **No stale phase sections** — the "Next phase" block is replaced every turn,
  not appended. Delete reminders once the phase is over.

The goal: a future you can read this in 10 seconds and know exactly what to do.
Fat notes burn tokens every phase and bury the signal.
