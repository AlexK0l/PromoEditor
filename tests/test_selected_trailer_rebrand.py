"""Selected-photo AI rebranding regressions. Entirely mocked; zero paid API traffic."""
import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import (
    ai_poster_service, asset_selection, main, product_rebrand_service,
)
from app.ai_quota import QuotaExceeded
from app.render import default_brief


def png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (420, 270), color).save(buffer, "PNG")
    return buffer.getvalue()


def reply(color):
    data = type("Datum", (), {
        "b64_json": base64.b64encode(png(color)).decode("ascii"),
    })()
    return type("Response", (), {"data": [data]})()


def selected_image_calls(monkeypatch):
    """Use separate fake image services to track exactly what gets edited."""
    calls = {"rebrand": [], "posters": []}

    class Rebrand:
        def edit(self, **kw):
            assert len(kw["image"]) in (1, 2)
            with Image.open(kw["image"][0]) as image:
                first_pixel = image.convert("RGB").getpixel((12, 12))
            calls["rebrand"].append({
                "pixel": first_pixel,
                "image_count": len(kw["image"]),
                "prompt": kw["prompt"],
            })
            return reply((180, 20, 180))

    class Poster:
        def edit(self, **kw):
            with Image.open(kw["image"][0]) as image:
                pixel = image.convert("RGB").getpixel((12, 12))
            calls["posters"].append({
                "pixel": pixel,
                "size": kw["size"],
                "prompt": kw["prompt"],
            })
            return reply((25, 180, 170))

    monkeypatch.setattr(
        product_rebrand_service, "client",
        lambda: type("API", (), {"images": Rebrand()})()
    )
    monkeypatch.setattr(
        ai_poster_service, "client",
        lambda: type("API", (), {"images": Poster()})()
    )
    return calls



def payload():
    brief = default_brief()
    brief["brand"] = "OUR BRAND"
    brief["model"] = "OUR TRAILER 500"
    return json.dumps(brief, ensure_ascii=False)


def test_multiple_photos_ai_picks_second_and_only_second_is_rebranded(
        monkeypatch, tmp_path):
    """Photo 1 stays unmodified; model receives ONLY photo 2 plus chosen logo."""
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key-not-real")
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "_guard_rate", lambda request: None)
    photos = [png((250, 210, 30)), png((20, 70, 220))]
    logo = png((30, 250, 90))
    observed = []
    def choose_best(records, requirements="", document_context=""):
        observed.append([(x["id"], x["kind"]) for x in records])
        return {"ratings": [
            {"id": "photo_1", "score": 18, "reason": "Не лучший ракурс",
             "suggested_role": "secondary_photo"},
            {"id": "photo_2", "score": 98, "reason": "Полный вид сбоку",
             "suggested_role": "primary_photo"},
        ], "warnings": []}
    from app import openai_service
    monkeypatch.setattr(openai_service, "assess_asset_images", choose_best)
    calls = selected_image_calls(monkeypatch)
    monkeypatch.setattr(
        main, "generate_exact_typography_posters",
        lambda *args, **kw: pytest.fail("No SVG/text-zone renderer in full AI mode"))
    with TestClient(main.app) as app:
        result = app.post("/api/generate", data={
            "payload": payload(), "generation_mode": "hybrid",
            "use_openai": "true", "model": "gpt-image-2.5-flare",
            "quality": "medium",
        }, files=[
            ("hero", ("front-view.png", photos[0], "image/png")),
            ("hero", ("side-view.png", photos[1], "image/png")),
            ("logo", ("owned-logo.png", logo, "image/png")),
        ])
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["selected_photo"]["id"] == "photo_2"
        assert data["selected_photo"]["name"] == "side-view.png"
        assert data["rebranding_applied"] is True
        assert len(observed) == 1, "Exactly one targeted paid AI photo ranking"
        assert observed[0] == [("photo_1", "photo"), ("photo_2", "photo")]
        assert len(calls["rebrand"]) == 1, "Never rebrand all uploaded photos"
        assert calls["rebrand"][0]["pixel"] == (20, 70, 220)
        assert calls["rebrand"][0]["image_count"] == 2, "Chosen photo + logo only"
        assert len(calls["posters"]) == 2, "AI must draw BOTH complete posters"
        assert {call["size"] for call in calls["posters"]} == {
            "1536x1024", "1024x1536"}
        assert all(call["pixel"] == (180, 20, 180)
                   for call in calls["posters"]), "Use the ONE rebranded hero"
        assert all("never reintroduce any former manufacturer" in
                   call["prompt"].lower() for call in calls["posters"])
        assert data["generation_mode"] == "openai_full_poster"
        assert data["raster_only"] is True
        assert data["zip"].endswith("ai_posters.zip")
        assert "corel" not in data, "No pretend editable SVG from raster AI"
        with zipfile.ZipFile(io.BytesIO(app.get(data["zip"]).content)) as z:
            assert z.read("originals/product_photo.png") == photos[1]
            assert z.read("originals/customer_logo.png") == logo
            assert "rebranded_product.png" in z.namelist()
            chosen = json.loads(z.read("selected_photo.json"))
            assert chosen["selected_primary"]["id"] == "photo_2"
            assert chosen["rebranded_only_this_photo"] is True
            assert chosen["other_uploaded_photos_untouched"] is True
            with Image.open(io.BytesIO(z.read("rebranded_product.png"))) as image:
                assert image.getpixel((12, 12)) == (180, 20, 180)
    assert photos[0] == png((250, 210, 30)), "Photo 1 bytes unchanged"


def test_manual_photo_choice_wins_and_does_not_pay_for_vision(
        monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key-not-real")
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "_guard_rate", lambda req: None)
    from app import openai_service
    monkeypatch.setattr(
        openai_service, "assess_asset_images",
        lambda *a, **kw: pytest.fail("Manual selection must skip paid AI ranking"),
    )
    calls = selected_image_calls(monkeypatch)
    monkeypatch.setattr(
        main, "generate_exact_typography_posters",
        lambda *args, **kw: pytest.fail("No SVG/text-zone renderer in full AI mode"))
    with TestClient(main.app) as app:
        response = app.post("/api/generate", data={
            "payload": payload(), "generation_mode": "hybrid",
            "use_openai": "true",
            "asset_preferences": json.dumps({"photo_1": "include"}),
        }, files=[
            ("hero", ("selected.png", png((250, 210, 30)), "image/png")),
            ("hero", ("not-selected.png", png((20, 70, 220)), "image/png")),
            ("logo", ("logo.png", png((30, 250, 90)), "image/png")),
        ])
    assert response.status_code == 200, response.text
    assert response.json()["selected_photo"]["id"] == "photo_1"
    assert len(calls["rebrand"]) == 1
    assert len(calls["posters"]) == 2
    assert calls["rebrand"][0]["pixel"] == (250, 210, 30)
    assert all(call["pixel"] == (180, 20, 180)
               for call in calls["posters"])
    assert response.json()["raster_only"] is True


def test_rebrand_cache_is_bound_to_selected_photo_logo_brand_and_model(
        monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    photo1 = png((250, 210, 30))
    photo2 = png((20, 70, 220))
    logo = png((30, 250, 90))
    b1 = {"brand": "B1", "model": "M1"}
    b2 = {"brand": "B2", "model": "M1"}
    args = ("gpt-image-2.5-flare", "medium")
    folder = product_rebrand_service.cache_dir(b1, photo1, logo, *args)
    assert folder != product_rebrand_service.cache_dir(b1, photo2, logo, *args)
    assert folder != product_rebrand_service.cache_dir(b2, photo1, logo, *args)
    assert folder != product_rebrand_service.cache_dir(
        b1, photo1, png((90, 10, 200)), *args)


def test_rebrand_prompt_only_changes_trailer_not_tractor_or_surroundings():
    prompt = product_rebrand_service._prompt(
        {"brand": "NEW", "model": "MODEL 17"}, has_logo=True)
    for term in (
        "Image 1", "Image 2", "Edit ONLY", "ON THE TRAILER ITSELF",
        "existing manufacturer logos", "customer brand name",
        "CUSTOMER MODEL NAME", "attached tractor cab", "background",
        "No traces of the old branding",
    ):
        assert term.lower() in prompt.lower(), term
    assert '"customer_brand":"NEW"' in prompt
    assert '"customer_model":"MODEL 17"' in prompt
    without_logo = product_rebrand_service._prompt(
        {"brand": "", "model": "ONLY MODEL"}, has_logo=False)
    assert "Do not invent or add a trademark." in without_logo
    assert "do NOT invent a brand name" in without_logo


def test_insufficient_image_quota_blocks_before_first_rebrand_call(
        monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY", "2")
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    calls = selected_image_calls(monkeypatch)
    with pytest.raises(QuotaExceeded, match="Ни один новый платный"):
        main._full_posters_sync(
            default_brief(), png("yellow"), None, None, None,
            "gpt-image-2.5-flare", "medium")
    assert not calls["rebrand"] and not calls["posters"]
