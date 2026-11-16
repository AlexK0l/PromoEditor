"""Oversize photo analysis must keep original bytes for product-poster rendering."""
import base64
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import main as main_module
from app import openai_service
from app.asset_selection import analyze_project, chosen_bytes
from app.image_analysis import analysis_preview, validate_image_dimensions
from app.render import default_brief

client = TestClient(main_module.app)


@pytest.fixture(scope="module")
def original_large_jpeg():
    # 24 MP: previously rejected by asset_selection's 20 MP ceiling.
    im = Image.new("RGB", (6000, 4000), "#d2ad22")
    pen = ImageDraw.Draw(im)
    pen.rectangle((200, 250, 5800, 3400), outline="#171717", width=45)
    pen.line((150, 3900, 5900, 250), fill="#33424c", width=70)
    buffer = io.BytesIO()
    im.save(buffer, format="JPEG", quality=78)
    im.close()
    return buffer.getvalue()


def _groups(raw):
    return {
        "photos": [("original-6000x4000.jpg", raw)],
        "logos": [], "documents": [], "references": [], "drawings": []
    }


def _payload():
    return {"payload": json.dumps(default_brief(), ensure_ascii=False)}


def test_large_original_is_preprocessed_for_analysis_but_never_replaced(original_large_jpeg):
    original_hash = hashlib.sha256(original_large_jpeg).hexdigest()
    preview, dimensions = analysis_preview(original_large_jpeg, max_edge=300)
    assert dimensions == (6000, 4000)
    assert max(preview.size) <= 300
    assert hashlib.sha256(original_large_jpeg).hexdigest() == original_hash

    report, records = analyze_project(_groups(original_large_jpeg))
    photo = report["project_assets"][0]
    assert photo["width"] == 6000 and photo["height"] == 4000
    assert photo["analysis_width"] <= 300 and photo["analysis_height"] <= 300
    assert photo["analysis_resized"] is True
    assert "уменьшен" in photo["quality"]
    assert "оригинал" in photo["quality"].lower()
    assert any("Оригинальное изображение не изменено" in msg
               for msg in report["warnings"])
    assert photo["sha256"] == original_hash
    assert chosen_bytes(report, records, "primary_photo") is original_large_jpeg


def test_upload_accepts_24mp_and_generation_receives_exact_original(
        original_large_jpeg, monkeypatch):
    # This test checks the asset path, not the shared hourly quota. Other API
    # tests intentionally exercise the limiter with the same TestClient IP.
    monkeypatch.setattr(main_module, "_guard_rate", lambda _request: None)
    upload = [("photos", ("large.jpg", original_large_jpeg, "image/jpeg"))]
    reviewed = client.post("/api/analyze-assets", data=_payload(), files=upload)
    assert reviewed.status_code == 200, reviewed.text
    report = reviewed.json()
    assert report["project_assets"][0]["analysis_resized"] is True

    captured = {}

    def fake_generate(brief, hero_raw, *args):
        captured["sha256"] = hashlib.sha256(hero_raw).hexdigest()
        captured["length"] = len(hero_raw)
        with Image.open(io.BytesIO(hero_raw)) as image:
            captured["dimensions"] = image.size
        return {"test_confirmed": True}

    monkeypatch.setattr(main_module, "_generate_sync", fake_generate)
    requested = client.post(
        "/api/generate",
        data={**_payload(), "asset_report": json.dumps(report, ensure_ascii=False),
              "use_openai": "false", "use_demo": "false"},
        files=upload
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["test_confirmed"] is True
    assert captured == {
        "sha256": hashlib.sha256(original_large_jpeg).hexdigest(),
        "length": len(original_large_jpeg),
        "dimensions": (6000, 4000),
    }


def test_ai_vision_receives_512px_copy_not_original(original_large_jpeg, monkeypatch):
    seen = {}

    class Responses:
        def create(self, **kwargs):
            inputs = kwargs["input"][0]["content"]
            images = [item for item in inputs if item["type"] == "input_image"]
            assert len(images) == 1
            raw = base64.b64decode(images[0]["image_url"].split(",", 1)[1])
            with Image.open(io.BytesIO(raw)) as preview:
                seen["size"] = preview.size
                seen["format"] = preview.format
            return type("Result", (), {"output_text": '{"ratings":[],"warnings":[]}'})()

    monkeypatch.setattr(
        openai_service, "client",
        lambda: type("FakeAPI", (), {"responses": Responses()})()
    )
    records = [{
        "id": "photo_1", "kind": "photo",
        "name": "large.jpg", "raw": original_large_jpeg
    }]
    source_hash = hashlib.sha256(records[0]["raw"]).hexdigest()
    scored = openai_service.assess_asset_images(records)
    assert scored == {"ratings": [], "warnings": []}
    assert seen["format"] == "JPEG"
    assert max(seen["size"]) <= 512
    assert hashlib.sha256(records[0]["raw"]).hexdigest() == source_hash


def test_orientation_and_alpha_are_kept_in_analysis_preview():
    rotated = Image.new("RGB", (300, 200), "red")
    exif = Image.Exif()
    exif[274] = 6
    out = io.BytesIO()
    rotated.save(out, format="JPEG", exif=exif)
    preview, original = analysis_preview(out.getvalue(), max_edge=512)
    assert original == (300, 200)
    assert preview.size == (200, 300)

    rgba = Image.new("RGBA", (240, 140), (10, 20, 30, 0))
    out = io.BytesIO()
    rgba.save(out, format="PNG")
    transparent_preview, source = analysis_preview(out.getvalue(), max_edge=300)
    assert source == (240, 140)
    assert transparent_preview.mode == "RGBA"
    assert transparent_preview.getpixel((0, 0))[3] == 0


def test_unreasonably_large_or_tiny_originals_still_rejected():
    with pytest.raises(ValueError, match="48 млн пикселей"):
        validate_image_dimensions(8000, 7000)
    with pytest.raises(ValueError, match="10000 px"):
        validate_image_dimensions(11000, 2000)
    with pytest.raises(ValueError, match="32 px"):
        validate_image_dimensions(20, 500)
    validate_image_dimensions(6000, 4000)
