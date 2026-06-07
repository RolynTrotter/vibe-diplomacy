---
name: consult-notes
description: Read and update your power's private strategy notebook — long-term plans, who you trust, intended alliances, and tactical reminders that must persist across phases and sessions. Use at the start of a turn to recall your plan and at the end to record what changed.
---

# Consult Notes

Your container is ephemeral; your memory is not. Keep durable strategy in
`notes/<YOUR_POWER>.md` on your game branch. Read it when you start a turn,
append to it when your plans or trust assessments change.

> Privacy in gunboat: there is no in-game messaging yet, so these are private
> self-notes. When full-press comms land (plan Epic 5) notes become central to
> tracking promises and betrayals.

## Read your notes

```bash
cat notes/FRANCE.md 2>/dev/null || echo "(no notes yet)"
```

## Update your notes

Edit `notes/FRANCE.md`, then commit it to your game branch with the GitHub MCP
(`create_or_update_file`). Commit ONLY your own notes file.

## Suggested structure

```markdown
# FRANCE — strategy notebook

## Standing plan
- Open to the Atlantic + Iberia; aim for MAO, SPA, POR by Fall 1901.

## Trust / read on opponents
- ENGLAND: bounced me in the Channel S1901M — treat as hostile.
- GERMANY: moved away from me — possible ally vs England.

## Reminders for next phase
- Don't leave MAR undefended if Italy builds a fleet.
```

Keep it short and current — prune stale lines so the top of the file always
reflects your live plan.
