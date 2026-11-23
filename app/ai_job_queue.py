"""Private, recoverable status for long-running paid AI generation jobs.

A large multi-step OpenAI workflow must not keep one reverse-proxy request
open for minutes. Input files stay inside the private PromoEditor data
directory, never beneath /files. No automatic retry of paid requests.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from starlette.datastructures import FormData, Headers, UploadFile

JOB_ID = re.compile(r"^[a-f0-9]{32}$")
PROCESS_ID = secrets.token_hex(16)
STATUS_NAME = "status.json"
FORM_NAME = "form.json"
ROOT_NAME = ".ai_generation_tasks"
TTL = 7200
MAX_TOTAL_BYTES = 68 * 1024 * 1024
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def task_root(storage: Path) -> Path:
    return Path(storage) / ROOT_NAME


def task_folder(storage: Path, task_id: str) -> Path:
    if not JOB_ID.fullmatch(str(task_id)):
        raise ValueError("Некорректный номер задачи.")
    return task_root(storage) / task_id


def new_task(storage: Path) -> tuple[str, Path]:
    root = task_root(storage)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for _ in range(3):
        task_id = secrets.token_hex(16)
        path = root / task_id
        try:
            path.mkdir(mode=0o700)
            return task_id, path
        except FileExistsError:
            continue
    raise OSError("Невозможно создать уникальный номер задачи.")


def set_status(folder: Path, status: str, *, stage: str = "",
               result: dict | None = None, error: str = "",
               http_status: int = 200,
               recovery_zip: str | None = None) -> None:
    if status not in ("running", "complete", "failed"):
        raise ValueError("Неизвестное состояние задачи.")
    record = {
        "status": status, "stage": str(stage)[:170],
        "result": result if status == "complete" else None,
        "error": str(error)[:500] if status == "failed" else "",
        "http_status": int(http_status),
        "recovery_zip": (recovery_zip if status == "failed" else None),
        "instance": PROCESS_ID, "updated_at": time.time(),
    }
    destination = folder / STATUS_NAME
    temporary = folder / ("." + secrets.token_hex(8) + ".tmp")
    try:
        temporary.write_text(
            json.dumps(record,ensure_ascii=False,separators=(",",":")),
            encoding="utf-8",
        )
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_status(storage: Path, task_id: str) -> dict | None:
    folder = task_folder(storage,task_id)
    source = folder / STATUS_NAME
    try:
        if time.time() - source.stat().st_mtime > TTL:
            return None
        content = json.loads(source.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return None
    if not isinstance(content,dict):
        return None
    if content.get("status") == "running" and content.get("instance") != PROCESS_ID:
        # Preserve the last completed process' real stage instead of hiding
        # it on restart. This distinguishes a failed AI call from memory
        # pressure during SVG export, although it cannot prove OOM by itself.
        last = str(content.get("stage") or "этап не определён")[:150]
        return {
            "status":"failed", "stage":last,
            "error":(
                "PromoEditor перезапустился до завершения AI-генерации. "
                "Последний этап: "+last+". "
                "Возможна нехватка RAM или перезапуск службы. "
                "Проверьте журнал promoeditor и события OOM ядра. "
                "Платный запрос автоматически НЕ повторялся."
            ),
            "http_status":503, "result":None,
            "recovery_zip":None,
        }
    return {
        key:content.get(key) for key in
        ("status","stage","error","http_status","result",
         "recovery_zip")
    }


async def snapshot_form(form: FormData, folder: Path) -> None:
    """Copy incoming multipart BEFORE the HTTP request gets closed."""
    records=[]
    size=0
    uploads=0
    for key,value in form.multi_items():
        if isinstance(value,UploadFile):
            uploads+=1
            if uploads > 16:
                raise ValueError("Не более 16 файлов в одном проекте.")
            stored=f"upload_{uploads:02d}"
            path=folder/stored
            written=0
            with path.open("xb") as target:
                while True:
                    chunk=await value.read(1024*1024)
                    if not chunk:
                        break
                    size+=len(chunk)
                    written+=len(chunk)
                    if written > MAX_UPLOAD_BYTES or size > MAX_TOTAL_BYTES:
                        raise ValueError("Превышен лимит 20 МБ на файл или 68 МБ на проект.")
                    target.write(chunk)
            records.append({
                "key":str(key),"kind":"file","path":stored,
                "filename":str(value.filename or "")[:240],
                "content_type":str(value.content_type or
                                   "application/octet-stream")[:120],
            })
        else:
            field=str(value)
            size+=len(field.encode("utf-8"))
            if size>MAX_TOTAL_BYTES:
                raise ValueError("Превышен лимит 68 МБ на проект.")
            records.append({"key":str(key),"kind":"field","value":field})
    (folder/FORM_NAME).write_text(
        json.dumps(records,ensure_ascii=False,separators=(",",":")),
        encoding="utf-8")


def reopen_form(folder: Path) -> tuple[FormData,list]:
    """Replay exact multipart keys/order for the unchanged main API logic."""
    records=json.loads((folder/FORM_NAME).read_text(encoding="utf-8"))
    items=[]
    open_files=[]
    try:
        for record in records:
            if record["kind"] == "field":
                items.append((record["key"],record["value"]))
            else:
                name=str(record["path"])
                if not re.fullmatch(r"upload_[0-9]{2}",name):
                    raise ValueError("Некорректный файл задачи.")
                handle=(folder/name).open("rb")
                open_files.append(handle)
                upload=UploadFile(
                    file=handle,
                    filename=record["filename"],
                    headers=Headers({
                        "content-type":record["content_type"],
                    }),
                )
                items.append((record["key"],upload))
        return FormData(items),open_files
    except Exception:
        for handle in open_files:
            handle.close()
        raise


def erase_uploads(folder: Path) -> None:
    """Keep only the opaque job status; remove private source inputs."""
    try:
        for path in folder.iterdir():
            if path.is_file() and path.name != STATUS_NAME:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup(storage: Path) -> None:
    root=task_root(storage)
    if not root.is_dir():
        return
    now=time.time()
    try:
        entries=list(root.iterdir())[:500]
    except OSError:
        return
    for folder in entries:
        try:
            if (folder.is_dir() and JOB_ID.fullmatch(folder.name)
                    and now-folder.stat().st_mtime>TTL):
                shutil.rmtree(folder,ignore_errors=True)
        except OSError:
            continue
