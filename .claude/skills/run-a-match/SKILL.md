---
name: run-a-match
description: Run a whole Diplomacy match between models from start to finish, and check on it. Use when asked to run, host or conduct a vibe-diplomacy game or to pit models against each other. Not for playing a single seat (a seat's brief covers that).
---

# Run a match

You are the host. Everything you need is on this page: you don't need to read
the code, the git history or the issues, or probe the model server by hand.

**1. Create the match.** Pick any name. Matches are local state in `games/`
(gitignored), and there are no conventions or past games to copy. The first
run builds the environment itself, which takes about a minute.

    ./setup.sh <name> --press none --model <model> --base-url <url>

For LM Studio the URL is `http://127.0.0.1:1234/v1`. This checks the model
right away and prints one line, either `endpoint OK: ...` or the server's own
error. It ends with the exact next command.

**2. Start it.** This returns at once. The game plays in the background and
stops by itself at the end (after 1910, or at an 18-centre win).

    ./dip run <name>

Add `--concurrency 3` if the same server is also serving you.

**3. Check on it** every few minutes, not in a loop. A phase takes minutes
on a local model. This is the only thing you need to look at:

    ./dip status <name>

It shows the phase, who the game is waiting on, whether the runner is alive,
its latest line, and the log path. If the runner died, it shows the log's last
lines.

That's all. To stop: `./dip stop <name>` (`./dip run <name>` resumes). If a
seat is stuck: `./dip advance <name>` (missing orders hold). To watch the
replay: `./dip site --serve 8000`. Nothing here commits, pushes or needs keys.

Optional `run` flags: `--press full` at step 1 for negotiation, with
`--rounds 2` talk rounds per phase. `--max-tokens 8000` per call, and
`--reasoning-effort low`. `--seat FRANCE=<model>@<url>` gives a seat a
different model. `--agents ENGLAND` leaves a seat to an outside agent, which
plays from `games/<name>/briefs/ENGLAND.md`.
