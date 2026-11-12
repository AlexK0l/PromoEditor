#!/usr/bin/env bash
set -euo pipefail

# READ-ONLY diagnostics. Safe to run while RegionalResearch has active jobs.
echo '=== OS / architecture ==='
. /etc/os-release
echo "$PRETTY_NAME $(uname -m)"
echo '=== RAM / swap ==='
free -h
swapon --show || true
echo '=== Disk ==='
df -h /opt /var 2>/dev/null || df -h /
echo '=== Existing applications (read only) ==='
for unit in caddy regionalresearch promoeditor; do
  printf '%s: ' "$unit"
  systemctl is-active "$unit" 2>/dev/null || true
done
echo '=== Listening ports ==='
ss -ltnp | grep -E '(:80|:443|:10000|:18080)[[:space:]]' || true
echo '=== DNS (non-secret) ==='
if [[ -n "${PROMO_HOST:-}" ]]; then
  getent ahostsv4 "$PROMO_HOST" | head -n 3 || true
else
  echo 'Set PROMO_HOST to check the future PromoEditor DNS hostname (optional).'
fi
echo '=== Host Caddy config state ==='
if command -v caddy >/dev/null 2>&1; then
  caddy version
  if [[ -f /etc/caddy/Caddyfile ]]; then caddy validate --config /etc/caddy/Caddyfile; fi
fi
echo 'No changes have been made.'
