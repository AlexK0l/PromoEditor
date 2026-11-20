"""Reverse-proxy-safe AI generation: mocked workers, no paid requests."""
import asyncio
import io
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import ai_job_queue, main
from app.render import default_brief


def _png():
    out=io.BytesIO()
    Image.new("RGB",(400,240),"yellow").save(out,"PNG")
    return out.getvalue()


def _poll(client,task_id,expected="complete",timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        answer=client.get("/api/generate/status/"+task_id)
        assert answer.status_code==200,answer.text
        state=answer.json()
        if state["status"] in ("complete","failed"):
            assert state["status"]==expected,state
            return state
        time.sleep(.03)
    raise AssertionError("Background task did not finish")


def _ready(monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","dummy-test-no-network")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda req:None)


def _post(client):
    return client.post(
        "/api/generate/start",data={
            "payload":json.dumps(default_brief(),ensure_ascii=False),
            "generation_mode":"hybrid","use_openai":"true",
        },files={
            "hero":("real-trailer.png",_png(),"image/png"),
        })


def test_async_job_snapshots_multipart_returns_fast_and_recovers_result(
        monkeypatch,tmp_path):
    _ready(monkeypatch,tmp_path)
    originals=[]
    async def process(form,progress=None):
        image=form.get("hero")
        assert image.filename=="real-trailer.png"
        raw=await image.read()
        originals.append(raw)
        assert raw==_png()
        assert form.get("generation_mode")=="hybrid"
        progress("Типографика и точный текст")
        await asyncio.sleep(.025)
        return {"images":{"4x3":"/files/test/img.png"},
                "zip":"/files/test/archive.zip",
                "raster_only":False}
    monkeypatch.setattr(main,"_generate_from_form",process)
    with TestClient(main.app) as client:
        started=_post(client)
        assert started.status_code==202,started.text
        item=started.json()
        assert item["status"]=="running"
        assert len(item["task_id"])==32
        state=_poll(client,item["task_id"])
        assert state["result"]["images"]["4x3"].endswith(".png")
        assert state["http_status"]==200
        assert originals==[_png()]
        folder=ai_job_queue.task_folder(tmp_path,item["task_id"])
        assert {p.name for p in folder.iterdir()}=={"status.json"}
        assert client.get("/api/generate/status/invalid").status_code==400


def test_one_paid_job_at_a_time_no_duplicate_charge_or_second_request(
        monkeypatch,tmp_path):
    _ready(monkeypatch,tmp_path)
    started=threading.Event()
    release=threading.Event()
    calls=[]
    async def pause(form,progress=None):
        calls.append("paid")
        started.set()
        assert await asyncio.to_thread(release.wait,3)
        return {"images":{"4x3":"/files/a/img.png"}}
    monkeypatch.setattr(main,"_generate_from_form",pause)
    with TestClient(main.app) as client:
        first=_post(client)
        assert first.status_code==202,first.text
        assert started.wait(3)
        blocked=_post(client)
        assert blocked.status_code==409
        assert "Уже выполняется AI-генерация" in blocked.json()["detail"]
        assert calls==["paid"],"No second paid request while one is running"
        release.set()
        _poll(client,first.json()["task_id"])
        next_request=_post(client)
        assert next_request.status_code==202,next_request.text
        _poll(client,next_request.json()["task_id"])
        assert calls==["paid","paid"]


def test_ai_job_failure_reports_stage_and_type_but_not_private_sdk_string(
        monkeypatch,tmp_path):
    _ready(monkeypatch,tmp_path)
    async def fail(form,progress=None):
        progress("AI распределяет текстовые зоны")
        raise RuntimeError("VERY_PRIVATE_API_KEY_and_customer_prompt")
    monkeypatch.setattr(main,"_generate_from_form",fail)
    with TestClient(main.app) as client:
        started=_post(client)
        assert started.status_code==202,started.text
        state=_poll(client,started.json()["task_id"],expected="failed")
    assert "AI распределяет текстовые зоны" in state["error"]
    assert "RuntimeError" in state["error"]
    assert "VERY_PRIVATE_API_KEY" not in state["error"]
    assert state["http_status"]==502


def test_process_restart_is_visible_without_automatically_repeating_ai(
        tmp_path):
    task_id,folder=ai_job_queue.new_task(tmp_path)
    ai_job_queue.set_status(folder,"running",stage="Сборка AI-шаблонов")
    status=json.loads((folder/"status.json").read_text(encoding="utf-8"))
    status["instance"]="previous-terminated-worker"
    (folder/"status.json").write_text(json.dumps(status),encoding="utf-8")
    recovered=ai_job_queue.read_status(tmp_path,task_id)
    assert recovered["status"]=="failed"
    assert recovered["http_status"]==503
    assert "перезапустился" in recovered["error"]
    assert "НЕ повторялся" in recovered["error"]


def test_main_async_job_uses_full_ai_posters_not_text_zone(
        monkeypatch,tmp_path):
    """The user's MAIN paid button must use the actual full Images pipeline.

    Verify the deferred route end-to-end, not just direct legacy
    /api/generate. No real paid OpenAI network requests run in CI.
    """
    _ready(monkeypatch,tmp_path)
    calls=[]
    def full(brief,product,logo,drawing,reference,model,quality,
             selected_source=None,progress=None):
        assert product==_png()
        assert selected_source["name"]=="real-trailer.png"
        calls.append("full-ai")
        if progress:
            progress("AI сам рисует надписи и всю композицию 4:3 и 9:16")
        return {
            "generation_mode":"openai_full_poster",
            "raster_only":True,
            "ai_used":True,
            "images":{"4x3":"/files/test/ai_poster_4x3.png",
                      "9x16":"/files/test/ai_poster_9x16.png"},
            "jpeg":{"4x3":"/files/test/ai_poster_4x3.jpg",
                    "9x16":"/files/test/ai_poster_9x16.jpg"},
            "zip":"/files/test/ai_posters.zip",
        }
    def fail(*args,**kw):
        raise AssertionError("Text-zone SVG engine must never run from main")
    monkeypatch.setattr(main,"_full_posters_sync",full)
    monkeypatch.setattr(main,"_exact_typography_posters_sync",fail)
    monkeypatch.setattr(main,"generate_exact_typography_posters",fail)
    with TestClient(main.app) as client:
        accepted=_post(client)
        assert accepted.status_code==202,accepted.text
        task=_poll(client,accepted.json()["task_id"])
    assert task["status"]=="complete"
    assert task["result"]["generation_mode"]=="openai_full_poster"
    assert task["result"]["raster_only"] is True
    assert task["result"]["zip"].endswith("/ai_posters.zip")
    assert "corel" not in task["result"]
    assert calls==["full-ai"]
