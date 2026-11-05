# Vibe Diplomacy

Run models against each other at **Diplomacy** on a level playing field. Every
seat gets the same plain-text board and the same few commands. The rules,
adjudication and order secrecy are handled for them, out of sight.

The [`diplomacy`](https://github.com/diplomacy/diplomacy) package
(DATC-compliant) does all the rules work. This repo stores matches, shows each
power its board, and drives model seats.

**Hosting a match as an agent?** Read
[.claude/skills/run-a-match/SKILL.md](.claude/skills/run-a-match/SKILL.md)
and nothing else. It has every command, what each output means, what a
finished game looks like and what to do when a phase stalls. You won't need
the source.

## Play a match

**1. Create it** (the first run also builds the environment by itself):

```bash
./setup.sh test --press none --model flint --base-url http://127.0.0.1:1234/v1
```

This checks that the model answers and prints one line saying so, then prints
the next command. Matches are local state in `games/` (gitignored); any name
works.

**2. Hand each seat to a player.** There are two ways, and you can mix them.

- **Agents** (Claude Code, Codex, a human, anything that can run a shell
  command): give each one its brief, `games/test/briefs/<POWER>.md`. The brief
  is one page. It lists three commands (`board`, `submit`, `wait`), plus `send`
  and `inbox` in full press. The agent can work from any directory and never
  needs to read this repo.
- **Models**, called directly through any OpenAI-compatible endpoint (LM
  Studio, Ollama, vLLM, OpenRouter...), all seats in parallel:

  ```bash
  ./dip run test            # returns at once; the game plays in the background
  ./dip status test         # phase, who it waits on, runner alive?, latest line
  ./dip run test --seat FRANCE=llama3@http://other:8000/v1 \
                 --seat GERMANY=claude:sonnet --agents ENGLAND
  ```

  `--foreground` keeps the run attached; `./dip stop test` stops it and
  `./dip run test` resumes it.

A phase resolves as soon as every power has submitted, or when its deadline
passes (`--deadline`, 30 minutes by default). Units without orders hold. The
game ends at `--max-year` (1910 by default) or with an 18-centre win. Nothing
needs a server, GitHub, keys or a paid API.

```bash
./dip check --model M --base-url U   # does the endpoint answer?
./dip advance test        # resolve now; missing orders hold
./dip site --serve 8000   # replay viewer: map, orders, messages, notes
```

## Model seats

`./dip run` makes one stateless call per decision. The prompt is the seat's
board and its inbox, followed by what to write. The reply is
free text:

```
TO ENGLAND: Channel DMZ this year?
```
...followed by the orders in a fenced code block. A reply with no usable orders
(cut off at `--max-tokens`, no orders block, or illegal orders) is finished
rather than redone: one short call quotes the seat's own reply back with what
was wrong and asks only for the orders. If that fails too, its units hold. If a model
returns only reasoning, the reasoning is parsed. In full press, each movement
phase has `--rounds` rounds of talk (2 by default) before orders.

Seat specs: `<model>` (at `--base-url`), `openai:<model>@<url>`,
`claude:<model>` (the `claude` CLI with no tools), `agent` (played from
outside), `fake` (random legal orders). `--concurrency` caps simultaneous
calls per endpoint. `--images` attaches the board picture for vision models.
Replies are streamed. A call fails only after `--timeout` seconds (180 by
default) with no tokens at all, or after `--call-limit` (an hour), so a slow
local model is never cut off mid-answer. `--max-tokens` is 8000 by default,
because reasoning models spend most of it thinking. `--reasoning-effort low` asks for less thinking where the server
supports it. Each call's transcript is saved in `games/<name>/log/`, and
each phase adds a line to `games/<name>/progress.log`, which `./dip status`
shows. To have an agent host a match, point it at the `run-a-match` skill.

## Layout

```
dip, setup.sh   the one entry point; builds .venv on first use
vibe/
  game.py       a match on disk: seats, orders, adjudication, mail
  board.py      the board as one power sees it (legal moves, outcomes, nearby centres)
  cli.py        ./dip: player commands and host commands, plus the seat brief
  run.py        model seats: OpenAI-compatible / claude CLI / fake, in parallel
  mapviz.py     labelled board picture
  site.py       static replay viewer (+ static/)
tests/
games/<name>/   one directory per match (gitignored)
```

## Secrecy and fairness

Each seat acts only through its own token, and nothing a seat is shown mentions
another seat's files, so orders stay hidden by not being pointed at. This keeps
honest players honest. It does not stop a hostile one: an agent with shell
access that goes digging could find `games/<name>/pending/`. A match's orders
and results are written to `history/` after each phase. Messages appear in the viewer only once the game is over.

The map and rendering come from the `diplomacy` package, which is
**AGPL-3.0+**. See [NOTICE.md](NOTICE.md).
