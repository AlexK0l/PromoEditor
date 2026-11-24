"""Rejection regression: a beautiful AI poster is NOT an algorithmic SVG stub.

All checks below are network-free. They establish that COMPLETE trusted
source copy and both style references reach the full-image model prompt,
and that missing economic inputs never generate invented financial facts.
No test claims model-created Cyrillic/figures are automatically certified.
"""
from __future__ import annotations

import io
from PIL import Image

from app import ai_poster_service
from app.ai_native_art_direction import (
    approved_full_copy, combine_style_references,
    reference_style_direction,
)
from app.approved_presets import approved_zubrtrail_500


def _png(width,height,color):
    buffer=io.BytesIO()
    with Image.new("RGB",(width,height),color) as image:
        image.save(buffer,format="PNG")
    return buffer.getvalue()


def test_reference_pro_gives_images_model_ALL_customer_facts_not_8_plus_4():
    brief=approved_zubrtrail_500()
    source=approved_full_copy(brief)
    assert len(source["technical_specifications"])==10
    assert len(source["engineering_dimensions"])==7
    assert len(source["customer_benefits"])==6
    assert len(source["selling_claims"])==4
    assert source["phone_numbers"]==brief["phones"]
    assert "6 527 000" in source["price"]
    expected=source["verified_economic_scenario"]
    assert expected is not None
    assert expected["additional_revenue_per_trip"]=="4 500 ₽"
    assert expected["annual_additional_revenue"]=="1 080 000 ₽"
    assert expected["net_economic_effect"]=="3 115 550 ₽"
    assert expected["payback_years"]=="2,12"
    assert source["technical_specifications"][-1][0]==brief["specs"][-1][0]
    assert source["engineering_dimensions"][-1][0]==brief["dimensions"][-1][0]


def test_no_roi_inputs_means_no_invented_numbers():
    brief=approved_zubrtrail_500()
    brief["roi"]={}
    assert approved_full_copy(brief)["verified_economic_scenario"] is None
    prompt=ai_poster_service._prompt(
        brief,"4x3",logo=True,drawing=True,reference=True,
        product_is_rebranded=True,
    )
    assert '"verified_economic_scenario":null' in prompt
    assert "do NOT invent financial return data" in prompt


def test_portrait_and_landscape_have_incompatible_creative_art_briefs():
    brief=approved_zubrtrail_500()
    wide=ai_poster_service._prompt(
        brief,"4x3",logo=True,drawing=True,reference=True,
        product_is_rebranded=True,
    )
    portrait=ai_poster_service._prompt(
        brief,"9x16",logo=True,drawing=True,reference=True,
        product_is_rebranded=True,
    )
    assert wide!=portrait
    assert "LANDSCAPE 4:3" in wide
    assert "PORTRAIT 9:16" in portrait
    for p in (wide,portrait):
        assert "actual" in p.lower() or "REAL" in p
        assert "not a" in p.lower()
        assert "FULL" in p or "complete" in p.lower()
        assert "verified_economic_scenario" in p
        assert "technical_specifications" in p
        assert "engineering_dimensions" in p
        assert "phone_numbers" in p
        assert "No empty template zones" in p
        assert "VISUAL REFERENCES MUST NOT supply facts" in p
        assert all(x[1] in p for x in brief["specs"])
        assert all(x[1] in p for x in brief["dimensions"])
        assert not ("six narrow columns" in p.lower())
    assert "NEVER reflow, crop or squeeze" in reference_style_direction("9x16")
    assert "ONLY" in wide
    assert "OpenAI" in portrait or "IMAGE MODEL" in portrait


def test_both_customer_style_examples_are_transmitted_without_exposing_raw():
    wide=_png(1200,900,"#FBF8F4")
    tall=_png(720,1280,"#F0F3F7")
    board=combine_style_references(wide,[tall])
    assert board is not None
    assert board!=wide and board!=tall
    with Image.open(io.BytesIO(board)) as image:
        assert image.size==(1500,960)
        assert image.mode=="RGB"
    assert combine_style_references(wide,[])==wide
    assert combine_style_references(None,[]) is None



def test_reference_pro_without_example_uses_actual_full_image_pipeline(
        monkeypatch,tmp_path):
    """No required example; all three routes reach mocked Images edits."""
    import base64
    import json
    import time
    import zipfile
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app import main, product_rebrand_service
    from app.render import default_brief

    monkeypatch.setenv("OPENAI_API_KEY","dummy-not-network")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    image=_png(420,270,"#FFDD00")
    calls=[]
    def edit(**options):
        calls.append(options)
        assert len(options["image"]) == 1
        return SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(image).decode("ascii"))])
    api=SimpleNamespace(images=SimpleNamespace(edit=edit))
    monkeypatch.setattr(ai_poster_service,"client",lambda:api)
    monkeypatch.setattr(product_rebrand_service,"client",lambda:api)
    def forbidden(*args,**kwargs):
        raise AssertionError("Full AI mode cannot fall back to an SVG renderer")
    monkeypatch.setattr(main,"_exact_typography_posters_sync",forbidden)
    monkeypatch.setattr(main,"_generate_sync",forbidden)
    with TestClient(main.app) as client:
        for index,route in enumerate(("/api/generate","/api/ai-posters",
                                      "/api/generate/start")):
            brief=default_brief()
            brief["style"]="reference_pro"
            # Unique source data per endpoint, so each exercises both
            # actual poster model calls rather than a cached answer.
            brief["model"]=f"Independent product {index}"
            before=len(calls)
            response=client.post(route,data={
                "payload":json.dumps(brief,ensure_ascii=False),
                "generation_mode":"hybrid","use_openai":"true",
            },files={"hero":("trailer.png",image,"image/png")})
            if route.endswith("/start"):
                assert response.status_code==202,response.text
                status_url=response.json()["status_url"]
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    state=client.get(status_url).json()
                    if state["status"]!="running":
                        break
                    time.sleep(.05)
                assert state["status"]=="complete",state
                result=state["result"]
            else:
                assert response.status_code==200,response.text
                result=response.json()
            assert result["generation_mode"]=="openai_full_poster"
            assert result["raster_only"] is True
            assert result["reference_used"] is False
            assert len(calls)-before==3
            assert [c["size"] for c in calls[-2:]]==["1536x1024","1024x1536"]
            for call in calls[-2:]:
                assert "NO EXAMPLE IMAGE WAS PROVIDED" in call["prompt"]
                assert brief["model"] in call["prompt"]
                assert "ZUBR TRAIL print advertisements" not in call["prompt"]
                assert "yellow accurate four-axle" not in call["prompt"]
            with zipfile.ZipFile(io.BytesIO(client.get(result["zip"]).content)) as z:
                assert "approved_copy.json" in z.namelist()
                assert not any(name.startswith("originals/style_reference") for name in z.namelist())
                assert "native_ai_artwork_4x3.png" in z.namelist()
                assert "native_ai_artwork_9x16.png" in z.namelist()


def test_customer_reference_pro_describes_editorial_campaign_not_template():
    for fmt in ("4x3","9x16"):
        direction=reference_style_direction(fmt)
        assert "auto-filled report" in direction
        assert "identical rectangle" in direction
        assert ("coordinate layout" in direction.lower()
                or "ui panels" in direction.lower())
        assert "cinematic" in direction.lower() or "professional" in direction
        assert "full native canvas" in direction
