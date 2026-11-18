"""Run memory-heavy image rendering in disposable child processes.

The FastAPI process only handles validation and small JSON replies. Rasterization,
large Pillow bitmaps and six AI concept previews live in a child that exits
after each job, returning its native allocations to the OS. This is not an
OS security sandbox: the child runs with the application's filesystem rights.

The authenticated app supplies every argument. Uploaded bytes are written as
private binary files, never interpolated into shell commands, stdout or logs.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from .ai_quota import QuotaExceeded, QuotaStoreUnavailable
from .worker_slots import MEMORY_HEAVY_SLOT

BASE = Path(__file__).resolve().parent.parent
# A single heavy child per Uvicorn worker prevents overlapping 4:3/9:16 renders.
_RENDER_SLOTS = MEMORY_HEAVY_SLOT
_BLOB = re.compile(r"blob-[0-9]+\.bin\Z")
_ACTIONS = {"generate": "_generate_sync", "previews": "_build_concept_previews_sync",
            "posters": "_full_posters_sync"}


class RenderWorkerError(Exception):
    """A local render failed or was interrupted; no paid retry is automatic."""


def _storage() -> Path:
    return Path(os.getenv("PROMO_DATA_DIR", str(BASE / "instance" / "jobs")))


def _timeout() -> int:
    raw = os.getenv("PROMO_RENDER_TIMEOUT_SECONDS", "300")
    try:
        seconds = int(raw)
    except (ValueError, TypeError) as exc:
        raise RenderWorkerError("Неверное значение PROMO_RENDER_TIMEOUT_SECONDS.") from exc
    if seconds < 30 or seconds > 900:
        raise RenderWorkerError("PROMO_RENDER_TIMEOUT_SECONDS должен быть от 30 до 900.")
    return seconds


def _encode(value, folder: Path, counter: list[int]):
    """Encode only plain server-validated objects; byte streams use private files."""
    if isinstance(value, bytes):
        filename = f"blob-{counter[0]}.bin"
        counter[0] += 1
        (folder / filename).write_bytes(value)
        return {"type": "bytes", "file": filename}
    if isinstance(value, (list, tuple)):
        return {"type": "list", "items": [_encode(x, folder, counter) for x in value]}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise RenderWorkerError("Некорректные ключи задания рендеринга.")
        return {"type": "dict", "items": [
            [key, _encode(item, folder, counter)] for key, item in value.items()
        ]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return {"type": "scalar", "value": value}
    raise RenderWorkerError("Недопустимый тип данных для задания рендеринга.")


def _decode(value, folder: Path):
    """Never deserialize pickle or treat uploaded content as a filesystem path."""
    if not isinstance(value, dict):
        raise ValueError("Некорректный пакет рендеринга.")
    kind = value.get("type")
    if kind == "bytes":
        filename = value.get("file")
        if not isinstance(filename, str) or not _BLOB.fullmatch(filename):
            raise ValueError("Некорректная ссылка на бинарные данные.")
        return (folder / filename).read_bytes()
    if kind == "list":
        return [_decode(x, folder) for x in value["items"]]
    if kind == "dict":
        return {key: _decode(item, folder) for key, item in value["items"]}
    if kind == "scalar":
        return value["value"]
    raise ValueError("Некорректный тип в пакете рендеринга.")


def run_render_task(action: str, *args):
    """Block a background thread (not the ASGI loop) until the child exits."""
    if action not in _ACTIONS:
        raise RenderWorkerError("Неизвестное задание рендеринга.")
    with _RENDER_SLOTS:
        root = _storage()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Hex name allows existing two-hour job cleanup to remove a crash
        # orphan; normal completion always removes this private staging folder.
        folder = root / secrets.token_hex(16)
        folder.mkdir(mode=0o700)
        try:
            request = {
                "action": action,
                "args": _encode(list(args), folder, [0]),
            }
            (folder / "request.json").write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "app.render_worker", str(folder)],
                    cwd=BASE,
                    stdin=subprocess.DEVNULL,
                    # No raw uploads, tokens or generated imagery in stdout.
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    # Paid Images requests need the API key; authentication
                    # session material is unrelated and excluded.
                    env={k: v for k, v in os.environ.items() if k not in (
                        "PROMO_PASSWORD_HASH", "PROMO_SESSION_SECRET",
                    )},
                    timeout=_timeout(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderWorkerError(
                    "Превышено время сборки рекламных файлов. "
                    "Повторную платную генерацию не запускайте без проверки квот."
                ) from exc
            if completed.returncode != 0:
                raise RenderWorkerError(
                    "Процесс сборки завершился аварийно. "
                    "Проверьте свободную память и лимит службы PromoEditor."
                )
            try:
                answer = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RenderWorkerError("Не получен корректный ответ сборщика.") from exc
            if answer.get("status") == "ok" and isinstance(answer.get("result"), dict):
                return answer["result"]
            detail = str(answer.get("message", ""))[:500]
            match answer.get("kind"):
                case "quota_exceeded":
                    raise QuotaExceeded(detail)
                case "quota_store":
                    raise QuotaStoreUnavailable(detail)
                case "value_error":
                    raise ValueError(detail)
                case _:
                    raise RenderWorkerError(
                        "Ошибка изолированной сборки: " + (
                            detail if detail.startswith("Тип ошибки: ") else "проверьте входные файлы."
                        )
                    )
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def _child(folder: Path) -> int:
    """Executed by python -m app.render_worker, never from a web request."""
    import contextlib
    import io

    # The parent chooses a private staging path; no client-controlled path
    # is accepted by the HTTP API or embedded in a subprocess command.
    if not folder.is_dir() or folder.is_symlink():
        return 2
    try:
        data = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        action = data["action"]
        if action not in _ACTIONS:
            raise ValueError("Неизвестное задание.")
        args = _decode(data["args"], folder)
        if not isinstance(args, list):
            raise ValueError("Некорректные параметры.")
        with contextlib.redirect_stdout(io.StringIO()):
            # Import here, not in the parent, to keep heavy dependencies and
            # render-related native allocations inside this disposable process.
            from . import main
            result = getattr(main, _ACTIONS[action])(*args)
        answer = {"status": "ok", "result": result}
    except QuotaExceeded as exc:
        answer = {"status": "error", "kind": "quota_exceeded", "message": str(exc)}
    except QuotaStoreUnavailable as exc:
        answer = {"status": "error", "kind": "quota_store", "message": str(exc)}
    except ValueError as exc:
        answer = {"status": "error", "kind": "value_error", "message": str(exc)[:500]}
    except Exception as exc:
        # No exception repr/traceback: SDK messages can contain sensitive data.
        answer = {"status": "error", "kind": "failed",
                  "message": "Тип ошибки: " + type(exc).__name__}
    (folder / "result.json").write_text(
        json.dumps(answer, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(2)
    sys.exit(_child(Path(sys.argv[1])))
