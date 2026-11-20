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
    assert "Полная AI-генерация" in response.json()["detail"]


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


def test_approved_reference_preset_does_not_modify_legacy_demo():
    from app.approved_presets import approved_zubrtrail_500
    from app.render import compute_roi
    approved = approved_zubrtrail_500()
    assert approved["price"] == "6527000"
    assert approved["currency"] == "₽"
    assert approved["phones"] == ["+7 (951) 704-30-42",
                                   "+7 (951) 704-29-95"]
    assert len(approved["specs"]) == 10
    assert len(approved["dimensions"]) == 7
    result = compute_roi(approved)
    assert result["per_trip"] == 4500
    assert result["annual"] == 1080000
    assert result["gross"] == 5400000
    assert result["premium"] == 2284450
    assert result["net"] == 3115550
    with TestClient(main.app) as client:
        actual = client.get("/api/presets/zubrtrail-500")
        assert actual.status_code == 200
        assert actual.json()["brief"] == approved
        config = client.get("/api/config").json()
        assert "hybrid" in config["generation_modes"]
    assert default_brief()["price"] != approved["price"]


def test_completed_hybrid_response_reports_actual_mode(monkeypatch, tmp_path):
    from app.ai_layout import _safe_layout
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "rasterize_svg", lambda svg: (b"png", b"jpeg"))
    monkeypatch.setattr(main, "art_directed_layout", lambda *args, **kwargs: {
        "id": "hybrid_sales", "name": "Точный рекламный макет",
        "rationale": "Крупная техника и проверенные числа.",
        "scene_prompt": "Industrial scenery only, no trailer or text",
        "palette": {"background": "#FFFFFF", "foreground": "#172235",
                    "accent": "#E31B26"},
        "layouts": {fmt: _safe_layout(fmt, 0) for fmt in ("4x3", "9x16")},
    })
    monkeypatch.setattr(main, "generate_complete_artworks", lambda *args, **kwargs: {
        "4x3": Image.new("RGB", (128, 96)),
        "9x16": Image.new("RGB", (96, 128)),
    })
    out = main._generate_sync(
        default_brief(), _png(), None, None, None, [], False, True,
        "gpt-image-2.5-flare", "medium", "validated mock background",
        generation_mode="hybrid")
    assert out["generation_mode"] == "hybrid"
    brief_file = tmp_path / out["job_id"] / "brief.json"
    metadata = json.loads(brief_file.read_text(encoding="utf-8"))["_metadata"]
    assert metadata["generation_mode"] == "hybrid"
    assert metadata["art_director"].startswith("OpenAI Responses")


def test_primary_create_uses_experimental_full_poster_engine_not_template(
        monkeypatch, tmp_path):
    """Customer-facing Create must use EXACTLY the /api/ai-posters engine.

    A plan or SVG compositor here would regress to the templated result.
    No paid OpenAI network call is allowed in this regression test.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)
    original = _png("yellow")
    called = []

    def full_posters(brief, product, logo, drawing, reference, model, quality):
        called.append(("full_poster", product, model, quality))
        assert brief["model"]
        assert product == original
        return {
            "images": {"4x3": "/files/test/ai_poster_4x3.png",
                       "9x16": "/files/test/ai_poster_9x16.png"},
            "jpeg": {"4x3": "/files/test/ai_poster_4x3.jpg",
                     "9x16": "/files/test/ai_poster_9x16.jpg"},
            "zip": "/files/test/ai_posters.zip",
            "generation_mode": "openai_full_poster",
            "raster_only": True,
            "ai_used": True,
            "warnings": [],
        }

    def forbidden_old_renderer(*args, **kwargs):
        raise AssertionError("Primary AI creation called old layout renderer")

    monkeypatch.setattr(main, "_full_posters_sync", full_posters)
    monkeypatch.setattr(main, "_generate_sync", forbidden_old_renderer)
    with TestClient(main.app) as browser:
        result = browser.post("/api/generate",
            data={
                "payload": json.dumps(default_brief(), ensure_ascii=False),
                "generation_mode": "hybrid",
                "use_openai": "true",
                "model": "gpt-image-2.5-flare",
                "quality": "medium",
            },
            files={"hero": ("real.png", original, "image/png")})
    assert result.status_code == 200, result.text
    assert result.json()["generation_mode"] == "openai_full_poster"
    assert result.json()["raster_only"] is True
    assert result.json()["zip"].endswith("ai_posters.zip")
    assert "corel" not in result.json(), "Do not advertise a fake editable SVG"
    assert len(called) == 1 and called[0][0] == "full_poster"
