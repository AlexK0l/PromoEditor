#!/usr/bin/env bash
set -euo pipefail

# Read-only, non-secret RAM/OOM report for the existing shared Time4VPS.
# Never runs image generation, restarts, deployments or Caddy reconfiguration.
echo '=== Time4VPS: running services ==='
for unit in promoeditor regionalresearch caddy; do
  printf '%s: ' "$unit"
  systemctl is-active "$unit" 2>/dev/null || true
done

echo '=== PromoEditor: cgroup memory and service status ==='
systemctl show promoeditor \
  -p ActiveState -p SubState -p MemoryCurrent -p MemoryPeak \
  -p MemoryMax -p Result -p NRestarts -p ControlGroup

echo '=== Cgroup memory events (cumulative since cgroup creation) ==='
cg="$(systemctl show --value -p ControlGroup promoeditor)"
if [[ "$cg" == /* && "$cg" != *..* && -r "/sys/fs/cgroup$cg/memory.events" ]]; then
  awk '/^(low|high|max|oom|oom_kill|oom_group_kill) / {print}' \
    "/sys/fs/cgroup$cg/memory.events"
  if [[ -r "/sys/fs/cgroup$cg/memory.stat" ]]; then
    awk '/^(anon|file|kernel|slab) / {print}' \
      "/sys/fs/cgroup$cg/memory.stat"
  fi
else
  echo 'No readable cgroup-v2 memory.events; check systemd and kernel version.'
fi

echo '=== Host RAM and swap ==='
free -h
swapon --show || true
echo '=== Disk space (no private paths or secrets shown) ==='
df -h /opt /var 2>/dev/null || df -h /
echo '=== Installed application revision ==='
if [[ -d /opt/promoeditor/.git ]]; then
  git -C /opt/promoeditor rev-parse HEAD || true
fi
echo 'No mutations made. Compare BEFORE and AFTER a single controlled no-AI render.'
