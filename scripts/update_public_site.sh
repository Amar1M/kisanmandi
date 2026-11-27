#!/usr/bin/env bash
# Run the bounded local ingest, regenerate the public snapshot, and push it.
# Intended for a Windows Task Scheduler job invoking WSL while the laptop is online.
set -Eeuo pipefail

PROJECT_DIR="/home/amarnavya/projects/kisanmandi"
cd "$PROJECT_DIR"

# Avoid overlapping runs and refuse to commit unrelated local work.
exec 9>/tmp/kisanmandi-public-refresh.lock
if ! flock -n 9; then
  echo "Another KisanMandi refresh is already running; exiting."
  exit 0
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Refusing to refresh from a branch other than main."
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean; commit/stash local changes before refreshing."
  exit 1
fi

git pull --ff-only origin main
source .venv/bin/activate

# run_public_ingest.py refuses to contact the API if the personal key is missing.
# The key is read from the ignored local .env; it is never printed or committed.
python scripts/run_public_ingest.py
python scripts/export_static_site.py --output-dir public

git add -- public/index.html public/prices.json
if git diff --cached --quiet; then
  echo "The public snapshot did not change; nothing to publish."
  exit 0
fi

git commit -m "Refresh Karnataka price snapshot $(date -u +%F)"
git push origin main
