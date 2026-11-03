---
name: run-a-match
description: Run a whole Diplomacy match between models from start to finish, and check on it. Use when asked to run, host or conduct a vibe-diplomacy game or to pit models against each other. Not for playing a single seat (a seat's brief covers that).
---

# Run a match

You are the host. **Everything you need is on this page.** You don't need to
read the code, the git history or the issues, or probe the model server by
hand. `./dip --help` and `./dip <command> --help` show the same flags.

## 1. Create the match

    ./setup.sh <name> --press none --model <model> --base-url <url>

- **Name:** anything made of letters, digits, `-` and `_`. The match is a
  folder, `games/<name>/`, which is local and gitignored. There are no
  conventions to follow and no earlier games to copy. Pick a new name for
  each game, since an existing name is refused.
- **URL:** LM Studio is `http://127.0.0.1:1234/v1`, Ollama
  `http://127.0.0.1:11434/v1`. The model is its id on that server.
- **First run** builds the environment by itself, taking about a minute.
  Wait for it.
- `--model fake` (no `--base-url`) plays random legal orders with no server, as a dry run.
- `--press full` turns on negotiation. `--max-year 1910` sets when the game
  ends, and `--deadline 30m` the time limit per phase.

It prints one endpoint line, a `settings:` line with everything the match
was created with, then `next: .../dip run <name>`.

| Endpoint line | Meaning | Do |
|---|---|---|
| `endpoint OK: flint @ http://...` | model answered | run the `next:` command |
| `endpoint DOWN: nothing answering at ...` | no server on that URL | start the server or fix the URL, then `./dip check --model M --base-url U` |
| `endpoint UP ... no model 'x'. It serves: a, b` | wrong model id | use one of the listed ids |
| `endpoint ERROR ...: HTTP 400: Failed to load model ...` | server can't load it (often memory) | pick a smaller or already-loaded model |

The match is already saved even if the check fails. Once the endpoint is
fixed, `./dip run <name> --model M --base-url U` works.

## 2. Start it

    ./dip run <name>

This returns at once and prints the runner's pid, log path, and the status
and stop commands. The game plays in the background. If the same server is
also serving you, add `--concurrency 3` (the default is 4 calls at once per
server). For a local reasoning model, `--reasoning-effort low` is a good
default too: orders don't need thousands of tokens of thought.

## 3. Check on it

Every few minutes, not in a loop. A movement phase takes minutes on a local
model. This is the only thing you need to look at:

    ./dip status <name>

While it's playing:

    gunboat: F1903M, 2/7 submitted; waiting on AUSTRIA, ENGLAND, ...
      settings: gunboat: press none · ends after 1910 · phase deadline 30 minutes · seats flint @ http://127.0.0.1:1234/v1
      runner: running (pid 4242), log .../games/gunboat/run.log
      latest:   FRANCE (flint): 4 order(s) (52s)

**Finished** looks like this, and the runner exits by itself:

    gunboat: over — year cap 1910 (last phase played: W1910A)   (or: over — solo FRANCE)
      runner: not running. Last lines of .../run.log:
        Game over: year cap 1910. Centres: FRANCE 9, ...

Lines in `latest` (and in the log) that need no action, or one flag:

| Line | Meaning | Do |
|---|---|---|
| `FRANCE (flint): 0 order(s) — holding [retry: ...]` | unusable orders twice, so its units hold | nothing; the game goes on |
| `FRANCE: call failed (no tokens for 180s); retrying` | server busy or stalled | nothing, unless it repeats |
| `... no tokens for 180s — model too slow: try ...` | still failing after the retry, so the seat holds | restart with the flags below |

A slow model that is still writing is never cut off; a call only fails
after `--timeout` seconds (180 s) with *no* tokens at all, or after
`--call-limit` (an hour). If seats keep failing on a shared or slow server,
run `./dip stop <name>`, then
`./dip run <name> --reasoning-effort low --concurrency 2 --timeout 600`.

## When it stalls

- **The runner isn't running and the game isn't over.** It crashed or was
  stopped. Read the log lines status shows, then `./dip run <name>` to resume
  from the same phase; nothing is lost.
- **The phase hasn't changed in much longer than usual and the runner is
  running.** A local reasoning model can take several minutes per seat, and
  the game moves on by itself. If you can't wait, `./dip advance <name>` resolves the
  phase now, and missing orders hold.
- `./dip stop <name>` stops the runner; `./dip run <name>` resumes it.

Nothing here commits, pushes or needs keys. To watch a replay:
`./dip site --serve 8000`, then open http://localhost:8000.

## Optional

- `run --seat FRANCE=<model>@<url>` gives one seat a different model.
- `--agents ENGLAND` leaves a seat to an outside agent, which plays from
  `games/<name>/briefs/ENGLAND.md`. The game waits for it.
- `--rounds 2` sets talk rounds per phase in full press.
- `--max-tokens 8000` per call, and `--reasoning-effort low` for less
  thinking.
- `--phases N` stops after N phases. `--foreground` stays attached.
