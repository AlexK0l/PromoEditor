#!/usr/bin/env bash
set -euo pipefail

# ADDITIVE configuration: a separate Caddy site block, preserving RegionalResearch.
if [[ "${EUID}" -ne 0 ]]; then
  echo 'Run as root: sudo bash deploy/time4vps/configure_caddy.sh' >&2; exit 1
fi
if ! command -v caddy >/dev/null 2>&1; then echo 'Caddy is not installed.' >&2; exit 1; fi
if [[ ! -f /etc/caddy/Caddyfile ]]; then echo 'Existing /etc/caddy/Caddyfile is missing.' >&2; exit 1; fi
# Only create a public site after FastAPI password protection has been verified.
code=$(curl --silent --output /dev/null --max-time 8 --write-out '%{http_code}' http://127.0.0.1:18080/api/config)
if [[ "$code" != "401" ]] || ! curl --fail --silent --show-error --max-time 8 http://127.0.0.1:18080/login >/dev/null; then
  echo 'Password-only app login is not ready. No Caddy changes made.' >&2; exit 1
fi
# These are entered on the VPS, never hardcoded into the PUBLIC GitHub repository.
read -r -p 'PromoEditor HTTPS hostname (e.g. promoeditor.1-2-3-4.sslip.io): ' HOST
read -r -p 'Expected public VPS IPv4 (e.g. 1.2.3.4): ' EXPECTED_IPV4
if [[ ! "$HOST" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ || "$HOST" == *..* ]]; then
  echo 'Invalid hostname characters.' >&2; exit 1
fi
if [[ ! "$EXPECTED_IPV4" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo 'Invalid IPv4 format.' >&2; exit 1
fi
if ! getent ahostsv4 "$HOST" | awk '{print $1}' | grep -Fxq "$EXPECTED_IPV4"; then
  echo "DNS for $HOST does not resolve to the expected VPS address." >&2; exit 1
fi
if grep -Fq "$HOST {" /etc/caddy/Caddyfile; then
  echo 'This hostname already exists in the main Caddyfile; configure manually.' >&2; exit 1
fi
if [[ -f /etc/caddy/promoeditor.caddy ]]; then
  echo '/etc/caddy/promoeditor.caddy already exists; refusing to overwrite.' >&2; exit 1
fi

install -d -o root -g root -m 0700 /root/promoeditor-backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/root/promoeditor-backups/Caddyfile-before-promoeditor-${stamp}"
cp -p /etc/caddy/Caddyfile "$backup"

# FastAPI password auth is already active; Caddy publishes only a protected upstream.
{
  printf '%s {\n' "$HOST"
  cat <<'CADDYHEAD'
    encode zstd gzip
    request_body {
        max_size 72MB
    }
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        X-Frame-Options DENY
    }
    reverse_proxy 127.0.0.1:18080
}
CADDYHEAD
} > /etc/caddy/promoeditor.caddy
chown root:caddy /etc/caddy/promoeditor.caddy
chmod 0640 /etc/caddy/promoeditor.caddy

if ! grep -Fqx 'import /etc/caddy/promoeditor.caddy' /etc/caddy/Caddyfile; then
  printf '\n# Additive site; existing RegionalResearch block above remains unchanged.\nimport /etc/caddy/promoeditor.caddy\n' >> /etc/caddy/Caddyfile
fi
if ! caddy validate --config /etc/caddy/Caddyfile; then
  cp -p "$backup" /etc/caddy/Caddyfile
  rm -f /etc/caddy/promoeditor.caddy
  echo 'Invalid Caddy config; original configuration restored; no reload.' >&2; exit 1
fi
if ! systemctl reload caddy; then
  cp -p "$backup" /etc/caddy/Caddyfile
  rm -f /etc/caddy/promoeditor.caddy
  caddy validate --config /etc/caddy/Caddyfile || true
  systemctl reload caddy || true
  echo 'Caddy reload failed; attempted rollback to original file.' >&2; exit 1
fi

echo "HTTPS site configured: https://${HOST}/"
echo 'Login: one password via the PromoEditor web page. No username needed.'
echo 'Existing RegionalResearch configuration was not replaced.'
echo 'Anonymous website should redirect to /login (HTTP 303):'
curl -sSI --max-time 15 "https://${HOST}/" | head -n 8 || true
