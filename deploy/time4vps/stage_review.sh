#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Isolated PR preview for the shared Time4VPS host. No main checkout,
# Caddy, RegionalResearch, or production jobs are modified.
# Usage (root): bash stage_review.sh <exact-reviewed-sha> [free|paid]
# Stop: systemctl stop promoeditor-preview
die(){ printf 'PR preview BLOCKED: %s\n' "$*" >&2; exit 1; }
info(){ printf 'PR preview: %s\n' "$*"; }
[[ "$EUID" -eq 0 ]] || die "Run as root."
[[ "$#" -ge 1 && "$#" -le 2 ]] || die "Need a reviewed full SHA and free|paid."
TARGET="$1"
MODE="free"
if [[ "$#" -eq 2 ]]; then MODE="$2"; fi
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] || die "Expected exact full commit SHA."
[[ "$MODE" == "free" || "$MODE" == "paid" ]] || die "Mode must be free or paid."

STAGE=/var/lib/promoeditor/pr58-preview
SOURCE="$STAGE/source"
JOBS="$STAGE/jobs"
ENV_FILE=/run/promoeditor-preview.env
PROD_ENV=/etc/promoeditor/promoeditor.env
UNIT=promoeditor-preview
BRANCH=feat/art-directed-one-screen-20261119
PORT=18081

id -u promoeditor >/dev/null || die "Missing promoeditor Unix user."
[[ -x /opt/promoeditor/.venv/bin/python ]] ||
  die "Production Python venv missing; stage uses it READ-ONLY."
[[ -f "$PROD_ENV" && ! -L "$PROD_ENV" ]] || die "Protected prod env missing."
[[ "$(stat -c '%U:%a' "$PROD_ENV")" == "root:600" ]] ||
  die "Production env must be root-owned and mode 0600."
for service in promoeditor regionalresearch caddy; do
  systemctl is-active --quiet "$service" ||
    die "Service $service is not active."
done
if systemctl is-active --quiet "$UNIT"; then
  die "Preview already running. Stop ONLY promoeditor-preview first."
fi
if ss -H -ltn "sport = :$PORT" | grep -q .; then
  die "Preview port $PORT is already in use."
fi
[[ ! -L "$STAGE" && ! -L "$SOURCE" && ! -L "$JOBS" ]] ||
  die "Preview path may not be a symlink."
[[ ! -e "$SOURCE" || -d "$SOURCE/.git" ]] ||
  die "Unexpected staging checkout; no overwrite."

# Check RAM before any changes. 1.9-GiB shared host previously had only
# 616 MiB available and no swap due to RegionalResearch's Chrome processes.
available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$available_kib" =~ ^[0-9]+$ ]] || die "Cannot read RAM availability."
needed=1152
if [[ "$MODE" == "paid" ]]; then needed=1400; fi
if (( available_kib < needed*1024 )); then
  die "Only $((available_kib/1024)) MiB RAM available; $MODE preview needs >= $needed MiB. Nothing changed."
fi
if [[ "$MODE" == "paid" ]]; then
  rr_bytes="$(systemctl show regionalresearch --value -p MemoryCurrent)"
  [[ "$rr_bytes" =~ ^[0-9]+$ ]] || die "Cannot determine RegionalResearch RAM."
  (( rr_bytes < 640*1024*1024 )) ||
    die "RegionalResearch uses $((rr_bytes/1024/1024)) MiB; paid preview requires <640 MiB."
  grep -Eq '^[[:space:]]*OPENAI_API_KEY[[:space:]]*=[[:space:]]*[^[:space:]#]+' "$PROD_ENV" ||
    die "Existing OpenAI key not configured."
fi
disk_kib="$(df -Pk /var/lib/promoeditor | awk 'END {print $4}')"
[[ "$disk_kib" =~ ^[0-9]+$ ]] || die "Cannot determine disk free space."
(( disk_kib >= 1024*1024 )) || die "Need >=1 GiB free disk."

install -d -o promoeditor -g promoeditor -m 0700 "$STAGE"
install -d -o promoeditor -g promoeditor -m 0700 "$JOBS"
if [[ -d "$SOURCE/.git" ]]; then
  [[ -z "$(runuser -u promoeditor -- git -C "$SOURCE" status --porcelain)" ]] ||
    die "Staging checkout is not clean."
else
  runuser -u promoeditor -- git clone --quiet --depth 1 --single-branch \
    --branch "$BRANCH" https://github.com/AlexK0l/PromoEditor.git "$SOURCE"
fi
current="$(runuser -u promoeditor -- git -C "$SOURCE" rev-parse HEAD)"
[[ "$current" == "$TARGET" ]] ||
  die "PR head changed to $current. Review new commit; no stage started."
info "Verified reviewed PR commit $current."

# Runtime-only root 0600 env; never expose secrets to the console, process
# arguments, URLs, git repository or generated preview files.
install -o root -g root -m 0600 /dev/null "$ENV_FILE"
{
  printf 'PROMO_AUTH_ENABLED=0\n'
  printf 'PROMO_DATA_DIR=%s\n' "$JOBS"
  printf 'PYTHONDONTWRITEBYTECODE=1\n'
  printf 'PYTHONUNBUFFERED=1\n'
  if [[ "$MODE" == "paid" ]]; then
    # Only OpenAI credentials; no production auth/password/session secret.
    grep -E '^[[:space:]]*(OPENAI_API_KEY|OPENAI_ORG_ID|OPENAI_PROJECT)[[:space:]]*=' "$PROD_ENV" || true
  else
    printf 'OPENAI_API_KEY=\n'
  fi
} > "$ENV_FILE"
chmod 0600 "$ENV_FILE"

# No Caddy publication, only loopback/SSH tunnel. Transient systemd service
# has a strict memory cgroup, no auto-restart and a 1-hour lifetime.
systemd-run --quiet --collect --unit="$UNIT" \
  -p Type=simple -p User=promoeditor -p Group=promoeditor \
  -p "WorkingDirectory=$SOURCE" -p "EnvironmentFile=$ENV_FILE" \
  -p MemoryHigh=340M -p MemoryMax=480M \
  -p TasksMax=48 -p CPUQuota=70% \
  -p LimitNOFILE=2048 -p UMask=0077 \
  -p Restart=no -p RuntimeMaxSec=3600 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes \
  -p ProtectHome=yes -p ProtectSystem=strict \
  -p "ReadWritePaths=$JOBS" \
  /opt/promoeditor/.venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port "$PORT" --workers 1 \
    --limit-concurrency 6 --timeout-keep-alive 5

http=""
for _ in $(seq 1 25); do
  http="$(curl --silent --output /dev/null --max-time 2 \
    --write-out '%{http_code}' "http://127.0.0.1:$PORT/api/config" || true)"
  [[ "$http" != "200" ]] || break
  sleep 1
done
if [[ "$http" != "200" ]]; then
  systemctl stop "$UNIT" || true
  die "Preview /api/config responded HTTP $http; production unchanged."
fi
for service in promoeditor regionalresearch caddy; do
  systemctl is-active --quiet "$service" ||
    die "Service $service became inactive; investigate immediately."
done
info "SUCCESS: $MODE preview on 127.0.0.1:$PORT ONLY."
info "Windows PowerShell: ssh -N -L 18081:127.0.0.1:18081 root@YOUR_VPS_IP"
info "Browser: http://127.0.0.1:18081"
info "Stop: systemctl stop promoeditor-preview (or automatic stop in one hour)."
if [[ "$MODE" == "paid" ]]; then
  info "IMPORTANT: clicking Create will make 3 paid OpenAI API requests."
else
  info "OpenAI key is absent in FREE staging; no paid calls possible."
fi
info "Production app, Caddy and RegionalResearch were not restarted."
