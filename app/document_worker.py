"""Bounded subprocess runner for untrusted PDF, DOCX and XLSX parsing.

The worker has NO access to the OpenAI API key or the main application's
environment. This limits CPU, virtual memory and wall-clock time, but is
NOT a full OS security sandbox (the child retains the service OS user).
"""
from __future__ import annotations

import base64
import io
import json
from contextlib import redirect_stdout
import os
import subprocess
import sys
import threading
from pathlib import Path

_MAX_INPUT_BYTES = 20 * 1024 * 1024
_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
# The production Time4VPS systemd unit has MemoryMax=800M.
# Only one parsing subprocess runs at a time in this Uvicorn worker.
_PARSE_SLOTS = threading.BoundedSemaphore(1)
_ROOT = Path(__file__).resolve().parent.parent


def _timeout_seconds() -> int:
    try:
        value = int(os.getenv("PROMO_DOCUMENT_TIMEOUT_SECONDS", "15"))
    except ValueError as exc:
        raise ValueError("Некорректная настройка лимита обработки документов.") from exc
    if not 2 <= value <= 60:
        raise ValueError("Таймаут документов должен быть от 2 до 60 секунд.")
    return value


def _memory_limit_mb() -> int:
    try:
        value = int(os.getenv("PROMO_DOCUMENT_MEMORY_MB", "512"))
    except ValueError as exc:
        raise ValueError("Некорректная настройка памяти документов.") from exc
    if not 256 <= value <= 768:
        raise ValueError("Лимит памяти документов должен быть от 256 до 768 МБ.")
    return value


def run_document_worker(operation: str, name: str, raw: bytes):
    """Run parsing in a killable process; never run a shell or external files."""
    if operation not in ("extract", "pdf_preview"):
        raise ValueError("Неизвестная операция обработки документа.")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_INPUT_BYTES:
        raise ValueError("Документ пуст или превышает 20 МБ.")
    timeout = _timeout_seconds()
    limit = _memory_limit_mb()
    env = {key: os.environ[key]
           for key in ("PATH", "LANG", "LC_ALL")
           if key in os.environ}
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PROMO_DOCUMENT_WORKER_TIMEOUT": str(timeout),
        "PROMO_DOCUMENT_WORKER_MEMORY_MB": str(limit),
    })
    command = [sys.executable, "-m", "app.document_worker", operation, str(name)[:160]]
    try:
        with _PARSE_SLOTS:
            result = subprocess.run(
                command, input=raw, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=str(_ROOT), env=env,
                timeout=timeout + 2, check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            "Документ обрабатывался слишком долго; лимит времени превышен."
        ) from exc
    except OSError as exc:
        raise ValueError("Не удалось запустить защищённый обработчик документов.") from exc

    if result.returncode != 0 or len(result.stdout) > _MAX_OUTPUT_BYTES:
        raise ValueError(
            "Обработка документа превышает доступные ресурсы или завершилась ошибкой."
        )
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or not payload.get("ok"):
            detail = payload.get("error") if isinstance(payload, dict) else ""
            raise ValueError(str(detail or "Не удалось обработать документ.")[:220])
        if operation == "pdf_preview":
            return base64.b64decode(payload["image"], validate=True)
        return str(payload["text"]), list(payload["warnings"])
    except (UnicodeDecodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Обработчик вернул некорректный результат.") from exc


def _apply_limits():
    """Called only within the subprocess, before importing office/PDF parsers."""
    if os.name == "posix":
        import resource
        memory = int(os.environ["PROMO_DOCUMENT_WORKER_MEMORY_MB"]) * 1024 * 1024
        cpu_seconds = int(os.environ["PROMO_DOCUMENT_WORKER_TIMEOUT"])
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))


def _worker_main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("extract", "pdf_preview"):
        return 2
    try:
        _apply_limits()
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if not raw or len(raw) > _MAX_INPUT_BYTES:
            raise ValueError("Превышен лимит исходного файла.")
        # Libraries may print notices to stdout; reserve stdout for one JSON reply.
        with redirect_stdout(io.StringIO()):
            from .documents import _extract_text_direct, _pdf_first_page_png_direct
            if sys.argv[1] == "extract":
                text, warnings = _extract_text_direct(sys.argv[2], raw)
                result = {"ok": True, "text": text[:36000], "warnings": warnings[:30]}
            else:
                image = _pdf_first_page_png_direct(raw)
                if len(image) > 20 * 1024 * 1024:
                    raise ValueError("Полученный чертёж слишком большой.")
                result = {"ok": True, "image": base64.b64encode(image).decode("ascii")}
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) > _MAX_OUTPUT_BYTES:
            raise ValueError("Результат обработки документа слишком большой.")
    except ValueError as exc:
        encoded = json.dumps({"ok": False, "error": str(exc)[:220]},
                             ensure_ascii=False).encode("utf-8")
    except Exception:
        encoded = json.dumps({"ok": False, "error": "Не удалось обработать документ."},
                             ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main())
