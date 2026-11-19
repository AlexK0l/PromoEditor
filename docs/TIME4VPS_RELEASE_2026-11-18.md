# PromoEditor: безопасный выпуск на действующем Time4VPS — 18.11.2026

Только для **существующего** VPS, где PromoEditor (127.0.0.1:18080, один Uvicorn worker, MemoryMax=800M) работает вместе с RegionalResearch (127.0.0.1:10000) и общим Caddy (80/443). **Не запускать Docker Compose, повторную установку, configure_caddy.sh или старый update.sh**: они не предназначены для безопасного обновления этого общего узла. Используйте новый deploy/time4vps/safe_release.sh.

В GitHub PR #53 создал основной точный гибридный режим, отдельный утверждённый пример ZubrTrail 500 и защиту оплаченных изображений при ошибках ZIP. На VPS по последней диагностике пока стоял старый HEAD 1cb090b61f654fd55e08363fb823dc6dcf428743. Новый скрипт ставит **только полный SHA проверенного CI main**, делает резервную копию исходного Git SHA, всего Python virtualenv и серверного env, временно останавливает только PromoEditor, обновляет и проверяет приложение. При ошибке автоматически восстанавливает именно эту старую версию, её зависимости и конфигурацию. Не меняет Caddy, RegionalResearch и пользовательские файлы /var/lib/promoeditor/jobs.

## Этап 1: проверка без изменений

Войти по SSH на Time4VPS с привилегиями root. Не отправлять никому OPENAI_API_KEY, пароль, PROMO_PASSWORD_HASH, PROMO_SESSION_SECRET и содержимое серверного .env. Убедиться, что нет активных генераций.

~~~bash
systemctl is-active promoeditor regionalresearch caddy
runuser -u promoeditor -- git -C /opt/promoeditor rev-parse HEAD
runuser -u promoeditor -- git -C /opt/promoeditor status --porcelain
systemctl show promoeditor -p MemoryCurrent -p MemoryPeak -p MemoryMax
free -h
swapon --show
df -h /opt /var
curl -s -o /dev/null -w 'login: %{http_code}\n' http://127.0.0.1:18080/login
curl -s -o /dev/null -w 'anonymous API: %{http_code}\n' http://127.0.0.1:18080/api/config
~~~

Ожидается active для всех трёх служб, пустой git status, login=200 и закрытый anonymous API=401. Прервать выпуск при неуспехе. Ранее RAM available было около 1.4 GiB, swap отсутствовал — это **не** измерение пика при рендере. Скрипт дополнительно требует хотя бы 1 GiB MemAvailable, достаточный диск и включённый парольный вход.

**Важно для версий с PR об отмене лимитов:** значение `PROMO_AI_IMAGE_CALLS_PER_DAY=0` и `PROMO_AI_TEXT_CALLS_PER_DAY=0` теперь означает **без дневной квоты PromoEditor**, а не запрет. Для временного запрета платных вызовов используйте значение `disabled` и сохраните root-only копию env. В старых версиях `0` означало запрет, поэтому перед переключением проверьте фактический коммит. Скрипт не меняет настройки самостоятельно и не выводит секреты.

## Этап 2: запуск скрипта из точного нового коммита

Скрипт может отсутствовать в старом установленном коде. Следующие команды сначала получают файл из конкретного коммита main **без обновления работающего приложения**, затем запускают транзакционный выпуск. В первой строке подставьте полный 40-символьный SHA из GitHub main, для которого CI завершился success.

~~~bash
sudo -i
set -euo pipefail
TARGET_SHA='ВСТАВЬТЕ_ПОЛНЫЙ_40_СИМВОЛЬНЫЙ_SHA_ПРОВЕРЕННОГО_MAIN'
runuser -u promoeditor -- git -C /opt/promoeditor fetch origin main
REMOTE_SHA="$(runuser -u promoeditor -- git -C /opt/promoeditor rev-parse origin/main)"
test "$REMOTE_SHA" = "$TARGET_SHA" || { echo "STOP: main revision changed"; exit 1; }
runuser -u promoeditor -- git -C /opt/promoeditor show \
  "$TARGET_SHA:deploy/time4vps/safe_release.sh" > /root/promoeditor-safe-release.sh
chmod 0700 /root/promoeditor-safe-release.sh
bash -n /root/promoeditor-safe-release.sh
bash /root/promoeditor-safe-release.sh "$TARGET_SHA"
~~~

Ни первая команда fetch, ни staging скрипта не перезапускают службы. При переключении скрипт делает backup в /root/promoeditor-releases/release-XXXXXXXX, останавливает **только** promoeditor на время установки Python-зависимостей и восстановления сервиса. При любой ошибке после остановки выполняет автоматический rollback, включая прежнее virtualenv; если показано AUTOMATIC ROLLBACK INCOMPLETE, не повторять, а разбирать неудачное восстановление и сохранённую root-only копию.

## Этап 3: приёмочные проверки без оплаты OpenAI

~~~bash
systemctl is-active promoeditor regionalresearch caddy
runuser -u promoeditor -- git -C /opt/promoeditor rev-parse HEAD
bash /opt/promoeditor/deploy/time4vps/memory_report.sh
~~~

В браузере: войти по паролю → выбрать «ZubrTrail 500 · утверждённый эталон» → сверить цену **6 527 000 ₽**, телефоны, характеристики и экономику → загрузить оригинальные фото, логотип и чертёж → проверить выбор файлов → выбрать **бесплатный шаблон**, создать 4:3 и 9:16 и скачать SVG/PNG/JPEG/ZIP. Открыть оба SVG в CorelDRAW: текст, техника и чертёж должны быть раздельными редактируемыми объектами; фото и AI-фон внутри — растровые слои.

Повторить memory_report.sh после **одной** контролируемой бесплатной генерации реального большого фото, в период без высокой нагрузки RegionalResearch. Сравнить MemoryPeak и числовые счётчики memory.events: рост max сигнализирует о достижении лимита; рост oom / oom_kill или перезапуск службы — **стоп для платных генераций**. Отсутствие аварий в малом демо не доказывает безопасность для крупного фото. PR #45 с изоляцией рендера пока отдельный черновик, он **не включён** в этот выпуск.

## Ручной откат, если проблема обнаружилась после успешного обновления

Автоматический rollback работает при ошибке **в ходе обновления**. Для более поздней проблемы использовать путь root-only backup, показанный после успешного релиза. Проверить пустой рабочий git status перед reset --hard; никогда не выполнять reset, если появились неизвестные изменения.

~~~bash
sudo -i
BACKUP='/root/promoeditor-releases/release-XXXXXXXX'  # точный путь
test -f "$BACKUP/previous-head" && test -d "$BACKUP/venv" || exit 1
test -z "$(runuser -u promoeditor -- git -C /opt/promoeditor status --porcelain)" || exit 1
systemctl stop promoeditor
runuser -u promoeditor -- git -C /opt/promoeditor reset --hard "$(cat "$BACKUP/previous-head")"
mv /opt/promoeditor/.venv "$BACKUP/failed-venv-post-release"
cp -a "$BACKUP/venv" /opt/promoeditor/.venv
install -o root -g root -m 0600 "$BACKUP/promoeditor.env" /etc/promoeditor/promoeditor.env
systemctl start promoeditor
systemctl is-active promoeditor regionalresearch caddy
~~~

Не удаляйте /var/lib/promoeditor/jobs: там пользовательские задания, частный кэш оплаченных картинок и SQLite-учёт вызовов. Никакие команды выше не изменяют Caddy или RegionalResearch. До реальной проверки памяти, CorelDRAW и OpenAI с оригинальными материалами выпуск нельзя считать полностью приёмочным.
