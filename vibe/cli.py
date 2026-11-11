"""`./dip` — every command, for players and for whoever hosts the match.

Players use only what their brief lists: `board`, `submit`, `wait` (and
`send`, `inbox` with full press), each with `--seat <token>`. Everything else
is for the host.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from vibe import board as boardmod
from vibe import mapviz
from vibe.game import POWERS, ROOT, LateOrders, Match, MatchError

DIP = ROOT / "dip"

HOST_HELP = """\
Host a match between models (no need to read any code):
  ./setup.sh <name> --press none --model <model> --base-url http://127.0.0.1:1234/v1
        creates games/<name>/ (local; any new name), checks the model answers
  ./dip run <name>       starts it in the background and returns at once
  ./dip status <name>    phase, who it waits on, runner alive?, latest line;
                         says 'over — ...' when the game has ended
  ./dip run <name>       again after a crash resumes from the same phase
  ./dip advance <name>   resolve a stalled phase now (missing orders hold)
Full guide: .claude/skills/run-a-match/SKILL.md and README.md.

Playing a seat? Your brief lists the only commands you need.
"""


def _duration(text: str) -> int:
    """'90s', '10m', '2h', '600' -> seconds."""
    m = re.fullmatch(r"(\d+)([smh]?)", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"bad duration {text!r} (try 10m)")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def _human(seconds: int) -> str:
    if not seconds:
        return "no time limit"
    return f"{seconds // 60} minutes" if seconds % 60 == 0 else f"{seconds} seconds"


def settings_line(match: Match) -> str:
    """Everything the match was created with, on one line."""
    cfg = match.config
    run = cfg.get("run") or {}
    seats = (f"seats {run['model']}" + (f" @ {run['base_url']}" if run.get("base_url") else "")
             if run.get("model") else "seats: none set (pass --model to `run`)")
    return (f"{cfg['name']}: press {cfg.get('press', 'none')} · ends after "
            f"{cfg['max_year']} · phase deadline {_human(cfg['deadline_s'])} · {seats}")


def brief(match: Match, power: str) -> str:
    """The one page a seat is handed. Everything it needs, nothing it doesn't."""
    cfg = match.config
    seat = f"{DIP} {{}} --seat {cfg['seats'][power]}"
    cmds = [
        (seat.format("board"), "the board, your units, and every move you can make"),
        (seat.format("submit") + ' "A PAR - BUR" "F BRE - MAO" ...',
         "your orders for this phase; checked, with errors explained. "
         "Submitting again replaces them. No orders = everything holds."),
        (seat.format("wait"), "after submitting: blocks until the phase "
                              "resolves, then shows the new board"),
    ]
    if match.full_press:
        cmds += [
            (seat.format("send") + ' --to ENGLAND,GERMANY "your message"',
             "a private message (or --to ALL)"),
            (seat.format("inbox"), "messages to you and to everyone"),
        ]
    press = ("Full press: you may negotiate privately with the other powers. "
             "Messages are private and not binding."
             if match.full_press else "Gunboat: no messaging; orders only.")
    lines = [
        f"# You are {power} in a game of Diplomacy",
        "",
        f"Seven players, one per great power; you play **{power}**. Each phase "
        "every power writes orders in secret and they resolve together. "
        f"{press}",
        "",
        "## Your commands",
        "",
    ]
    for cmd, what in cmds:
        lines += [f"    {cmd}", f"        {what}", ""]
    lines += [
        "## The loop",
        "",
        ("`board` → negotiate (`inbox`, `send`) → `submit` → `wait` → repeat"
         if match.full_press else "`board` → `submit` → `wait` → repeat"),
        f"until `board` or `wait` says GAME OVER (the game ends after "
        f"{cfg['max_year']} or when someone reaches 18 centres).",
        "",
        f"A phase resolves once every power has submitted, or after "
        f"{_human(cfg['deadline_s'])}; anything not submitted holds. Retreat "
        "and winter-build phases work the same way — `board` shows your options.",
        "",
        "These commands are all you need. Nothing else on this computer is part "
        "of the game; there is no need to read any files or source code.",
    ]
    return "\n".join(lines)


def write_briefs(match: Match) -> list:
    out = []
    (match.path / "briefs").mkdir(exist_ok=True)
    for power in POWERS:
        f = match.path / "briefs" / f"{power}.md"
        f.write_text(brief(match, power) + "\n")
        out.append(f)
    return out


# --------------------------------------------------------------------------- #
# Player commands
# --------------------------------------------------------------------------- #
def _seat(args) -> tuple[Match, str]:
    return Match.by_token(args.seat)


def _picture(match: Match) -> str | None:
    game = match.load()
    if game.phase_type != "M" or match.ended():
        return None
    path = mapviz.phase_image(match.path, game)
    return str(path) if path else None


def _show(match: Match, power: str) -> None:
    """The board, and once the game is over, how to leave lore for the next player."""
    print(boardmod.render(match, power, picture=_picture(match)))
    if match.ended() and power not in match.config.get("lore_from", []):
        token = match.config["seats"][power]
        print(f"\nLeave notes for whoever plays {power} next game (openings, alliances, "
              f"what worked, what you'd change; one go, under 200 words):\n"
              f'    {DIP} lore --seat {token} "your notes"')


def cmd_board(args) -> int:
    match, power = _seat(args)
    match.advance()  # a passed deadline resolves on whoever looks first
    _show(match, power)
    match.seen(power, match.phase())
    if match.full_press and not match.ended():
        n = len([m for m in match.inbox(power) if m["sender"] != power])
        print(f"\nYou have {n} message(s); read them with `inbox`.")
    return 0


def _read_orders(items: list[str]) -> list[str]:
    if not items and not sys.stdin.isatty():
        items = [sys.stdin.read()]
    return [o.strip() for item in items for o in re.split(r"[\n;,]", item) if o.strip()]


def cmd_submit(args) -> int:
    match, power = _seat(args)
    game = match.load()
    phase = game.get_current_phase()
    if power not in match.owing(game):
        print(f"{power} has nothing to order in {phase}. Run `wait`.")
        return 0
    orders = _read_orders(args.orders)
    # Orders are for the phase this seat last looked at; if that has since
    # resolved, they were written against a board that no longer exists.
    written_for = match.seen(power) or phase
    match.seen(power, phase)
    try:
        checked = match.submit(power, orders, phase=written_for)
    except LateOrders as exc:
        print(f"Not submitted: {exc}. Run `board` to see {phase}, then submit again.")
        return 1
    if not checked.ok:
        print("Not submitted — fix these and submit the whole set again:")
        for e in checked.errors:
            print(f"  - {e}")
        return 1
    shown = "\n".join(f"  {o}" for o in checked.accepted) or "  (none — everything holds)"
    print(f"Submitted for {phase}:\n{shown}")
    if match.phase() != phase or match.ended():
        print(f"\nEveryone was in, so {phase} has resolved. Run `wait` or `board`.")
    else:
        print("\nYou can submit again to replace these until the phase resolves. "
              "Now run `wait`.")
    return 0


def cmd_wait(args) -> int:
    match, power = _seat(args)
    game = match.load()
    start = game.get_current_phase()
    last = match.seen(power)
    if last and last != start:
        # It resolved before we got here (often on this seat's own submit).
        print(f"{last} has resolved.\n")
        _show(match, power)
        match.seen(power, start)
        return 0
    if not match.ended() and power in match.owing(game) and power not in match.submitted(game):
        print(f"You have not submitted orders for {start} yet; the phase is waiting "
              "on you. Run `submit` first (with no orders, everything holds).")
        return 1
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        match.advance()
        if match.ended() or match.phase() != start:
            print(f"{start} has resolved.\n")
            _show(match, power)
            match.seen(power, match.phase())
            return 0
        time.sleep(args.poll)
    game = match.load()
    print(f"Still waiting on {start}: {len(match.submitted(game))}/"
          f"{len(match.owing(game))} powers have submitted. Run `wait` again.")
    return 0


def cmd_send(args) -> int:
    match, power = _seat(args)
    to = [t for t in re.split(r"[,\s]+", args.to) if t]
    sent = match.send(power, to, " ".join(args.message))
    print(f"Sent to {', '.join(sent)}." if sent else "Nothing sent (empty message?).")
    return 0


def cmd_lore(args) -> int:
    match, power = _seat(args)
    if not match.ended():
        print("The game is not over yet.")
        return 1
    if not match.add_lore(power, " ".join(args.text)):
        print("Not saved: you have already left your notes for this game (or wrote nothing).")
        return 1
    print(f"Saved. The next player of {power} will see it at the start of their game.")
    return 0


def cmd_inbox(args) -> int:
    match, power = _seat(args)
    print(boardmod._inbox(match, power, limit=args.last))
    return 0


# --------------------------------------------------------------------------- #
# Host commands
# --------------------------------------------------------------------------- #
def cmd_new(args) -> int:
    match = Match.create(args.name, press=args.press, max_year=args.max_year,
                         deadline_s=args.deadline)
    briefs = write_briefs(match)
    print(f"Created match {args.name!r} ({'full press' if match.full_press else 'gunboat'},"
          f" ends after {args.max_year}, phase limit {_human(args.deadline)}).")
    print(f"It lives in {match.path} (local only; any name works, nothing to copy).\n")
    print("Agents play it from these briefs, one each:")
    for f in briefs:
        print(f"  {f}")
    if args.model and (args.base_url or args.model in ("fake", "agent")
                       or args.model.startswith("claude:")):
        from vibe import run
        url = (args.base_url or "").rstrip("/")
        match._set_config(run={"model": args.model, "base_url": url})
        seat = run.parse_seat(args.model, url, "")
        if seat.kind == "openai":
            ok, line = run.check_endpoint(seat)
            print(f"\n{line}")
            if not ok:
                print("Fix the endpoint first (`./dip check` retries it), then:")
        print(f"\nsettings: {settings_line(match)}")
        print(f"next: {DIP} run {args.name}")
    elif args.model:
        print(f"\n--model {args.model} needs --base-url too (e.g. http://127.0.0.1:1234/v1); "
              f"or pass both to run:\nnext: {DIP} run {args.name} --model {args.model} "
              "--base-url <url>")
    else:
        print(f"\nOr models play every seat:\nnext: {DIP} run {args.name} "
              "--model <name> --base-url <OpenAI-compatible URL, e.g. http://127.0.0.1:1234/v1>")
    return 0


def cmd_brief(args) -> int:
    print(brief(Match.open(args.name), args.power.upper()))
    return 0


def cmd_status(args) -> int:
    matches = [Match.open(args.name)] if args.name else Match.all()
    if not matches:
        print("No matches yet. Create one with `./dip new <name>`.")
    from vibe.run import runner_pid
    for m in matches:
        m.advance()
        game = m.load()
        if m.ended():
            played = [str(k) for k in game.order_history.keys()]
            print(f"{m.name}: over — {m.ended()}"
                  + (f" (last phase played: {played[-1]})" if played else ""))
        else:
            sub, owing = m.submitted(game), m.owing(game)
            waiting = [p for p in owing if p not in sub]
            print(f"{m.name}: {game.get_current_phase()}, {len(sub)}/{len(owing)} submitted"
                  + (f"; waiting on {', '.join(waiting)}" if waiting else ""))
        print(f"  settings: {settings_line(m)}")
        played = [str(k) for k in game.order_history.keys()]
        last = m.history(played[-1]) if played else None
        if last and last.get("missing"):
            print(f"  {last['phase']} resolved ({last.get('resolved', 'deadline')}) with "
                  f"{len(last['missing'])} seat(s) missing, who held: {', '.join(last['missing'])}")
        log = m.path / "run.log"
        if pid := runner_pid(m):
            print(f"  runner: running (pid {pid}), log {log}")
        elif log.exists():
            print(f"  runner: not running. Last lines of {log}:")
            for line in log.read_text().splitlines()[-3:]:
                print(f"    {line}")
        progress = m.path / "progress.log"
        if progress.exists() and pid:
            tail = progress.read_text().splitlines()[-1:]
            print(f"  latest: {tail[0].strip() if tail else ''}")
    return 0


def cmd_stop(args) -> int:
    import os
    import signal

    from vibe.run import runner_pid
    match = Match.open(args.name)
    pid = runner_pid(match)
    if not pid:
        print(f"No runner is running for {match.name}.")
        return 0
    os.killpg(pid, signal.SIGTERM)
    print(f"Stopped the runner (pid {pid}). The match keeps its state; "
          f"`./dip run {match.name}` resumes it.")
    return 0


def cmd_advance(args) -> int:
    match = Match.open(args.name)
    summary = match.advance(force=True)
    if summary is None:
        print("Nothing to resolve (game over?).")
        return 1
    print(f"Resolved {summary['phase']}; now {match.phase()}."
          + (f" Held for: {', '.join(summary['missing'])}." if summary["missing"] else ""))
    return 0


def cmd_check(args) -> int:
    from vibe import run
    ok, line = run.check_endpoint(run.parse_seat(args.model, args.base_url, ""))
    print(line)
    return 0 if ok else 1


def cmd_run(args) -> int:
    from vibe import run
    return run.main(args)


def cmd_site(args) -> int:
    from vibe import site
    return site.main(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dip", description="Vibe Diplomacy: run models against each other at Diplomacy.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=HOST_HELP)
    sub = p.add_subparsers(dest="cmd", required=True)

    def seat_cmd(name, fn, help):
        s = sub.add_parser(name, help=help)
        s.add_argument("--seat", required=True, help="your seat token (from your brief)")
        s.set_defaults(fn=fn)
        return s

    seat_cmd("board", cmd_board, "[player] the board for your power")
    s = seat_cmd("submit", cmd_submit, "[player] submit this phase's orders")
    s.add_argument("orders", nargs="*", help='e.g. "A PAR - BUR" "F BRE H"')
    s = seat_cmd("wait", cmd_wait, "[player] block until the phase resolves")
    s.add_argument("--timeout", type=_duration, default="30m")
    s.add_argument("--poll", type=float, default=2.0, help=argparse.SUPPRESS)
    s = seat_cmd("send", cmd_send, "[player] send a message (full press)")
    s.add_argument("--to", required=True, help="POWER[,POWER...] or ALL")
    s.add_argument("message", nargs="+")
    s = seat_cmd("inbox", cmd_inbox, "[player] read your messages (full press)")
    s.add_argument("--last", type=int, default=60)
    s = seat_cmd("lore", cmd_lore, "[player] after the game: notes for the next player")
    s.add_argument("text", nargs="+")

    s = sub.add_parser("new", help="[host] create a match and its seat briefs")
    s.add_argument("name")
    s.add_argument("--press", choices=["none", "full"], default="none")
    s.add_argument("--max-year", type=int, default=1910)
    s.add_argument("--deadline", type=_duration, default="30m",
                   help="per-phase time limit, e.g. 10m (0 = none)")
    s.add_argument("--model", help="model for `./dip run` to use (checked now)")
    s.add_argument("--base-url", help="its OpenAI-compatible URL, e.g. http://127.0.0.1:1234/v1")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("brief", help="[host] print a seat's brief")
    s.add_argument("name")
    s.add_argument("power")
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("status", help="[host] where each match stands")
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("stop", help="[host] stop a background `run`")
    s.add_argument("name")
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("check", help="[host] does the model endpoint answer?")
    s.add_argument("--model", required=True)
    s.add_argument("--base-url", required=True)
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("advance", help="[host] resolve the phase now; missing orders hold")
    s.add_argument("name")
    s.set_defaults(fn=cmd_advance)

    from vibe import run
    run.add_arguments(sub.add_parser("run", help="[host] play seats with models"))
    sub.choices["run"].set_defaults(fn=cmd_run)

    s = sub.add_parser("site", help="[host] build the replay viewer for every match")
    s.add_argument("--out", default="_site")
    s.add_argument("--serve", type=int, metavar="PORT", help="then serve it on PORT")
    s.set_defaults(fn=cmd_site)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except MatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
