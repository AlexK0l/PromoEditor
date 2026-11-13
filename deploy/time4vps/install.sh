#!/usr/bin/env bash
set -euo pipefail

# Installs ONLY PromoEditor. Does not alter RegionalResearch, Caddy, firewall or port 80/443.
if [[ "${EUID}" -ne 0 ]]; then
  echo 'Run as root: sudo bash deploy/time4vps/install.sh' >&2; exit 1
fi

if [[ -e /opt/promoeditor/.git ]]; then
  echo 'Existing /opt/promoeditor checkout found. Use deploy/time4vps/update.sh.' >&2; exit 1
fi
if [[ -e /opt/promoeditor && -n "$(ls -A /opt/promoeditor 2>/dev/null)" ]]; then
  echo '/opt/promoeditor is nonempty; manual inspection is required, refusing to overwrite.' >&2; exit 1
fi
if ss -ltn | grep -Eq '^LISTEN[[:space:]].*127\.0\.0\.1:18080[[:space:]]'; then
  echo '127.0.0.1:18080 is occupied; choose a different port after inspecting services.' >&2; exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git python3 python3-venv python3-pip fonts-dejavu-core libcairo2 ca-certificates curl
if ! getent passwd promoeditor >/dev/null; then
  useradd --system --create-home --home-dir /var/lib/promoeditor --shell /usr/sbin/nologin promoeditor
fi
install -d -o promoeditor -g promoeditor -m 0755 /opt/promoeditor
install -d -o promoeditor -g promoeditor -m 0700 /var/lib/promoeditor/jobs
install -d -o root -g root -m 0700 /etc/promoeditor

runuser -u promoeditor -- git clone --depth 1 --branch main https://github.com/AlexK0l/PromoEditor.git /opt/promoeditor
runuser -u promoeditor -- python3 -m venv /opt/promoeditor/.venv
runuser -u promoeditor -- /opt/promoeditor/.venv/bin/python -m pip install --no-cache-dir -r /opt/promoeditor/requirements.txt

if [[ ! -f /etc/promoeditor/promoeditor.env ]]; then
  install -o root -g root -m 0600 /opt/promoeditor/deploy/time4vps/promoeditor.env.example /etc/promoeditor/promoeditor.env
fi
echo 'Set up password-only login before exposing the app to Caddy.'
python3 /opt/promoeditor/deploy/time4vps/provision_auth.py /etc/promoeditor/promoeditor.env
install -o root -g root -m 0644 /opt/promoeditor/deploy/time4vps/promoeditor.service /etc/systemd/system/promoeditor.service
systemctl daemon-reload
systemctl enable --now promoeditor.service
sleep 2
systemctl is-active --quiet promoeditor.service || { journalctl -u promoeditor -n 40 --no-pager; exit 1; }
code=$(curl --silent --output /dev/null --max-time 10 --write-out '%{http_code}' http://127.0.0.1:18080/api/config)
[[ "$code" == "401" ]] || { echo "Expected password protection (HTTP 401); received $code." >&2; exit 1; }
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18080/login >/dev/null

echo 'PromoEditor runs locally on 127.0.0.1:18080.'
echo 'Next: configure Caddy with deploy/time4vps/configure_caddy.sh.'
echo 'RegionalResearch was not restarted or modified.'
