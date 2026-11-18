"""Hybrid mode and paid-image ZIP transaction regressions (zero real API calls)."""
import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai_poster_service, main, openai_service
from app.render import default_brief


def _png(color="yellow"):
    out = io.BytesIO()
    Image.new("RGB", (300, 180), color).save(out, "PNG")
    return out.getvalue()


def _api():
    calls = []

    class Images:
        def generate(self, **kwargs):
            calls.append(("generate", kwargs["size"]))
            return self._result()

        def edit(self, **kwargs):
            calls.append(("edit", kwargs["size"]))
            return self._result()

        def _result(self):
            datum = type("Datum", (), {
                "b64_json": base64.b64encode(_png("lightblue")).decode("ascii")
            })()
            return type("Result", (), {"data": [datum]})()

    return type("API", (), {"images": Images()})(), calls


def _fail_zip(*args, **kwargs):
    raise OSError("test-only ZIP failure after both paid images")


def test_hybrid_rejects_missing_photo_before_images_api(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)
    api, calls = _api()
    monkeypatch.setattr(openai_service, "client", lambda: api)
    with TestClient(main.app) as client:
        response = client.post("/api/generate", data={
            "payload": json.dumps(default_brief(), ensure_ascii=False),
            "generation_mode": "hybrid",
            "use_openai": "true",
        })
    assert response.status_code == 400
    assert "оригинальное фото" in response.json()["detail"]
    assert calls == []


def test_hybrid_rejects_faux_no_ai_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)
    with TestClient(main.app) as client:
        response = client.post("/api/generate", data={
            "payload": json.dumps(default_brief(), ensure_ascii=False),
            "generation_mode": "hybrid",
            "use_openai": "false",
        }, files={"hero": ("real.png", _png(), "image/png")})
    assert response.status_code == 400
    assert "AI-фон" in response.json()["detail"]


def test_paid_hybrid_renders_survive_failed_zip_and_retry_without_cost(
        monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "rasterize_svg", lambda svg: (b"png", b"jpeg"))
    api, calls = _api()
    monkeypatch.setattr(openai_service, "client", lambda: api)
    brief = default_brief()
    kwargs = {
        "brief": brief,
        "hero_raw": _png(),
        "detail_raw": None,
        "logo_raw": None,
        "drawing_raw": None,
        "references": [],
        "use_demo": False,
        "use_openai": True,
        "model": "gpt-image-2.5-flare",
        "quality": "medium",
        "design_prompt": "clean agricultural logistics environment",
    }
    with monkeypatch.context() as patch:
        patch.setattr(main.zipfile, "ZipFile", _fail_zip)
        with pytest.raises(OSError, match="ZIP failure"):
            main._generate_sync(**kwargs)
    paid_cache = openai_service._default_visual_cache(
        brief, True, [], kwargs["model"], kwargs["quality"],
        kwargs["design_prompt"], "")
    assert (paid_cache / "4x3.png").is_file()
    assert (paid_cache / "9x16.png").is_file()
    assert len(calls) == 2
    output = main._generate_sync(**kwargs)
    assert output["corel"]["4x3"].endswith(".svg")
    assert len(calls) == 2, "retry must not spend two more paid Images calls"
    assert not (paid_cache / "4x3.png").exists()
    archive = tmp_path / output["job_id"] / "promo_kit.zip"
    with zipfile.ZipFile(archive) as z:
        assert "corel_4x3.svg" in z.namelist()
        assert "corel_9x16.svg" in z.namelist()


def test_full_raster_poster_outputs_survive_zip_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    api, calls = _api()
    monkeypatch.setattr(ai_poster_service, "client", lambda: api)
    brief = default_brief()
    raw = _png()
    kwargs = (brief, raw, None, None, None,
              "gpt-image-2.5-flare", "medium")
    with monkeypatch.context() as patch:
        patch.setattr(main.zipfile, "ZipFile", _fail_zip)
        with pytest.raises(OSError, match="ZIP failure"):
            main._full_posters_sync(*kwargs)
    cache = openai_service._default_visual_cache(
        brief, True, [raw], "gpt-image-2.5-flare", "medium",
        ai_poster_service.VERSION, "complete-poster")
    assert (cache / "4x3.png").is_file()
    assert (cache / "9x16.png").is_file()
    assert len(calls) == 2
    output = main._full_posters_sync(*kwargs)
    assert len(calls) == 2
    assert not (cache / "4x3.png").exists()
    assert output["raster_only"] is True
    assert (tmp_path / output["job_id"] / "ai_posters.zip").is_file()
