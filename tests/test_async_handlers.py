"""Concurrency regressions for the synchronous document/preview workers.

No OpenAI calls are made. If a heavy operation accidentally runs directly on
the ASGI event loop again, the health check times out.
"""
import asyncio
import json
import threading

import httpx

from app import main
from app.render import default_brief


async def _assert_api_is_responsive(request_call, started, release):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        task = asyncio.create_task(request_call(client))
        try:
            # The event wait itself must not occupy the ASGI event loop.
            entered = await asyncio.to_thread(started.wait, 5)
            assert entered, "blocking test worker did not start"
            response = await asyncio.wait_for(client.get("/api/config"), timeout=1.5)
            assert response.status_code == 200
        finally:
            release.set()
        result = await asyncio.wait_for(task, timeout=10)
        assert result.status_code == 200, result.text
        return result


def test_document_parser_does_not_block_other_requests(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_extract(name, raw):
        started.set()
        assert release.wait(10), "document parser was never released"
        return "Объём: 55 м³", []

    monkeypatch.setattr(main, "extract_text", slow_extract)

    async def post(client):
        return await client.post(
            "/api/inspect",
            files={"documents": ("specs.txt", b"sample", "text/plain")},
        )

    result = asyncio.run(_assert_api_is_responsive(post, started, release))
    assert result.json()["files"][0]["characters"] == len("Объём: 55 м³")


def test_six_concept_previews_do_not_block_other_requests(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)

    report = {
        "project_assets": [],
        "selected_assets": {"primary_photo": None, "reference_example": None},
    }
    monkeypatch.setattr(
        main, "analyze_project",
        lambda *args, **kwargs: (report, {}),
    )
    monkeypatch.setattr(
        main, "generate_concepts",
        lambda *args, **kwargs: [{"id": "concept_0"}],
    )

    def slow_preview(*args):
        started.set()
        assert release.wait(10), "rendering worker was never released"
        return {"concept_set_id": "a" * 32, "concepts": []}

    monkeypatch.setattr(main, "_build_concept_previews_sync", slow_preview)

    async def post(client):
        return await client.post(
            "/api/concepts",
            data={"payload": json.dumps(default_brief(), ensure_ascii=False)},
        )

    result = asyncio.run(_assert_api_is_responsive(post, started, release))
    assert result.json()["concept_set_id"] == "a" * 32


def test_uploaded_image_verification_runs_in_worker(monkeypatch):
    from io import BytesIO
    from PIL import Image

    image = Image.new("RGB", (50, 30), "#C3D4E5")
    buf = BytesIO()
    image.save(buf, "PNG")
    started, release = threading.Event(), threading.Event()

    def slow_verify(name, raw):
        started.set()
        assert release.wait(10), "image verifier was never released"

    monkeypatch.setattr(main, "_validate_uploaded_image", slow_verify)
    monkeypatch.setattr(
        main, "analyze_project",
        lambda *args, **kwargs: (
            {"selected_assets": {}, "project_assets": []}, {},
        ),
    )

    async def post(client):
        return await client.post(
            "/api/analyze-assets",
            files={"photos": ("truck.png", buf.getvalue(), "image/png")},
        )

    asyncio.run(_assert_api_is_responsive(post, started, release))
