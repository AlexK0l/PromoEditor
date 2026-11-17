"""Persistent server-side ceilings for paid OpenAI API attempts.

Counters are process-safe and survive Uvicorn/Docker restarts because the
SQLite database lives on PROMO_DATA_DIR (the existing persistent VPS volume).
No API keys, prompts, user addresses or image bytes are stored.

These are limits on *calls*, not monetary billing limits. Actual spending
still requires a separate budget in the OpenAI account.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ENV = {
    "image": ("PROMO_AI_IMAGE_CALLS_PER_DAY", 24, "генерации изображений"),
    "text": ("PROMO_AI_TEXT_CALLS_PER_DAY", 80, "текстовых/визуальных запросов"),
}


class QuotaExceeded(Exception):
    """A user-visible HTTP 429; the paid request MUST NOT be sent."""


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
    value = os.getenv(env, str(default))
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
    env, _, label = _ENV[kind]
    if limit == 0:
        raise QuotaExceeded(
            f"Платные вызовы OpenAI ({label}) отключены лимитом {env}=0."
        )
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
