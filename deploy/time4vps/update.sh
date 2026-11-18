#!/usr/bin/env bash
set -euo pipefail

# Historical entrypoint retained only for compatibility. The previous script
# upgraded a moving origin/main in place with no rollback. Fail closed unless
# the operator provides the exact 40-char CI-reviewed main commit SHA.
if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Time4VPS: unsafe auto-update is disabled.' >&2
  echo 'Use docs/TIME4VPS_RELEASE_2026-11-18.md and a reviewed 40-character SHA.' >&2
  echo 'Example: bash deploy/time4vps/safe_release.sh <reviewed-main-SHA>' >&2
  exit 2
fi
exec bash "$(dirname "$0")/safe_release.sh" "$1"
