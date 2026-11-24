#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Isolated preview of a pinned exact-copy AI branch SHA on the shared Time4VPS host.
# No production checkout,
# Caddy, RegionalResearch, or production jobs are modified.
# Usage (root): bash stage_exact_copy_review.sh <exact-reviewed-branch-sha> [free|paid]
# Stop: systemctl stop promoeditor-exact-preview
die(){ printf 'Exact-copy preview BLOCKED: %s\n' "$*" >&2; exit 1; }
info(){ printf 'Exact-copy preview: %s\n' "$*"; }
[[ "$EUID" -eq 0 ]] || die "Run as root."
[[ "$#" -ge 1 && "$#" -le 2 ]] || die "Need a reviewed full SHA and free|paid."
TARGET="$1"
MODE="free"
if [[ "$#" -eq 2 ]]; then MODE="$2"; fi
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] || die "Expected exact full commit SHA."
[[ "$MODE" == "free" || "$MODE" == "paid" ]] || die "Mode must be free or paid."

STAGE=/var/lib/promoeditor/exact-copy-preview
SOURCE="$STAGE/source"
JOBS="$STAGE/jobs"
CACHE="$STAGE/cache"
ENV_FILE=/run/promoeditor-exact-preview.env
PROD_ENV=/etc/promoeditor/promoeditor.env
UNIT=promoeditor-exact-preview
BRANCH=fix/ai-exact-copy-stability-2026-11-23
PORT=18082

for binary in ss git curl systemd-run runuser; do
  command -v "$binary" >/dev/null || die "Missing host utility $binary."
done
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
  die "Preview already running. Stop ONLY promoeditor-exact-preview first."
fi
# Never overlap another staging preview with this memory-constrained test.
if systemctl is-active --quiet promoeditor-preview; then
  die "Another PromoEditor preview is running. Stop only that preview first."
fi
if ss -H -ltn "sport = :$PORT" | grep -q .; then
  die "Preview port $PORT is already in use."
fi
[[ ! -L "$STAGE" && ! -L "$SOURCE" && ! -L "$JOBS" && ! -L "$CACHE" ]] ||
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

if [[ "$MODE" == "paid" ]]; then
  # Zero-cost transport preflight, BEFORE touching the stage checkout or
  # exposing the production API key to the isolated service. Without an
  # Authorization header, HTTP 401 from /v1/models is expected. A TLS
  # handshake plus HTTP response proves that outbound HTTPS works.
  # The runtime service does not inherit root's proxy settings.
  api_status="$(curl --ipv4 --noproxy '*' --silent --show-error \
    --connect-timeout 10 --max-time 20 --output /dev/null \
    --write-out '%{http_code}' \
    https://api.openai.com/v1/models || true)"
  if [[ "$api_status" != "401" ]]; then
    api_status="$(curl --ipv6 --noproxy '*' --silent --show-error \
      --connect-timeout 10 --max-time 20 --output /dev/null \
      --write-out '%{http_code}' \
      https://api.openai.com/v1/models || true)"
  fi
  [[ "$api_status" == "401" ]] ||
    die "OpenAI unauthenticated models endpoint did not return expected HTTP 401 (last status $api_status). DNS/TLS, proxy or API edge access may be blocked. No paid requests made. Run diagnose_openai_network.sh."
  info "Zero-cost OpenAI HTTPS connectivity preflight passed (HTTP $api_status; no API key sent)."
fi

install -d -o promoeditor -g promoeditor -m 0700 "$STAGE"
install -d -o promoeditor -g promoeditor -m 0700 "$JOBS"
# CairoSVG/Pango/Fontconfig must be able to write font metadata caches.
# ProtectHome and ProtectSystem=strict otherwise leave no writable home.
install -d -o promoeditor -g promoeditor -m 0700 "$CACHE"
install -d -o promoeditor -g promoeditor -m 0700 "$CACHE/fontconfig"
if [[ -d "$SOURCE/.git" ]]; then
  [[ -z "$(runuser -u promoeditor -- git -C "$SOURCE" status --porcelain)" ]] ||
    die "Staging checkout is not clean."
  # A previous PR SHA may already be staged; update ONLY this isolated,
  # disposable checkout, after the preview service is confirmed stopped.
  runuser -u promoeditor -- git -C "$SOURCE" fetch --quiet --depth 1 \
    --no-tags origin "$BRANCH"
  reviewed="$(runuser -u promoeditor -- git -C "$SOURCE" rev-parse FETCH_HEAD)"
  [[ "$reviewed" == "$TARGET" ]] ||
    die "PR head moved to $reviewed; review the new commit first."
  runuser -u promoeditor -- git -C "$SOURCE" reset --quiet --hard "$TARGET"
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
  # Presentation bitmaps are scaled to the 1440/1080px poster before SVG
  # export; full uploaded originals remain in ZIP. Avoid 3200px RGBA
  # layers and expensive Cairo image copies on the 1.9GiB shared host.
  printf 'PROMO_RENDER_MAX_EDGE=1600\n'
  printf 'XDG_CACHE_HOME=%s\n' "$CACHE"
  printf 'PYTHONDONTWRITEBYTECODE=1\n'
  printf 'PYTHONUNBUFFERED=1\n'
  if [[ "$MODE" == "paid" ]]; then
    # Keep the already-paid rebranded photo and any completed art for 24h
    # instead of the 2h default. Support investigations often take longer
    # than two hours; never force an avoidable duplicate charged edit.
    # This is the isolated private staging data directory, NOT production.
    printf 'PROMO_JOB_TTL_SECONDS=86400\n'
    printf 'PROMO_OPENAI_ART_TIMEOUT_SECONDS=480\n'
    printf 'PROMO_LOW_MEMORY_QA=1\n'
    # Only OpenAI credentials; no production auth/password/session secret.
    grep -E '^[[:space:]]*(OPENAI_API_KEY|OPENAI_ORG_ID|OPENAI_PROJECT)[[:space:]]*=' "$PROD_ENV" || true
    # Honor configured call limits, using a separate preview counter DB.
    grep -E '^[[:space:]]*PROMO_AI_(IMAGE|TEXT)_CALLS_PER_DAY[[:space:]]*=' "$PROD_ENV" || true
  else
    printf 'OPENAI_API_KEY=\n'
  fi
} > "$ENV_FILE"
chmod 0600 "$ENV_FILE"

# No Caddy publication, only loopback/SSH tunnel. Transient systemd service
# has a strict memory cgroup, no auto-restart and a 1-hour lifetime.
# Paid Images + CairoSVG need a larger cgroup, but are allowed only when
# the measured preflight has >=1400 MiB MemAvailable and RegionalResearch
# is below 640 MiB. Free preview retains the smaller historical limit.
worker_high=420M
worker_max=480M
if [[ "$MODE" == "paid" ]]; then
  # On the 1.9 GiB host, MemoryHigh=660M produced >98% full PSI
  # while current was only ~676 MiB and MemoryMax was not reached.
  # Remove that reclaim/throttling cliff, retain the existing hard cap,
  # and reject optional QA when there is no safe working-memory reserve.
  worker_high=infinity
  worker_max=760M
fi
systemd-run --quiet --collect --unit="$UNIT" \
  -p Type=simple -p User=promoeditor -p Group=promoeditor \
  -p "WorkingDirectory=$SOURCE" -p "EnvironmentFile=$ENV_FILE" \
  -p "MemoryHigh=$worker_high" -p "MemoryMax=$worker_max" \
  -p TasksMax=48 -p CPUQuota=70% \
  -p LimitNOFILE=2048 -p UMask=0077 \
  -p Restart=no -p RuntimeMaxSec=3600 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes \
  -p ProtectHome=yes -p ProtectSystem=strict \
  -p "ReadWritePaths=$JOBS $CACHE" \
  -p InaccessiblePaths=/var/lib/promoeditor/jobs \
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

# API health alone cannot detect failed stylesheets. Without app.css the
# header's inline SVG becomes a giant blue browser-default hyperlink icon.
# Check the actual rendered page and each essential static asset BEFORE
# telling the operator that a visual preview is ready.
page_html="$(curl --silent --show-error --fail --max-time 8 "http://127.0.0.1:$PORT/" || true)"
if [[ "$page_html" != *'class="topbar"'* ||
      "$page_html" != *'id="promoeditor-embedded-styles"'* ||
      "$page_html" != *'.composer-grid{display:grid;'* ]]; then
  systemctl stop "$UNIT" || true
  die "Preview / is missing embedded usable CSS or expected HTML."
fi
for asset in app.css editor.css theme.css assets.css app.js editor.js assets.js theme.js; do
  probe="$(curl --silent --show-error --output /dev/null --max-time 8 \
    --write-out '%{http_code}|%{content_type}|%{size_download}' \
    "http://127.0.0.1:$PORT/static/$asset" || true)"
  IFS='|' read -r status mime bytes <<< "$probe"
  if [[ "$status" != "200" || ! "$bytes" =~ ^[0-9]+$ ||
        "$bytes" -lt 200 ]]; then
    systemctl stop "$UNIT" || true
    die "Preview asset /static/$asset failed: HTTP $status, type $mime, $bytes bytes."
  fi
  if [[ "$asset" == *.css && "$mime" != text/css* ]]; then
    systemctl stop "$UNIT" || true
    die "Preview CSS /static/$asset has wrong MIME type: $mime."
  fi
done
info "Main page and eight CSS/JS assets are reachable and nonempty."
for service in promoeditor regionalresearch caddy; do
  if ! systemctl is-active --quiet "$service"; then
    systemctl stop "$UNIT" || true
    die "Service $service became inactive; stopped preview immediately."
  fi
done
info "SUCCESS: $MODE preview on 127.0.0.1:$PORT ONLY."
info "Windows PowerShell: ssh -N -L 18082:127.0.0.1:18082 root@YOUR_VPS_IP"
info "Browser: http://127.0.0.1:18082"
info "Stop: systemctl stop promoeditor-exact-preview (or automatic stop in one hour)."
if [[ "$MODE" == "paid" ]]; then
  info "IMPORTANT: clicking Create now makes up to 3 PAID OpenAI Images requests (one rebrand + two complete AI-created posters at native 1536x1152 and 1152x2048); no automatic outpainting, crop or padding; optional paid photo ranking and opt-in Responses QA (skipped before billing if memory admission fails). Masked outpainting is available only as explicit refinement for old ZIPs. Existing ZIP can be reopened free and locally corrected with explicit paid confirmation. Only the selected rebranded view enters poster Images; secondary originals remain archive-only. NO algorithmic SVG text templates; source numbers in AI raster must be reviewed. Identical requests reuse cached posters; new variants require an explicit paid action."
else
  info "OpenAI key is absent in FREE staging; no paid calls possible."
fi
info "Production app, Caddy and RegionalResearch were not restarted."
