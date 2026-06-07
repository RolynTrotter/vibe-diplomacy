#!/usr/bin/env bash
# Create a local virtualenv and install the engine. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "Ready. Run: source .venv/bin/activate"
