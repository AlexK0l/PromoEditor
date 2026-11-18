> **Исторический документ от 17.11.2026.** Новые безопасные команды находятся в [инструкции от 18.11.2026](TIME4VPS_RELEASE_2026-11-18.md). Не выполняйте из этого документа устаревший `update.sh` без транзакционного отката.

# Выпуск PromoEditor на Time4VPS: контрольный список и откат

**Базовый проверенный набор:** PR #37–#43, коммит основного кода
`e4d40b85b0e858c2b4bb76a29bfc009d409f7049` (17.11.2026).
Используйте актуальный CI `main` перед установкой; этот документ не является
подтверждением состояния удалённого VPS.

## Важно

Речь о **существующей** установке Time4VPS с systemd, общим Caddy и отдельной
службой RegionalResearch. **Не используйте** Docker Compose,
`deploy/time4vps/install.sh` или повторную настройку Caddy для обновления.
**Не останавливайте**, не перезагружайте и не изменяйте RegionalResearch или Caddy.

`deploy/time4vps/update.sh` обновляет `/opt/promoeditor`, зависимости
Python и перезапускает только `promoeditor`. **Скрипт не откатывает обновление
автоматически**, если установка зависимостей или healthcheck завершится ошибкой.
Поэтому обязательно подготовьте самостоятельный путь отката.

## 1. Чтение состояния VPS, до любых изменений

Команды — в привилегированной SSH-сессии на Time4VPS. Не показывайте в чате
`OPENAI_API_KEY`, пароль, `PROMO_PASSWORD_HASH` и `PROMO_SESSION_SECRET`.

```bash
systemctl is-active promoeditor regionalresearch caddy
free -h
swapon --show
df -h /opt /var
systemctl show promoeditor -p MemoryMax -p MemoryCurrent
runuser -u promoeditor -- git -C /opt/promoeditor status --porcelain
runuser -u promoeditor -- git -C /opt/promoeditor rev-parse HEAD
stat -c '%a %U %G' /etc/promoeditor/promoeditor.env
bash /opt/promoeditor/deploy/time4vps/preflight.sh
```

**Стоп-условия:** любая основная служба неактивна, `git status --porcelain`
не пуст, недостаточно RAM/места, отсутствует `/var/lib/promoeditor/jobs`,
или конфигурация текущей авторизации отличается от ожидаемой.
На историческом VPS было около 1.9 GiB RAM и отсутствовал swap; фактическое
состояние необходимо проверить заново.

## 2. Резервная копия старого состояния

Создайте root-only каталог и сохраните точный коммит предыдущей версии плюс
исходный серверный конфиг без публикации его содержимого.

```bash
RELEASE_BACKUP="/root/promoeditor-releases/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o root -g root -m 0700 "$RELEASE_BACKUP"
runuser -u promoeditor -- git -C /opt/promoeditor rev-parse HEAD > "$RELEASE_BACKUP/previous-head"
install -o root -g root -m 0600 /etc/promoeditor/promoeditor.env "$RELEASE_BACKUP/promoeditor.env"
printf 'Private rollback folder: %s\n' "$RELEASE_BACKUP"
```

Запомните путь `RELEASE_BACKUP` в текущей SSH-сессии: он понадобится при
неудачном обновлении. Не загружайте этот каталог в публичные сервисы.

## 3. Настройка лимитов, пока платные операции ещё не тестируются

В `/etc/promoeditor/promoeditor.env` через `sudoedit` или защищённый
редактор проверьте наличие **ровно по одному** значению:

```dotenv
PROMO_AI_IMAGE_CALLS_PER_DAY=0
PROMO_AI_TEXT_CALLS_PER_DAY=0
PROMO_DOCUMENT_TIMEOUT_SECONDS=15
PROMO_DOCUMENT_MEMORY_MB=512
```

Нули временно запрещают *все новые* платные операции. После тестирования
локального режима и сверки бюджета OpenAI установите собственные квоты;
значения по умолчанию при отсутствии переменных — 24 попытки images/сутки
и 80 attempts responses/сутки (UTC). **Это не лимит в деньгах.**

Для Time4VPS `PROMO_DATA_DIR=/var/lib/promoeditor/jobs` задаётся в
systemd. Там должны создаваться `openai_call_quota.sqlite3` и временный
кэш успешных AI-изображений. Не удаляйте persistent job-том для «сброса
квоты»; это может уничтожить результаты других задач.

## 4. Обновление только PromoEditor

Только после успешных этапов 1–3:

```bash
bash /opt/promoeditor/deploy/time4vps/update.sh
runuser -u promoeditor -- git -C /opt/promoeditor rev-parse HEAD
systemctl is-active promoeditor regionalresearch caddy
systemctl show promoeditor -p MemoryCurrent -p MemoryMax
```

Используйте **только** скрипт `update.sh`, а не повторную установку.
Обновление до произвольно более нового `origin/main` допустимо только
после проверки его CI; сравните фактический SHA с запланированным выпуском.

## 5. Приёмочные тесты без платных вызовов

На Time4VPS со встроенным парольным входом **неавторизованный**
`/api/config` штатно возвращает **401**. Это не неисправность.
`/login` должен отдавать **200**.

```bash
curl --silent --output /dev/null --write-out 'login: %{http_code}\n' http://127.0.0.1:18080/login
curl --silent --output /dev/null --write-out 'anonymous API: %{http_code}\n' http://127.0.0.1:18080/api/config
systemctl is-active regionalresearch caddy promoeditor
journalctl -u promoeditor -n 60 --no-pager
```

В авторизованном браузере вручную проверьте шаблонную генерацию без AI:
оба формата PNG/JPEG, редактируемые SVG, ZIP и доступ к файлам.
Отдельно откройте RegionalResearch; его работоспособность не должна
измениться. После этого, при достаточной памяти и настроенном бюджете,
можно выставить небольшую ненулевую суточную квоту для контролируемого
AI smoke-теста. Никогда не тестируйте платный путь с нулевыми квотами как
проверку «сети OpenAI»: корректный ответ тогда 429.

## 6. Ручной откат при проблемах

`update.sh` **не гарантирует автоматический откат**, особенно после
изменения пакетов virtualenv. Если возникли ошибки:

1. Не затрагивайте Caddy или RegionalResearch.
2. Остановите **только** `promoeditor` на время восстановления.
3. Проверьте, что `git status --porcelain` пуст; **не выполняйте**
   `reset --hard`, если в checkout появились несохранённые изменения.
4. Восстановите прежний commit и окружение приложения.

```bash
systemctl stop promoeditor
runuser -u promoeditor -- git -C /opt/promoeditor status --porcelain
PREVIOUS_HEAD="$(cat "$RELEASE_BACKUP/previous-head")"
runuser -u promoeditor -- git -C /opt/promoeditor reset --hard "$PREVIOUS_HEAD"
runuser -u promoeditor -- /opt/promoeditor/.venv/bin/python -m pip install --no-cache-dir -r /opt/promoeditor/requirements.txt
install -o root -g root -m 0600 "$RELEASE_BACKUP/promoeditor.env" /etc/promoeditor/promoeditor.env
systemctl start promoeditor
systemctl is-active promoeditor regionalresearch caddy
```

Восстановление `pip` из прежних незакреплённых диапазонов версий **не
гарантирует идентичное окружение**; при сбое зависимостей может понадобиться
восстановление прежнего virtualenv из отдельной резервной копии или ручная
переустановка. Поэтому обновлять лучше в согласованное окно с резервным
копированием виртуального окружения или снапшотом VPS.

## Ограничения выпуска

- Автоматической периодической очистки всех устаревших результатов пока нет;
  не путайте TTL пользовательской выдачи с гарантированным удалением.
- Разбор PDF/DOCX/XLSX ограничен по времени и ресурсам, но **не изолирован
  полнофункциональной ОС-песочницей**.
- Квоты OpenAI учитывают попытки, а не фактические суммы в валюте.
- На историческом VPS `MemoryMax=800M` для PromoEditor и отдельный
  лимит дочернего процесса PDF 512 МБ могут потребовать проверки на
  нагрузке. Тестировать лучше в период без активных тяжёлых задач
  RegionalResearch.
