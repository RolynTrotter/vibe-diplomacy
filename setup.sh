#!/usr/bin/env bash
# Build the environment, and optionally create a match:
#   ./setup.sh                          just the environment
#   ./setup.sh test --press none        environment + a match called "test"
# Safe to run any number of times, including from several shells at once.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="$here/.venv"

build() {
  rm -rf "$venv"
  if command -v uv >/dev/null 2>&1; then
    # uv fetches the pinned interpreter itself if it isn't installed.
    uv venv --quiet --python 3.11 "$venv"
    uv pip install --quiet --python "$venv/bin/python" -r "$here/requirements.txt"
  elif command -v python3.11 >/dev/null 2>&1; then
    python3.11 -m venv "$venv"
    "$venv/bin/pip" install --quiet -r "$here/requirements.txt"
  else
    echo "setup: needs uv (https://docs.astral.sh/uv/ — one line:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo ") so it can fetch the right Python by itself." >&2
    exit 1
  fi
  touch "$venv/.ready"
}

if [ ! -f "$venv/.ready" ] || [ "$here/requirements.txt" -nt "$venv/.ready" ]; then
  # One builder at a time; anyone else waits for it to finish.
  lock="$here/.setup.lock"
  until mkdir "$lock" 2>/dev/null; do sleep 1; done
  trap 'rmdir "$lock"' EXIT
  if [ ! -f "$venv/.ready" ] || [ "$here/requirements.txt" -nt "$venv/.ready" ]; then
    echo "setup: building the environment (first run only)..." >&2
    build
    echo "setup: ready." >&2
  fi
fi

if [ "${1:-}" = "--name" ]; then shift; fi
if [ $# -gt 0 ]; then exec "$here/dip" new "$@"; fi
[ -n "${VD_FROM_DIP:-}" ] && exit 0
echo "Environment ready. To create a match:"
echo "  next: $here/setup.sh <name> --press none --model <model> --base-url http://127.0.0.1:1234/v1"
echo "Hosting guide: $here/.claude/skills/run-a-match/SKILL.md"
