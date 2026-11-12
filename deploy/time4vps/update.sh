#!/usr/bin/env bash
set -euo pipefail

# Updates ONLY PromoEditor. Does not touch existing Caddy or RegionalResearch.
if [[ "${EUID}" -ne 0 ]]; then echo 'Use sudo to run this script.' >&2; exit 1; fi
[[ -d /opt/promoeditor/.git ]] || { echo 'PromoEditor is not installed.' >&2; exit 1; }
cd /opt/promoeditor
if [[ -n "$(runuser -u promoeditor -- git status --porcelain)" ]]; then
  echo 'Uncommitted changes in /opt/promoeditor; stopping (no reset/stash).' >&2; exit 1
fi
previous=$(runuser -u promoeditor -- git rev-parse HEAD)
runuser -u promoeditor -- git fetch origin main
runuser -u promoeditor -- git merge --ff-only origin/main
runuser -u promoeditor -- /opt/promoeditor/.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
systemctl restart promoeditor
systemctl is-active --quiet promoeditor
curl -fsS --max-time 10 http://127.0.0.1:18080/api/config >/dev/null
printf 'PromoEditor updated. Previous HEAD: %s\n' "$previous"
echo 'RegionalResearch and Caddy were not restarted.'
