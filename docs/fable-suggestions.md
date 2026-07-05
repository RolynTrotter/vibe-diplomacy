# Bot-tournament improvements — diagnosis & suggestions

Goal: bot-v-bot tournaments with smooth comms, mixing weak local models and
capable API models, without burning the credit budget in three game-years.
This doc is the *notes* half; the code half (marked ✅) lands in the same
branch. Everything here is grounded in the finished games on the `game/*`
branches.

## What the past games actually show

Counting result tags across every movement phase in `history/`:

| game | model class | M-phases | orders | void supports | failed convoys | bounces |
|---|---|---|---|---|---|---|
| lm-studio-1 | weak local | 100 | 3105 | **1587 (51%)** | 354 (11%) | 601 |
| proving-ground | weak local | 10 | 290 | **161 (55%)** | 20 | 38 |
| cloud-1 | capable API | 10 | 290 | 2 | 1 | 86 (30%) |
| qwen-test-2 | local qwen | 4 | 95 | 0 | 0 | 8 |

Three distinct failure modes fall out of this and out of reading the
notebooks (`notes/<POWER>.md`) on those branches:

1. **Weak models waste most of their orders on incoherent sets.** In
   `lm-studio-1`, *62% of all orders did literally nothing*: supports for
   moves nobody ordered ("F BRE S F MAO - ENG" while MAO was ordered to POR),
   support-holds for units that were ordered to move, armies ordered `VIA`
   with no fleet convoying them, and plain self-bounces (France ordering both
   `F MAO - POR` and `A SPA - POR` in the same set). Every one of these
   passes validation because each order is *individually* legal —
   `validate.py` checks membership in `get_all_possible_orders()`, which says
   nothing about whether the set is self-consistent.

2. **Board-state hallucination and rules misconceptions.** The brief gives
   units/centers/standings but no geometry, so models reason about adjacency
   from priors and get it wrong. A qwen notebook on `game/qwen-test-2`
   records "**MAR LOST** when A MAR→Gascony moved out" — a center can't be
   lost by vacating it, and that false belief steered France's whole plan.
   The capable models mostly avoid this but spend tool calls re-deriving
   geometry (`query.adjacencies`, `province_info`) every single phase.

3. **Memory is only as good as the notebook, and notebooks bloat.** The
   `consult-notes` skill asks for <250 words, but nothing enforces it:
   `cloud-1` FRANCE's notes ran to pages of per-phase order dumps and
   "expected outcomes", all re-injected into the brief *every negotiation
   round and orders round* — pure token burn that also crowds out the actual
   standing plan. Meanwhile the brief only recaps the *last* phase, so an
   ephemeral agent has no cheap way to see the arc of the game (who's been
   growing, who stabbed whom in 1902).

And the meta-problem behind "games end early": every player turn is a full
headless Claude Code session — agentic loop, tool calls, `turn.sh` re-printing
a brief that was *already in the prompt* (`run_match._build_task` embeds the
brief, then step 1 tells the agent to run `scripts/turn.sh`, which regenerates
it). Seven powers × negotiation rounds × phases multiplies all of that.

## Suggestions

### 1. ✅ Order-set coherence check (biggest single lever for weak models)

New `engine/coherence.py`, wired into `submit_orders` after per-order
validation. It classifies intra-power problems that are *provably* wasted
orders as *errors* (rejected with a readable fix-it message, same UX as
validation errors — the submitting agent already knows how to retry), and
cross-power assumptions as *warnings* (printed, still accepted):

- **error** — supporting your own unit's move when that move isn't in your
  set ("A PAR S A MAR - BUR" but MAR is ordered elsewhere): guaranteed void.
- **error** — support-holding your own unit that you ordered to move:
  guaranteed void.
- **error** — convoying your own army on a route the army wasn't ordered
  (or `VIA` army with no own fleet convoying and no foreign fleet possible).
- **warning** — two of your own units moving to the same province
  (self-bounce; legal tactic when deliberate, usually a blunder).
- **warning** — support/convoy that depends on *another power's* order
  ("assumes RUSSIA orders A UKR - GAL") — legitimate in full-press, but the
  model should see the dependency spelled out.

Had this existed, roughly half of every weak-model turn in `lm-studio-1`
would have come back with "fix these two orders" instead of silently rotting.
`--no-coherence` on `submit_orders` is the escape hatch.

### 2. ✅ Tactical annex in the power brief (kill geometry hallucination)

`context.power_brief` now appends, per phase type, engine-derived facts the
models were burning tool calls (or guessing) to get:

- **Movement:** for each of your units, its legal move destinations with
  occupancy annotations (`A MAR → BUR, GAS, PIE (ITALY A), SPA`), plus a
  "threats" list — every enemy unit adjacent to one of your supply centers.
- **Retreat:** the legal retreat options per dislodged unit.
- **Adjustment:** open home centers you can build in, or units to disband.
- A three-line **rules crib** correcting the misconceptions that actually
  appeared in past games (centers change hands only when occupied at the end
  of Fall; a support is cut by any attack on the supporter; a supported move
  must be ordered exactly).

This is ~25 lines of brief for 7 units, all deterministic, and it makes the
"no tools, one completion" backend (suggestion 4) viable.

### 3. ✅ Cross-game memory: center-change digest + notes cap

- The brief now includes a **year-by-year digest of supply-center changes**
  ("1902: FRANCE +SPA +POR; RUSSIA +SWE; TURKEY −BUL…") computed from the
  engine's state history. One line per year buys an ephemeral agent the whole
  arc of the game — who is snowballing, which alliance actually fired —
  without re-reading `history/*.json`.
- Notes are **truncated at ~2,500 characters** when injected into the brief,
  with a visible "(truncated — keep notes under 250 words)" marker, so a
  bloated notebook costs the power that wrote it a nudge instead of costing
  every downstream prompt unbounded tokens. (The `consult-notes` format is
  good; it just needed teeth.)

### 4. ✅ `raw` player backend: one completion per turn, no agentic loop

`player_agent.py` grows a `RawChatAgent` (`--backend raw`): instead of
spawning `claude -p` with the full tool loop, it makes **one direct
chat-completions call** (LM Studio's OpenAI-compatible endpoint for `local`
seats, Anthropic Messages for `api` seats), asks for orders in a fenced
block / messages as `TO <POWER>: …` lines, parses the reply, and drives the
*same* join/submit/send CLIs the skills use — identical signed/sealed
artifacts. On validation or coherence rejection it retries once with the
error text appended.

Why this matters for the north star:

- A weak local model gets a *fill-in-the-form* task instead of an open-ended
  agentic session it can't drive. With the annex (suggestion 2) in the brief,
  it never needs a tool.
- Token cost per power-turn drops from a whole session (system prompt +
  tools + N round trips) to one prompt ≈ the brief. That is the difference
  between a game dying in 1903 and finishing.
- Mixed tournaments become natural: `--backend raw` for the seven cheap
  seats, or per-seat later (`backend` as a `SeatSpec` field is the obvious
  follow-up — the factory already takes one string).

`run_match._build_task` gains a `style` ("agentic" vs "chat"), so raw seats
get a compact instruction ("reply with only your orders") instead of skill
walkthroughs they can't execute — and agentic seats no longer get told to
re-run `turn.sh` when the brief is already in the prompt.

### 5. ✅ Stop paying full price for trivial phases

Retreat and adjustment tasks are now slimmed in `_build_task`: no negotiation
prompt, no notes-update step, just "here are your options, submit". (The
roster already skips powers with nothing to decide; this covers the ones with
exactly one decision.)

### 6. ✅ Order-outcome feedback in the brief

The last-phase recap only listed orders + raw result tags; weak models never
close the loop on *why* their order failed (the same support stayed void for
ten straight phases in lm-studio-1). The brief now explains each of your
failed orders: "VOID — your own unit was actually ordered 'A MAR - SPA'",
"support CUT — the supporting unit was attacked", "NO CONVOY — no fleet
carried this move", reusing the coherence parser against `order_history`.

### 7. ✅ Negotiation digest (constant-cost inbox)

In long full-press games the inbox (last 30 messages, re-injected every
round) dominates the brief. Raw mail is now shown only for the last two
phases that produced any; everything older collapses to a per-partner count
("GERMANY ×7 (last F1903M)") with a pointer to `read_messages --with` for
re-reading a thread and to the DEAL ledger for anything worth keeping.

### 8. ✅ Commitments ledger

Lines starting `DEAL:` in `notes/<POWER>.md` are extracted from the *raw*
file (so notes truncation can never eat a treaty) and surfaced in their own
"Your commitments" brief section next to the orders prompt — cheap insurance
against the "agreed a DMZ, then absent-mindedly moved in" pattern visible in
several games. Full-press briefs with no deals recorded show the syntax hint.

### 9. ✅ Brief-section toggles

All the player-facing additions (outcomes, digest, annex+crib, commitments,
inbox digesting) can be switched off per match: a `brief:` mapping in the
match YAML / `new_game --brief-json` lands in `game/config.json` and
`context.brief_options` applies it. Defaults: everything on.

### 10. ✅ Tournament harness with quality metrics

`python -m orchestration.run_tournament --spec … --games 7 --backend raw`
runs N games through the ordinary `Conductor` (own directory + own
adjudicator key each), rotating seat assignments one power per game so no
model is stuck opening as Austria. Scoring reads each game's revealed
`history/` and aggregates per power *and* per seat (model+persona):

- classic outcome: avg centers, survival rate, topped-the-board, solo wins;
- **void_rate** — provably wasted orders (the metric that separated weak
  from capable models 51% vs 0.7% in past games; the table at the top of
  this doc is now a first-class artifact);
- **warning_rate** — self-bounces + orders depending on another power's
  simultaneous order (the coherence warning class; high isn't bad per se —
  deliberate self-bounces are a real tactic — but high *with* high
  void_rate means flailing, and rising cross-power dependency with *low*
  void_rate usually means actual coordination);
- bounce_rate.

One `<name>-tournament.json` plus a printed table per tournament.

## Not built here — recommended next, in order

1. **Per-seat `backend`** in `SeatSpec`, so one match mixes raw-local seats
   with headless-Claude seats. Small change; the factory signature already
   fits.
2. **Cheaper adjudication cadence for CI mode** — batch `mail/` pushes per
   negotiation round rather than per message to cut Actions minutes (only
   relevant when going back to `adjudication: ci`).
