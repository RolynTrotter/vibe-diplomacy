---
name: consult-notes
description: Read and update your power's private strategy notebook — long-term plans, who you trust, intended alliances, and tactical reminders that must persist across phases and sessions. Use at the start of a turn to recall your plan and at the end to record what changed.
---

# Consult Notes

Your brief (from `scripts/turn.sh`) already includes your latest notes. No extra read needed.

## Update
Overwrite `notes/<POWER>.md` each phase — never append. Target: under 250 words.
```bash
scripts/sync.sh "<POWER> notes" notes/<POWER>.md
```

## Format — three sections only

```markdown
# <POWER> — strategy notebook

## Standing plan
- <3–5 strategic goals, stable across the game>

## Trust & deals
- ENGLAND: trusted | DMZ: F ENG mutual (no fleet in ENG from either side)
- FRANCE: suspicious — probed BUR | non-aggression: BUR/MAR quiet both ways
- GERMANY: neutral | deal: Belgium conceded to GER
- ITALY: reliable | DMZ: PIE + ADR mutual
- RUSSIA: hostile, 4 centers | no deal
- TURKEY: unknown | no deal

## Next phase
- <2–3 reminders for the coming phase only — replaced every turn>
```

The `|` separates your read (left) from active treaty terms (right). **Check deals before submitting orders** — if a move would violate one, either honor it or note the betrayal explicitly.

## What NOT to write
- Resolved orders — already in `history/`
- Board state — comes from the brief
- Diplomatic transcripts — live in the mail pool
- Decision rationale — think it, don't commit it
