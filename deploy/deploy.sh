#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo 'ERROR: Docker Engine and Docker Compose v2 are required.' >&2
  exit 1
fi

for file in deploy/app.env deploy/caddy.env; do
  if [ ! -f "$file" ]; then
    echo "ERROR: Missing $file; copy its .example and configure it first." >&2
    exit 1
  fi
done

# Fail closed if example credentials or example hostname are still present.
if grep -Eq '(^PROMO_DOMAIN=promo\.example\.com$|^PROMO_AUTH_HASH=.*REPLACE_WITH_YOUR_BCRYPT_HASH)' deploy/caddy.env; then
  echo 'ERROR: Replace example domain and bcrypt password hash in deploy/caddy.env.' >&2
  exit 1
fi

if ! grep -Eq '^PROMO_DOMAIN=[A-Za-z0-9.-]+$' deploy/caddy.env; then
  echo 'ERROR: Set one valid DNS hostname in PROMO_DOMAIN.' >&2
  exit 1
fi

if ! grep -Eq '^PROMO_AUTH_USER=[A-Za-z0-9_-]+$' deploy/caddy.env; then
  echo 'ERROR: Set a nonempty alphanumeric PROMO_AUTH_USER.' >&2
  exit 1
fi

# A bcrypt hash normally starts with $2a$, $2b$ or $2y$ and is single-quoted.
if ! grep -Eq "^PROMO_AUTH_HASH='[$]2[aby][$][0-9]{2}[$][./A-Za-z0-9]{53}'$" deploy/caddy.env; then
  echo 'ERROR: Set a valid single-quoted bcrypt hash in PROMO_AUTH_HASH.' >&2
  exit 1
fi

chmod 600 deploy/app.env deploy/caddy.env

docker compose -f compose.vps.yaml config --quiet
docker compose -f compose.vps.yaml build --pull
docker compose -f compose.vps.yaml up -d --remove-orphans
docker compose -f compose.vps.yaml ps
printf '\nDone. Test: curl -I https://YOUR_DOMAIN/ (expect HTTP 401 without credentials)\n'
