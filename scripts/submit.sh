#!/usr/bin/env bash
# Validate, seal, commit, and push a power's orders for the current phase.
# Pipe your orders to stdin:
#   echo "A PAR - BUR
#   F BRE - MAO" | scripts/submit.sh FRANCE
#
# On any validation error the script exits non-zero before writing anything.
set -euo pipefail

POWER=${1:?usage: echo "orders..." | scripts/submit.sh POWER}
POWER=$(echo "$POWER" | tr '[:lower:]' '[:upper:]')

source .venv/bin/activate 2>/dev/null \
  || { ./scripts/setup.sh && source .venv/bin/activate; }

PHASE=$(python -c "from engine import state; print(state.load_game('.').get_current_phase())")

python -m orchestration.submit_orders --power "$POWER"

scripts/sync.sh "$POWER $PHASE orders" "orders/$POWER/$PHASE.enc"
