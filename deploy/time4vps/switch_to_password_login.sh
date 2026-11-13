#!/usr/bin/env bash
set -euo pipefail
# Existing Time4VPS: enable app auth BEFORE removing Caddy Basic Auth.
# Only PromoEditor config is changed, not RegionalResearch.
[[ "$EUID" -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
SITE=/etc/caddy/promoeditor.caddy
ENV_FILE=/etc/promoeditor/promoeditor.env
[[ -f "$SITE" && -f "$ENV_FILE" ]] || { echo 'PromoEditor Caddy site or environment file is missing.' >&2; exit 1; }
command -v caddy >/dev/null || { echo 'Caddy not installed.' >&2; exit 1; }
systemctl is-active --quiet caddy || { echo 'Caddy is not active.' >&2; exit 1; }
systemctl is-active --quiet promoeditor || { echo 'PromoEditor is not active.' >&2; exit 1; }
[[ "$(stat -c '%a' "$ENV_FILE")" == "600" ]] || { echo 'Set env permissions to 0600 first.' >&2; exit 1; }
grep -Fq 'reverse_proxy 127.0.0.1:18080' "$SITE" || { echo 'Unexpected Caddy site; manual review required.' >&2; exit 1; }
grep -Fq 'import /etc/caddy/promoeditor.caddy' /etc/caddy/Caddyfile || { echo 'Missing existing PromoEditor site import.' >&2; exit 1; }
local_status() {
  curl --silent --output /dev/null --max-time 10 --write-out '%{http_code}' "http://127.0.0.1:18080$1" || true
}
if ! grep -Eq '^[[:space:]]*basic_auth[[:space:]]*\{' "$SITE"; then
  [[ "$(local_status '/api/config')" == "401" ]] || { echo 'Auth is not active! No Caddy changes made.' >&2; exit 1; }
  echo 'Already migrated: login by password only.'
  exit 0
fi
install -d -o root -g root -m 0700 /root/promoeditor-backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_site="/root/promoeditor-backups/promoeditor.caddy-before-login-$stamp"
backup_env="/root/promoeditor-backups/promoeditor.env-before-login-$stamp"
cp -p "$SITE" "$backup_site"
cp -p "$ENV_FILE" "$backup_env"
chmod 0600 "$backup_env"
echo 'Caddy Basic Auth stays enabled until the FastAPI password screen is verified.'
python3 /opt/promoeditor/deploy/time4vps/provision_auth.py "$ENV_FILE"
systemctl restart promoeditor
for attempt in $(seq 1 20); do
  if [[ "$(local_status '/login')" == "200" && "$(local_status '/api/config')" == "401" ]]; then break; fi
  sleep 1
done
if [[ "$(local_status '/login')" != "200" || "$(local_status '/api/config')" != "401" ]]; then
  echo 'FastAPI auth is not healthy. Caddy Basic Auth remains ENABLED. Check journalctl -u promoeditor.' >&2
  exit 1
fi
# Remove only a verified single basic_auth block in this imported PromoEditor site.
python3 - "$SITE" <<'PY'
import os,pathlib,re,sys,tempfile
site=pathlib.Path(sys.argv[1])
source=site.read_text(encoding="utf-8")
pattern=r"(?m)^[ \t]*basic_auth[ \t]*\{\r?\n(?:[^\n]*\n)*?^[ \t]*\}[ \t]*\r?\n"
matches=list(re.finditer(pattern,source))
if len(matches)!=1:
    raise SystemExit("Unexpected Basic Auth syntax: leaving Caddy unchanged.")
updated=re.sub(pattern,"",source,count=1)
if "basic_auth" in updated:
    raise SystemExit("Other authentication blocks present; manual review required.")
fd,tmp=tempfile.mkstemp(prefix=".promoeditor.caddy.",dir=str(site.parent))
try:
    os.fchmod(fd,0o640)
    os.fchown(fd,0,site.stat().st_gid)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        out.write(updated)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp,site)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
PY
if ! caddy validate --config /etc/caddy/Caddyfile || ! systemctl reload caddy; then
  cp -p "$backup_site" "$SITE"
  caddy validate --config /etc/caddy/Caddyfile || true
  systemctl reload caddy || true
  echo 'Caddy validate/reload failed. Previous Basic Auth restored; application auth remains active.' >&2
  exit 1
fi
echo 'Single password form is now active. The login "promo" is no longer required.'
echo 'RegionalResearch and its configurations were not modified.'
echo 'If the old browser prompt persists, use a private/incognito tab.'
