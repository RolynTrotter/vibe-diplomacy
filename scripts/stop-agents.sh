#!/usr/bin/env bash
# Stop spun-off Diplomacy match / agent processes that were launched detached
# and have no clean shutdown. Finds this project's orchestration entrypoints
# (run_match / conduct / run_adjudication) and terminates them, printing what it
# killed. Never matches a bare "claude" process (which could kill your own
# session); pass --pattern to match agents launched some other way.
#
# Usage:
#   scripts/stop-agents.sh                     # all vibe-diplomacy match procs
#   scripts/stop-agents.sh <game>              # only those whose cmdline mentions <game>
#   scripts/stop-agents.sh --dry-run           # show what would be killed, kill nothing
#   scripts/stop-agents.sh --force <game>      # SIGKILL instead of SIGTERM
#   scripts/stop-agents.sh --pattern '<regex>' # custom match
set -euo pipefail

sig=TERM
dry=0
name=""
pattern='orchestration\.(run_match|conduct|run_adjudication)'
custom_pattern=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run|-n) dry=1 ;;
    --force|-9)   sig=KILL ;;
    --pattern)    shift; pattern=${1:?--pattern needs a regex}; custom_pattern=1 ;;
    -h|--help)    grep '^#' "$0" | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
    -*)           echo "unknown flag: $1" >&2; exit 2 ;;
    *)            name="$1" ;;
  esac
  shift
done

self=$$
matches=""
for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
  [ "$pid" = "$self" ] && continue
  cmd=$(ps -o command= -p "$pid" 2>/dev/null || true)
  [ -z "$cmd" ] && continue
  # Safety: unless the caller supplied their own pattern, never touch a process
  # that isn't clearly one of our orchestration entrypoints.
  if [ "$custom_pattern" -eq 0 ]; then
    case "$cmd" in *orchestration.run_match*|*orchestration.conduct*|*orchestration.run_adjudication*) ;; *) continue ;; esac
  fi
  # If a game name was given, the command line must mention it.
  if [ -n "$name" ]; then
    case "$cmd" in *"$name"*) ;; *) continue ;; esac
  fi
  matches="$matches $pid"
done

if [ -z "${matches# }" ]; then
  echo "No matching match/agent processes found${name:+ for '$name'}."
  exit 0
fi

echo "Matching processes:"
for pid in $matches; do
  ps -o pid=,command= -p "$pid" 2>/dev/null || true
done

if [ "$dry" -eq 1 ]; then
  echo "(dry run — nothing killed)"
  exit 0
fi

for pid in $matches; do
  if kill -"$sig" "$pid" 2>/dev/null; then
    echo "sent SIG$sig to $pid"
  else
    echo "could not signal $pid (already gone?)" >&2
  fi
done
