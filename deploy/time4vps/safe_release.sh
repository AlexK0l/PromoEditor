#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Pinned, transactional release for the EXISTING shared Time4VPS.
# Changes only PromoEditor's Git checkout, virtualenv and systemd unit.
# Never modifies Caddy, RegionalResearch, or /var/lib/promoeditor/jobs.
ROOT=/opt/promoeditor
ENV_FILE=/etc/promoeditor/promoeditor.env
BACKUP_ROOT=/root/promoeditor-releases
backup=""
previous=""
switched=0

die() { printf 'PromoEditor release stopped: %s\n' "$*" >&2; exit 1; }
note() { printf 'PromoEditor release: %s\n' "$*"; }
as_app() { runuser -u promoeditor -- "$@"; }

check_endpoints() {
  local attempt login_code api_code
  for ((attempt=1; attempt<=20; attempt++)); do
    if systemctl is-active --quiet promoeditor; then
      login_code="$(curl --silent --output /dev/null --max-time 3 --write-out '%{http_code}' \
        http://127.0.0.1:18080/login || true)"
      api_code="$(curl --silent --output /dev/null --max-time 3 --write-out '%{http_code}' \
        http://127.0.0.1:18080/api/config || true)"
      if [[ "$login_code" == "200" && "$api_code" == "401" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  note "Health check failed: expected /login=200 and private /api/config=401."
  return 1
}

on_exit() {
  local rc="$1" failed=0
  trap - EXIT ERR INT TERM
  if (( rc == 0 )); then return; fi
  if (( switched == 0 )); then
    note "No application switch took place; server was left unchanged."
    exit "$rc"
  fi
  note "Upgrade failed. Rolling back ONLY promoeditor from $backup" >&2
  systemctl stop promoeditor || failed=1
  if [[ -n "$previous" && -d "$ROOT/.git" ]]; then
    # Tree was checked clean before merge; reset only the app's checkout.
    as_app git -C "$ROOT" reset --hard "$previous" >/dev/null || failed=1
  else
    failed=1
  fi
  if [[ -d "$backup/venv" ]]; then
    # Keep failed venv for diagnosis; preserve the backup itself.
    if [[ -e "$ROOT/.venv" ]]; then
      mv "$ROOT/.venv" "$backup/failed-venv" || failed=1
    fi
    cp -a "$backup/venv" "$ROOT/.venv" || failed=1
  else
    failed=1
  fi
  if [[ -f "$backup/promoeditor.env" ]]; then
    install -o root -g root -m 0600 "$backup/promoeditor.env" "$ENV_FILE" || failed=1
  else
    failed=1
  fi
  systemctl start promoeditor || failed=1
  if ! check_endpoints; then failed=1; fi
  if (( failed == 0 )); then
    note "Previous version restored: $previous. Backup: $backup" >&2
  else
    note "AUTOMATIC ROLLBACK INCOMPLETE; inspect ONLY promoeditor, backup: $backup" >&2
  fi
  exit "$rc"
}
trap 'on_exit "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$#" -eq 1 ]] || die "Pass the exact 40-character reviewed GitHub main SHA."
TARGET="$1"
[[ "$EUID" -eq 0 ]] || die "Run this script as root using sudo."
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] ||
  die "Pass a complete 40-character reviewed commit SHA."
id -u promoeditor >/dev/null 2>&1 || die "User promoeditor is missing."
[[ -d "$ROOT/.git" ]] || die "Expected /opt/promoeditor checkout is missing."
[[ -d "$ROOT/.venv" && ! -L "$ROOT/.venv" ]] ||
  die "Existing virtualenv is missing or symlinked."
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || die "Private env file missing."
[[ "$(stat -c '%a' "$ENV_FILE")" == "600" ]] || die "Env must have mode 0600."
[[ "$(stat -c '%U' "$ENV_FILE")" == "root" ]] || die "Env must belong to root."
[[ -d /var/lib/promoeditor/jobs ]] || die "Private job directory missing."
[[ "$(as_app git -C "$ROOT" branch --show-current)" == "main" ]] ||
  die "Checkout must be on main."
[[ -z "$(as_app git -C "$ROOT" status --porcelain)" ]] ||
  die "Checkout has local changes; do not stash or reset."
for service in promoeditor regionalresearch caddy; do
  systemctl is-active --quiet "$service" ||
    die "Service $service is not active before release."
done
grep -Eq '^[[:space:]]*PROMO_AUTH_ENABLED=1([[:space:]]*(#.*)?)?$' "$ENV_FILE" ||
  die "Production password-only protection is not enabled."
command -v curl >/dev/null || die "curl is required."
command -v ldconfig >/dev/null || die "ldconfig is required."
ldconfig -p | grep 'libcairo.so.2' >/dev/null ||
  die "Cairo runtime missing; install separately before upgrade."
check_endpoints || die "Existing PromoEditor is unhealthy; release not started."

# The service's historical MemoryMax is 800M on a shared 1.9-GiB host.
available_kib="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$available_kib" =~ ^[0-9]+$ ]] || die "Unable to read free RAM."
(( available_kib >= 1024*1024 )) || die "Under 1 GiB RAM available; postpone."

note "Fetching reviewed main revision; other services remain untouched."
as_app git -C "$ROOT" fetch origin main
remote="$(as_app git -C "$ROOT" rev-parse origin/main)"
[[ "$remote" == "$TARGET" ]] ||
  die "Remote main $remote differs from pinned reviewed $TARGET."
previous="$(as_app git -C "$ROOT" rev-parse HEAD)"
if [[ "$previous" == "$TARGET" ]]; then
  note "Already on reviewed $TARGET; nothing to change."
  exit 0
fi
as_app git -C "$ROOT" merge-base --is-ancestor "$previous" "$TARGET" ||
  die "Target is not a fast-forward descendant of installed version."
venv_kib="$(du -sk "$ROOT/.venv" | awk '{print $1}')"
disk_kib="$(df -Pk /root | awk 'END {print $4}')"
[[ "$venv_kib" =~ ^[0-9]+$ && "$disk_kib" =~ ^[0-9]+$ ]] ||
  die "Unable to measure virtualenv/disk usage."
(( disk_kib >= venv_kib*2 + 524288 )) ||
  die "Insufficient free disk for rollback backup plus pip install."

install -d -o root -g root -m 0700 "$BACKUP_ROOT"
backup="$(mktemp -d "$BACKUP_ROOT/release-XXXXXXXX")"
chmod 0700 "$backup"
printf '%s\n' "$previous" > "$backup/previous-head"
printf '%s\n' "$TARGET" > "$backup/target-head"
install -o root -g root -m 0600 "$ENV_FILE" "$backup/promoeditor.env"
cp -a "$ROOT/.venv" "$backup/venv"
note "Private rollback backup created: $backup"
if ! grep -Eq '^[[:space:]]*PROMO_AI_IMAGE_CALLS_PER_DAY=0([[:space:]]*(#.*)?)?$' "$ENV_FILE"; then
  note "NOTICE: paid Images calls are not disabled; test first with controlled quotas."
fi

# Once mutation starts, any failure restores Git HEAD, virtualenv and env.
switched=1
# Never serve requests using a mixture of old and newly installed packages.
systemctl stop promoeditor
as_app git -C "$ROOT" merge --ff-only "$TARGET"
as_app "$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check \
  --no-cache-dir -r "$ROOT/requirements.txt"
systemctl start promoeditor
check_endpoints || die "New version failed HTTP smoke test."
[[ "$(as_app git -C "$ROOT" rev-parse HEAD)" == "$TARGET" ]] ||
  die "Deployed checkout differs from pinned target."
for service in regionalresearch caddy; do
  systemctl is-active --quiet "$service" ||
    die "$service became inactive; investigate application rollback."
done
switched=0
note "SUCCESS: PromoEditor is now at $TARGET."
note "Private rollback snapshot retained: $backup."
note "RegionalResearch and Caddy were not restarted or reconfigured."
note "Next: authenticated 4:3 / 9:16 SVG-PNG-ZIP and memory acceptance tests."
