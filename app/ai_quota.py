"""Optional, opt-in daily call ceilings for paid OpenAI API attempts.

Default is unlimited: PromoEditor does not restrict paid calls by UTC day.
Set a positive daily value to enable the old persistent SQLite counter.
Set "disabled" to explicitly block paid calls. Neither mode controls
provider billing: use an OpenAI account budget for cost management.
No API keys, prompts, addresses or image bytes are stored in counters.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ENV = {
    "image": ("PROMO_AI_IMAGE_CALLS_PER_DAY", 0, "генерации изображений"),
    "text": ("PROMO_AI_TEXT_CALLS_PER_DAY", 0, "текстовых/визуальных запросов"),
}


class QuotaExceeded(Exception):
    """Reject paid requests before dispatch; routed as a validation error."""


class QuotaStoreUnavailable(Exception):
    """Fail closed if durable usage cannot be recorded."""


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _data_dir() -> Path:
    return Path(os.getenv("PROMO_DATA_DIR", str(
        Path(__file__).resolve().parent.parent / "instance" / "jobs"
    )))


def _limit(kind: str) -> int:
    env, default, _ = _ENV[kind]
    value = os.getenv(env, str(default)).strip()
    # Explicit emergency stop; zero is deliberately UNLIMITED.
    if value.lower() in ("disabled", "off"):
        raise QuotaExceeded(
            f"Платные вызовы OpenAI ({_ENV[kind][2]}) отключены настройкой {env}=disabled."
        )
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise QuotaStoreUnavailable(f"Некорректная настройка {env} на сервере.") from exc
    if result < 0:
        raise QuotaStoreUnavailable(f"Значение {env} не может быть отрицательным.")
    return result


def reserve_paid_call(kind: str) -> None:
    """Atomically reserve one paid API attempt before dispatching the call.

    Entries are not refunded on upstream failures or uncertain timeouts:
    this deliberately favours a conservative spending ceiling. The UTC date
    separates daily buckets; SQLite serializes concurrent worker processes.
    """
    if kind not in _ENV:
        raise ValueError("Неизвестная категория платного запроса.")
    limit = _limit(kind)
    if limit == 0:
        # No application-imposed daily quota; OpenAI provider limits remain.
        return
    env, _, label = _ENV[kind]
    day = _utc_day()
    folder = _data_dir()
    path = folder / "openai_call_quota.sqlite3"
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        # First creator restricts DB permissions; no user content is persisted.
        handle = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(handle)
        with closing(sqlite3.connect(path, timeout=10, isolation_level=None)) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("""
                CREATE TABLE IF NOT EXISTS paid_call_usage (
                    utc_day TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN ('image','text')),
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    PRIMARY KEY (utc_day, category)
                )
            """)
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT attempts FROM paid_call_usage WHERE utc_day=? AND category=?",
                (day, kind),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                db.execute("ROLLBACK")
                raise QuotaExceeded(
                    f"Дневной лимит OpenAI ({label}): {limit} вызовов по UTC. "
                    "Новые платные запросы отклонены до следующего дня."
                )
            db.execute("""
                INSERT INTO paid_call_usage(utc_day, category, attempts)
                VALUES (?, ?, 1)
                ON CONFLICT(utc_day, category)
                DO UPDATE SET attempts = attempts + 1
            """, (day, kind))
            # Keep short-lived aggregate counts, not an ever-growing log.
            cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()
            db.execute("DELETE FROM paid_call_usage WHERE utc_day < ?", (cutoff,))
            db.execute("COMMIT")
    except QuotaExceeded:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise QuotaStoreUnavailable(
            "Сервер не смог записать учёт платных вызовов OpenAI. "
            "Запрос отклонён, чтобы не превысить лимит расходов."
        ) from exc



def check_paid_capacity(kind: str, needed: int) -> None:
    """Reject multi-image workflows when the daily quota cannot cover them.

    Read-only preflight: actual paid calls continue to use atomic reservations.
    Concurrent external usage can still change available capacity later.
    """
    if kind not in _ENV or needed < 0:
        raise ValueError("Неизвестная категория или число платных запросов.")
    if needed == 0:
        return
    limit = _limit(kind)
    if limit == 0:
        # No preflight daily cap, including multi-image workflows.
        return
    env, _, label = _ENV[kind]
    path = _data_dir() / "openai_call_quota.sqlite3"
    used = 0
    if path.is_file():
        try:
            with closing(sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, timeout=10)) as db:
                row = db.execute(
                    "SELECT attempts FROM paid_call_usage "
                    "WHERE utc_day=? AND category=?",
                    (_utc_day(), kind),
                ).fetchone()
                used = int(row[0]) if row else 0
        except (OSError, sqlite3.Error) as exc:
            raise QuotaStoreUnavailable(
                "Невозможно проверить суточный остаток OpenAI. "
                "Новые платные запросы заблокированы.") from exc
    available = max(0, limit-used)
    if available < needed:
        raise QuotaExceeded(
            f"Для выбранной AI-операции требуется новых вызовов "
            f"OpenAI Images: {needed}; доступно сегодня по UTC: {available} "
            f"(лимит {limit}). Проверьте {env} или дождитесь нового дня. "
            "Ни один новый платный вызов не отправлен."
        )
