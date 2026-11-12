#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo 'ERROR: Tracked local changes present; commit or back them up before updating.' >&2
  exit 1
fi
git fetch origin main
git pull --ff-only origin main
docker compose -f compose.vps.yaml up -d --build --remove-orphans
docker compose -f compose.vps.yaml ps
