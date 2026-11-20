"""Automatic hybrid art direction: one text plan + two AI-only backdrops.

These tests never call the real paid OpenAI API.
"""
import io
import json
import os
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from PIL import Image

from app import main, hybrid_art_director
from app.ai_layout import _safe_layout
from app.approved_presets import approved_zubrtrail_500


def _png(color="yellow"):
    out = io.BytesIO()
    Image.new("RGBA", (360, 220), color).save(out, format="PNG")
    return out.getvalue()


def _concept(index=0):
    return {
        "id": f"concept_{index}",
        "name": "Выразительная промышленная реклама",
        "rationale": "Крупная техника и контрастные характеристики.",
        "scene_prompt": "Cinematic industrial quarry, background only, no vehicles.",
        "palette": {
            "background": "#E7EDF4", "foreground": "#172235", "accent": "#345BCD",
        },
        "layouts": {fmt: _safe_layout(fmt, index) for fmt in ("4x3", "9x16")},
    }


def test_art_directed_plan_caches_without_second_paid_text_call(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    brief = approved_zubrtrail_500()
    calls = []

    def paid(brief_arg, **kwargs):
        calls.append(kwargs)
        return [_concept(0), _concept(1), _concept(2)]

    monkeypatch.setattr(hybrid_art_director, "generate_concepts", paid)
    first = hybrid_art_director.art_directed_layout(brief, _png())
    assert len(calls) == 1
    assert first["id"] == "hybrid_sales"
    assert first["palette"]["accent"] == brief["accent"]
    assert first["layouts"]["4x3"]["hero"]["w"] >= 350
    assert calls[0]["style"] == "bold"
    assert calls[0]["goal"] == "sales"
    assert calls[0]["cinematic_hybrid"] is True, (
        "Primary AI mode must reserve a large unobstructed original-product stage"
    )

    stale = tmp_path / ".hybrid_art_plans" / ("f" * 64)
    stale.mkdir()
    (stale / "plan.json").write_text("old plan", encoding="utf-8")
    expiry = time.time()-9000
    os.utime(stale, (expiry, expiry))
    again = hybrid_art_director.art_directed_layout(brief, _png())
    assert not stale.exists(), "Expired AI design plans must not accumulate forever"
    assert again == first
    assert len(calls) == 1, "identical retry must reuse paid art direction"

    changed = hybrid_art_director.art_directed_layout(brief, _png("orange"))
    assert changed["id"] == "hybrid_sales"
    assert len(calls) == 2, "different customer photo needs own plan"
    caches = list((tmp_path / ".hybrid_art_plans").glob("*/plan.json"))
    assert len(caches) == 2
    assert all(not path.name.startswith("ZubrTrail") for path in caches)


def test_invalid_ai_layout_does_not_trigger_visual_api(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    calls = []

    def broken(*args, **kwargs):
        calls.append("layout")
        raise ValueError("AI-схема не прошла проверку читаемости")

    monkeypatch.setattr(main, "art_directed_layout", broken)
    monkeypatch.setattr(main, "generate_visuals",
                        lambda *args, **kwargs: calls.append("images"))
    with pytest.raises(ValueError, match="читаемости"):
        main._generate_sync(
            approved_zubrtrail_500(), _png(), None, None, None, [],
            False, True, "gpt-image-2.5-flare", "medium", "Cinematic",
            generation_mode="hybrid",
        )
    assert calls == ["layout"]
    assert not list(tmp_path.glob("*/promo_kit.zip"))


def test_hybrid_exact_svg_from_ai_geometry_and_original_asset_bytes(
        monkeypatch, tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    brief = approved_zubrtrail_500()
    original = _png()
    logo = _png("black")
    drawing = _png("white")
    calls = []

    def art(*args, **kwargs):
        calls.append("art")
        return {**_concept(), "id": "hybrid_sales",
                "palette": {**_concept()["palette"], "accent": "#E31B26"}}

    def backdrops(*args, **kwargs):
        calls.append("backdrops")
        assert kwargs["references"] == [], (
            "Hybrid paid backdrop must not edit or copy a product-bearing reference"
        )
        assert kwargs["hero_regions"]["4x3"] == _safe_layout("4x3", 0)["hero"]
        return {
            fmt: Image.new("RGB", (640, 480), "lightgray")
            for fmt in ("4x3", "9x16")
        }

    monkeypatch.setattr(main, "art_directed_layout", art)
    monkeypatch.setattr(main, "generate_visuals", backdrops)
    monkeypatch.setattr(main, "rasterize_svg", lambda svg: (b"png", b"jpg"))
    output = main._generate_sync(
        brief, original, None, logo, drawing, [_png("red")],
        False, True, "gpt-image-2.5-flare", "medium",
        "Photorealistic industrial scenery", generation_mode="hybrid",
    )
    assert calls == ["art", "backdrops"]
    assert output["generation_mode"] == "hybrid"
    assert output["ai_used"] is True
    assert output["visualization"] is False
    folder = tmp_path / output["job_id"]
    assert (folder / "layout_spec.json").is_file()
    saved = json.loads((folder / "layout_spec.json").read_text())
    assert saved["generation_mode"] == "hybrid"
    assert saved["selected_concept"]["id"] == "hybrid_sales"
    for fmt in ("4x3", "9x16"):
        svg = (folder / f"corel_{fmt}.svg").read_bytes()
        root = ET.fromstring(svg)
        all_text = " ".join(" ".join(el.itertext())
                            for el in root.iter()
                            if el.tag.endswith("text"))
        assert "ZubrTrail 500" in all_text
        assert "44 т" in all_text
        assert "6 527 000" in all_text
        assert "+7 (951) 704-30-42" in all_text
        for name,value in brief["specs"][:8]:
            assert name in all_text and value in all_text, (
                "All 8 published technical facts must appear in full; "
                "never silently shorten a spec", fmt, name, value
            )
        assert "229 998" not in all_text
        assert "Br" not in all_text
        image_ids = [el.get("id", "") for el in root.iter()
                     if el.tag.endswith("image")]
        assert any(i.startswith("original-product-photo") for i in image_ids)
        product_images=[el for el in root.iter()
                        if (el.get("id") or "").startswith("original-product-photo")]
        assert len(product_images)==1
        assert float(product_images[0].get("height"))>320, (
            "The real product must dominate the art rather than be shrunk "
            "by repeated marketing claims"
        )
        assert not any((el.get("id") or "").startswith("ai-hero-claims-panel")
                       for el in root.iter()), "Claims belong in benefits, not over wheels"
        assert "Легче на 2,5 т" in all_text
        assert any(i.startswith("original-logo") for i in image_ids)
        assert any(i.startswith("original-drawing") for i in image_ids)
        assert any(i.startswith("ai-scene") for i in image_ids)
        assert not any(i.startswith("ai-product-bitmap") for i in image_ids)
        assert any(el.get("id", "").startswith("hybrid-header-slash")
                   for el in root.iter())
        assert any(el.get("id", "").startswith("hybrid-benefits-rail")
                   for el in root.iter()), "Approved benefits need cinematic rail"
        assert any(el.get("id", "").startswith("hybrid-economy-red-rail")
                   for el in root.iter()), "Approved ROI needs high-contrast red rail"
    with ZipFile(folder / "promo_kit.zip") as archive:
        contents = archive.namelist()
        assert "corel_4x3.svg" in contents
        assert "corel_9x16.svg" in contents
        assert "layout_spec.json" in contents
        assert "brief.json" in contents
        saved_brief = json.loads(archive.read("brief.json"))
        assert saved_brief["_metadata"]["generation_mode"] == "hybrid"
        assert saved_brief["phones"] == brief["phones"]
