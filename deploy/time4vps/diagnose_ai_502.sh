#!/usr/bin/env bash
# Read-only diagnosis of HTTP 502 during a long PromoEditor AI operation.
# Never changes services, Caddy, RegionalResearch, env vars or process limits.
set -euo pipefail
echo "=== PromoEditor service health (READ ONLY) ==="
systemctl show promoeditor --no-pager \
  -p ActiveState -p SubState -p NRestarts \
  -p MemoryCurrent -p MemoryPeak -p MemoryMax || true
echo "=== Global memory ==="
free -m
echo "=== Local private-port HTTP status (200/302/401 may all be healthy with auth) ==="
curl --silent --show-error --max-time 6 --output /dev/null \
  --write-out 'PromoEditor 127.0.0.1:18080 HTTP %{http_code}\n' \
  http://127.0.0.1:18080/api/config || true
echo "=== Last 45 min: app lifecycle, task stages and failures ==="
journalctl -u promoeditor --since '-45 minutes' --no-pager -o cat 2>/dev/null \
  | grep -Ei 'PromoEditor AI task|ERROR|Traceback|502|503|500|worker|Started server|Shutting down|failed|oom|out of memory|killed|memory' \
  | tail -n 80 || true
echo "=== Last 45 min: kernel OOM / cgroup kill indicators ==="
journalctl -k --since '-45 minutes' --no-pager -o cat 2>/dev/null \
  | grep -Ei 'oom|out of memory|memory cgroup|killed process' \
  | tail -n 30 || true
echo "=== Done: no services or environment files were modified ==="
