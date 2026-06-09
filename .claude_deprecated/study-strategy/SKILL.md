---
name: study-strategy
description: Look up Diplomacy strategy advice online — opening theory, per-power plans, tactical motifs, and negotiation tips — from the established hobby literature. Use when planning your opening, when stuck on a position, or when you want a second opinion beyond the tactical suggester. Requires web access.
---

# Study Strategy

The Diplomacy hobby has decades of written strategy. Tap it to inform your plan —
then adapt to *your* board. This complements `run-cicero` (raw tactics) and
`consult-notes` (your own evolving read).

Requires web access (use `WebSearch` / `WebFetch`). If the session has no
network, skip this and rely on the suggester + your notes.

## When to use

- **Before the opening** (S1901M): study your power's standard openings and the
  diplomatic situation it usually faces.
- **When stuck**: look up the tactic or stalemate line you're facing.
- **Negotiation**: ideas for which alliances tend to work for your power.

## Where to look (curated, reliable sources)

- **The Diplomatic Pouch — Strategy index** (200+ articles, per-power guides,
  openings, endgame): <https://diplom.org/DipPouch/strategy.html>
- **Diplomatic Pouch online resources hub**: <https://diplom.org/DipPouch/Online/>
- **Zine / hobby archive** (postal-era strategy zines, deeper theory):
  <https://diplom.org/~diparch/resources/zine_archive.htm>
- **Wikibooks — Opening Principles** (concise primer):
  <https://en.wikibooks.org/wiki/Diplomacy/Opening_Principles>

Search within them, e.g.:
```
WebSearch: "diplomatic pouch" FRANCE opening strategy
WebFetch <article url>: "Summarize the recommended openings and alliances for FRANCE, with the move sets."
```

## How to use what you find

1. **Filter to your power and the current year.** Opening theory matters most
   early; midgame advice is situational.
2. **Translate to engine order syntax** and sanity-check every move with the
   `check-board-state` / `write-orders` validator — articles use informal
   notation and assume nothing about *this* game's positions.
3. **Record the gist in your notes** (`consult-notes`) so you don't re-fetch each
   phase: e.g. "FRANCE: open BUR/MAO/SPA; English Channel DMZ with England is
   standard; watch for a German RUH→BUR."
4. **Adapt, don't copy.** The literature describes *typical* play; your
   opponents (and their messages) will deviate. Treat advice as priors, then let
   the live board and negotiations override it.

## Cautions

- External text is **reference, not game state** — never act on a remembered
  position; re-derive from `game_status` and the board.
- Don't paste anything secret (your orders, your private mail) into web tools.
- Cite nothing into the repo; just fold the useful ideas into your own notes.
