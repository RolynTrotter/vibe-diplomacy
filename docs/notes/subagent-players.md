# Running players as scoped subagents (one session per match)

**Status:** implemented (conductor mode, callstack-first with a native toggle) —
see `.claude/skills/conduct-match`, `orchestration/conduct.py`, and
`engine/context.py`. Prompted by a look at
[unwind-labs/callstack](https://github.com/unwind-labs/callstack).
**Question:** can we run all seven powers as subagents *with selective context*
inside a single Claude Code session, instead of seven separate sessions?

**Short answer:** yes, and it's a great fit for self-play, evaluation, and a solo
human running a sandbox. It does **not** replace the multi-session + crypto path
for genuinely distrusting players — it sits alongside it. The two compose.

---

## Why this is appealing

Today a match needs **seven parallel sessions**, one per power, isolated by
cryptography (per-power keypairs, sealed orders/mail). That's the right model
when seven distrusting parties play. But for *me running a test match*, or *an
AI-vs-AI benchmark*, spinning up and shepherding seven sessions is the fiddly
part. One conductor session that spawns the players would collapse that.

The key realization: **a fresh subagent only sees the prompt you hand it.** That
*is* "selective context" — France's subagent never receives Germany's notes or
inbox, so it can't act on them, without any crypto involved.

## Two ways to get scoped subagents

### 1. Native Claude Code subagents (zero dependency)
The built-in `Agent`/Task tool already:
- launches a **fresh-context** subagent that receives only the prompt (selective
  context by construction), and
- runs **multiple subagents in parallel** in one turn.

This is enough to prototype the whole idea with no new dependency. Recommended
starting point.

### 2. callstack plugin (MIT) — nicer ergonomics
[callstack](https://github.com/unwind-labs/callstack) adds function-call
semantics on top: a `/call` operator with **fresh mode** (only the task string
crosses the boundary — exactly our isolation need), **parallel fan-out**
(`/call do X, do Y in parallel`, `CALLSTACK_MAX_FANOUT=64` ≫ 7), recursive
nesting, a **yield-to-root** protocol (a buried subagent can ask the human
without relaying through frames), deterministic unwind, and prompt-cache reuse in
fork mode. MIT-licensed, installs via the Claude Code marketplace.

It's worth adopting if/when we want **multi-round negotiation** (nested fan-out)
or **resumable yields** (a power pausing to ask the operator a question). For a
first cut, native subagents are simpler.

> Note: callstack auto-approves tool-permission requests for forked sessions
> (no human in the loop). Review that against our safety posture before adopting.

## Proposed architecture: the "conductor"

One session = the **match conductor**. Per phase:

1. **Slice context** for each live power (selective): the public board
   (`state/current.json`, recent `history/`), that power's own `notes/<POWER>.md`,
   its decrypted inbox (full-press), and a short strategy brief. *Never* another
   power's private data.
2. **Fan out** one subagent per power, in parallel, each fresh:
   > "You are FRANCE in S1901M. Board: … Your notes: … Your inbox: … Decide your
   > orders (and, full-press, your messages). Return them as JSON."
   Parallel fresh subprocesses can't observe each other's pending output, which
   preserves Diplomacy's simultaneity for free.
3. **Collect** each power's returned orders/messages.
4. **Adjudicate.** Two options:
   - *Full pipeline* (reuse `submit_orders` → `run_adjudication`): produces the
     same sealed/signed artifacts, so a **mixed** match (some powers as
     subagents, some as independent crypto sessions) still works.
   - *Local fast path* (pure self-play): call `engine.adjudicate.adjudicate(game,
     orders_by_power)` directly in-memory — no sealing/signing needed when one
     trusted party runs everyone. Simpler and faster.
5. **Advance & persist:** write `state/current.json` + `history/`, update each
   power's notes, and commit/push so the **Pages visualizer** shows the game
   (and `mail/revealed.json` at game end).
6. Repeat until solo/draw.

**Full-press** adds negotiation rounds before step 2: fan out seven
"read inbox → send messages" subagents, deliver, repeat N rounds, then collect
orders. (This is where callstack's nested parallelism earns its keep.)

A single-session conductor can also hold the adjudicator key and **adjudicate
locally**, so this mode needs **no GitHub Actions loop at all** — the CI
adjudicator stays for the multi-session mode.

## The trade-off that matters: trust model

Our crypto isolation was built for *mutually distrusting separate sessions*. In
one-session subagent mode:

- Isolation is enforced by **context boundaries** (what the conductor hands each
  subagent), **not cryptography**. The conductor — and whoever runs it — can see
  everything.
- That's exactly right for **self-play, AI evaluation, Cicero-style
  benchmarking, or a solo sandbox** — the "reduce sessions" use case.
- It's **weaker** for competitive play among distrusting parties. Keep the
  multi-session + crypto path for that.
- They **compose:** run, say, 5 powers as conductor subagents and 2 as
  independent crypto sessions. Crypto protects the independent two; selective
  context handles the subagents. The signed-orders check still stops forgery
  across the trust boundary.

So we **keep** the crypto/Epic-5 work; this is an additive *conductor mode*.

## Honest caveats

- **Not truly independent players.** One model running all seven can homogenize
  strategy or implicitly "collude" through the shared operator. Mitigate with
  fresh context (no shared memory), distinct per-power strategy briefs, and maybe
  varied temperature/persona. For rigorous head-to-head eval, separate sessions
  (or separate models) remain the gold standard.
- **Cost:** fresh mode forgoes the parent-prefix cache, but each power's context
  is small (board + own notes/inbox), so per-call cost is modest.
- **Determinism:** ensure siblings never see each other's in-progress orders
  (fresh subprocesses already guarantee this).

## What it would take to build (sketch)

- `scripts/conduct.py` (or a `conduct-match` skill): the phase loop that slices
  context, fans out per-power subagents, collects, adjudicates, persists.
- A per-power subagent prompt that returns structured `{orders, messages}` JSON.
- A context-slicing helper reusing `engine.query`, `engine.comms.read_inbox`, and
  `notes/`.
- Reuse `engine.adjudicate` (fast path) or the existing CLIs (full pipeline).
- Optional: install callstack for ergonomic fan-out / negotiation rounds /
  resumable yields.

## Recommendation

Prototype a **native-subagent conductor** for gunboat self-play first (smallest
step, no new dependency, reuses `engine.adjudicate`), confirm it produces a
visualizer-watchable match from one session, then layer in full-press
negotiation rounds — adopting **callstack** at that point if its nested fan-out
and yield-resume pay off. Track as a ticket.
