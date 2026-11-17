"""Quota failures surface clearly from each paid API route, without upstream calls."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.ai_quota import QuotaExceeded, QuotaStoreUnavailable
from app.render import default_brief


def _blocked(error):
    def raise_quota(*args, **kwargs):
        raise error("test: no paid request may be sent")
    return raise_quota


def _png():
    stream = io.BytesIO()
    Image.new("RGB", (160, 160), "white").save(stream, "PNG")
    return stream.getvalue()


@pytest.mark.parametrize("error,status", [
    (QuotaExceeded, 429),
    (QuotaStoreUnavailable, 503),
])
@pytest.mark.parametrize("route", [
    "concepts", "generate", "analyze-assets", "edit", "inspect",
])
def test_paid_routes_preserve_quota_status(monkeypatch, route, error, status):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-ci-key")
    monkeypatch.setenv("PROMO_AUTH_ENABLED", "0")
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)
    failure = _blocked(error)
    empty_report = {"project_assets": [], "selected_assets": {"drawing": None}}
    fake_analyze = lambda *args, **kwargs: (empty_report, {})
    monkeypatch.setattr(main, "chosen_bytes", lambda report, records, role: [] if role == "references" else None)
    if route != "analyze-assets":
        monkeypatch.setattr(main, "analyze_project", fake_analyze)

    payload = json.dumps(default_brief(), ensure_ascii=False)
    with TestClient(main.app) as client:
        if route == "concepts":
            monkeypatch.setattr(main, "generate_concepts", failure)
            response = client.post("/api/concepts", data={"payload": payload})
        elif route == "generate":
            monkeypatch.setattr(main, "_generate_sync", failure)
            response = client.post("/api/generate", data={
                "payload": payload,
                "use_openai": "true",
            })
        elif route == "analyze-assets":
            monkeypatch.setattr(main, "analyze_project", failure)
            response = client.post("/api/analyze-assets", data={
                "payload": payload, "use_ai": "true",
            }, files={"documents": ("specs.txt", b"model: demo", "text/plain")})
        elif route == "edit":
            monkeypatch.setattr(main, "edit_promotional_image", failure)
            response = client.post("/api/edit", data={
                "instruction": "Исправить подсветку",
            }, files={"image": ("ad.png", _png(), "image/png")})
        else:
            monkeypatch.setattr(main, "analyze_documents", failure)
            response = client.post("/api/inspect", data={
                "use_ai": "true",
            }, files={"documents": ("specs.txt", b"model: demo", "text/plain")})

    assert response.status_code == status, (route, response.text)
    assert "test: no paid request" in response.json()["detail"]
