---
name: consult-notes
description: Read and update your power's private strategy notebook — long-term plans, who you trust, intended alliances, and tactical reminders that must persist across phases and sessions. Use at the start of a turn to recall your plan and at the end to record what changed.
---

# Consult Notes

Your brief (from `scripts/turn.sh`) already includes your latest notes. No extra read needed.

## Update
Overwrite `notes/<POWER>.md` each phase — never append. Target: under 250 words — **the brief truncates anything past ~2,500 characters**, so bloated notes silently lose their tail.
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

## The DEAL: ledger

Record every standing agreement as its own line starting with `DEAL:` —
anywhere in the file:

```markdown
DEAL: ENGLAND — Channel DMZ, no fleets in ENG either side — until end 1903
DEAL: GERMANY — BUR is mine, BEL is theirs — standing
```

These lines are extracted from the RAW file and surfaced in your brief in a
dedicated "Your commitments" section right before you write orders — they
survive even if the rest of your notes get truncated. Delete a DEAL line when
the deal dies (or when you decide to break it — deliberately).

## What NOT to write
- Resolved orders — already in `history/`
- Board state — comes from the brief
- Diplomatic transcripts — live in the mail pool
- Decision rationale — think it, don't commit it
