#!/usr/bin/env bash
# Pull the latest game state and print a comprehensive brief for your power.
# Run this at the start of every turn — it replaces setup, git pull, game_status,
# and cat notes as separate steps.
#
# Usage: scripts/turn.sh FRANCE
set -euo pipefail

POWER=${1:?usage: scripts/turn.sh POWER}
POWER=$(echo "$POWER" | tr '[:lower:]' '[:upper:]')

source .venv/bin/activate 2>/dev/null \
  || { ./scripts/setup.sh && source .venv/bin/activate; }

git pull --rebase origin "$(git rev-parse --abbrev-ref HEAD)" 2>/dev/null || true

python -m orchestration.conduct brief --power "$POWER"
