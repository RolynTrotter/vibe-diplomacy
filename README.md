# Vibe Diplomacy

Run models against each other at **Diplomacy** on a level playing field. Every
seat gets the same plain-text board and the same few commands. The rules,
adjudication and order secrecy are handled for them, out of sight.

The [`diplomacy`](https://github.com/diplomacy/diplomacy) package
(DATC-compliant) does all the rules work. This repo stores matches, shows each
power its board, and drives model seats.

## Play a match

**1. Create it** (the first run also builds the environment by itself):

```bash
./setup.sh test --press none
```

**2. Hand each seat to a player.** There are two ways, and you can mix them.

- **Agents** (Claude Code, Codex, a human, anything that can run a shell
  command): give each one its brief, `games/test/briefs/<POWER>.md`. The brief
  is one page. It lists three commands (`board`, `submit`, `wait`), plus `send`
  and `inbox` in full press. The agent can work from any directory and never
  needs to read this repo.
- **Models**, called directly through any OpenAI-compatible endpoint (LM
  Studio, Ollama, vLLM, OpenRouter...), all seats in parallel:

  ```bash
  ./dip run test --model qwen3-8b --base-url http://localhost:1234/v1
  ./dip run test --model fake --seat FRANCE=llama3@http://other:8000/v1 \
                 --seat GERMANY=claude:sonnet --agents ENGLAND
  ```

A phase resolves as soon as every power has submitted, or when its deadline
passes (`--deadline`, 30 minutes by default). Units without orders hold. The
game ends at `--max-year` (1910 by default) or with an 18-centre win. Nothing
needs a server, GitHub, keys or a paid API.

```bash
./dip status              # where every match stands, and who it's waiting on
./dip advance test        # resolve now; missing orders hold
./dip site --serve 8000   # replay viewer: map, orders, messages, notes
```

## Model seats

`./dip run` makes one stateless call per decision. The prompt is the seat's
board, its inbox and its own notes, followed by what to write. The reply is
free text:

```
TO ENGLAND: Channel DMZ this year?
TO SELF: Germany is massing on Burgundy
```
...followed by the orders in a fenced code block. A reply with no usable orders
gets one retry with the errors spelled out, then its units hold. If a model
returns only reasoning, the reasoning is parsed. In full press, each movement
phase has `--rounds` rounds of talk (2 by default) before orders.

Seat specs: `<model>` (at `--base-url`), `openai:<model>@<url>`,
`claude:<model>` (the `claude` CLI with no tools), `agent` (played from
outside), `fake` (random legal orders). `--concurrency` caps simultaneous
calls per endpoint. `--images` attaches the board picture for vision models.
Each call's transcript is saved in `games/<name>/log/`.

## Layout

```
dip, setup.sh   the one entry point; builds .venv on first use
vibe/
  game.py       a match on disk: seats, orders, adjudication, mail, notes
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
and results are written to `history/` after each phase. Messages and notes
appear in the viewer only once the game is over.

The map and rendering come from the `diplomacy` package, which is
**AGPL-3.0+**. See [NOTICE.md](NOTICE.md).
