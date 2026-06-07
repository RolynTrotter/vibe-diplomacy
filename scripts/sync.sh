#!/usr/bin/env bash
# Commit your own files and push to the shared game branch, rebasing past other
# powers' commits and retrying on races. Keeps multi-session play frictionless.
#
# Usage:
#   scripts/sync.sh "FRANCE S1901M orders" orders/FRANCE notes/FRANCE.md
#   scripts/sync.sh "FRANCE claims seat" players/FRANCE.json
#
# Pass ONLY your own paths — never stage other powers' files, state/, history/,
# or game/. (secrets/ is gitignored and can never be committed.)
set -euo pipefail

msg=${1:?usage: sync.sh "commit message" <path> [path...]}
shift
[ "$#" -gt 0 ] || { echo "give at least one path to commit" >&2; exit 2; }

branch=$(git rev-parse --abbrev-ref HEAD)
git add -- "$@"
if git diff --cached --quiet; then
  echo "nothing staged to commit"; exit 0
fi
git commit -m "$msg"

for i in 1 2 3 4 5; do
  git pull --rebase origin "$branch" || true
  if git push origin "$branch"; then
    echo "pushed to $branch"; exit 0
  fi
  echo "push race; retry $i…" >&2
  sleep $((i * 2))
done
echo "push failed after retries — pull --rebase and try again" >&2
exit 1
