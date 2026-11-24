#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only diagnosis of outbound connectivity from the Time4VPS host.
# Usage (root or regular operator): bash diagnose_openai_network.sh
# No API key, no chargeable requests, no changes to services or firewall.
url='https://api.openai.com/v1/models'
printf 'PromoEditor: бесплатная проверка HTTPS до OpenAI API\n'
printf 'Проверяется лишь доступность сети, НЕ работа платной модели.\n'

if command -v getent >/dev/null 2>&1; then
  printf '\nDNS IPv4:\n'
  getent ahostsv4 api.openai.com | head -n 3 || true
  printf '\nDNS IPv6:\n'
  getent ahostsv6 api.openai.com | head -n 3 || true
fi

probe() {
  local family="$1"
  local response=''
  printf '\nHTTPS %s:\n' "$family"
  # --noproxy matches the isolated preview service, which does not
  # inherit the root shell's proxy environment. HTTP 401 without any
  # Authorization header is an EXPECTED and GOOD reachability result.
  if response="$(curl "$family" --noproxy '*' --silent --show-error \
    --connect-timeout 10 --max-time 20 --output /dev/null \
    --write-out 'HTTP %{http_code}; remote IP %{remote_ip}; TLS verify %{ssl_verify_result}; connect %{time_connect}s; TLS %{time_appconnect}s; total %{time_total}s' \
    "$url" 2>&1)"; then
    printf '%s\n' "$response"
  else
    printf 'Сетевая проверка не пройдена: %s\n' "$response"
  fi
}

probe --ipv4
probe --ipv6

printf '\nСостояние служб (только чтение):\n'
for svc in promoeditor promoeditor-exact-preview regionalresearch caddy; do
  if command -v systemctl >/dev/null 2>&1; then
    printf '%s: ' "$svc"
    systemctl is-active "$svc" || true
  fi
done
printf '\nДоступная память:\n'
awk '/^MemAvailable:/ {printf "%.0f MiB\\n", $2/1024}' /proc/meminfo
if command -v systemctl >/dev/null 2>&1; then
  systemctl show promoeditor-exact-preview \
    -p MemoryCurrent -p MemoryPeak -p MemoryMax -p NRestarts \
    --no-pager 2>/dev/null || true
fi

printf '\nИнтерпретация: HTTP 401 при запросе без ключа означает, что DNS/TLS/HTTPS работают.\n'
printf 'HTTP 000, ошибка DNS/TLS или тайм-аут требуют устранения сети до платного запроса.\n'
printf 'Это не проверка лимитов, скорости генерации изображений или оплаты.\n'
