---
name: run-a-match
description: Run a whole Diplomacy match between models from start to finish with one command, and check on it. Use when asked to run, host or conduct a vibe-diplomacy game or to pit models against each other. Not for playing a single seat (a seat's brief covers that).
---

# Run a match

You are the host. You don't play, and you don't need to read any source.

1. Create the match. The first run also builds the environment; let it finish.

       ./setup.sh <name> --press none        # or --press full for negotiation

2. Start every seat on a model, in the background, and leave it running:

       nohup ./dip run <name> --model <model> --base-url http://127.0.0.1:1234/v1 > /dev/null 2>&1 &

   Use the base URL of any OpenAI-compatible server (LM Studio, Ollama, vLLM).
   To mix in other players, add `--seat FRANCE=<model>@<url>`, or use
   `--agents ENGLAND` for a seat that an outside agent plays from
   `games/<name>/briefs/ENGLAND.md`.

3. Check on it now and then, not in a tight loop. Each phase of a local model
   takes minutes.

       ./dip status <name>

   This prints the phase, who it is waiting on, and the latest progress line.
   The full progress log is `games/<name>/progress.log`. The run ends by
   itself when the game does (year cap, 1910 by default, or an 18-centre win).

If a phase is stuck on a seat that will never answer: `./dip advance <name>`
(missing orders hold). For the replay viewer: `./dip site --serve 8000`.
Useful `run` flags: `--concurrency 4` (calls at once per server),
`--max-tokens 8000`, `--reasoning-effort low`, `--rounds 2` (talk rounds per
phase in full press). Nothing here pushes, commits or needs keys.
