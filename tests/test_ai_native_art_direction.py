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



def test_reference_pro_without_actual_uploaded_example_is_rejected_before_paid_ai(
        monkeypatch,tmp_path):
    """The latest paid customer ZIP had no originals/style_reference file.

    Images shown in a ChatGPT conversation are not automatically uploaded
    into the PromoEditor web form. Prevent another paid, unguided art run.
    """
    import json
    from fastapi.testclient import TestClient
    from app import main
    from app.render import default_brief

    brief=default_brief()
    brief["style"]="reference_pro"
    monkeypatch.setenv("OPENAI_API_KEY","dummy-not-network")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    def forbidden(*args,**kwargs):
        raise AssertionError("Paid image/ranking called before style validation")
    monkeypatch.setattr(main,"_full_posters_sync",forbidden)
    monkeypatch.setattr(main,"analyze_project",forbidden)
    image=_png(420,270,"#FFDD00")
    with TestClient(main.app) as client:
        result=client.post("/api/generate",data={
            "payload":json.dumps(brief,ensure_ascii=False),
            "generation_mode":"hybrid","use_openai":"true",
        },files={"hero":("trailer.png",image,"image/png")})
    assert result.status_code==400,result.text
    assert "Рекламный PRO" in result.text
    assert "эталон" in result.text
    assert "Платные запросы не запускались" in result.text


def test_customer_reference_pro_describes_editorial_campaign_not_template():
    for fmt in ("4x3","9x16"):
        direction=reference_style_direction(fmt)
        assert "auto-filled report" in direction
        assert "identical rectangle" in direction
        assert ("coordinate layout" in direction.lower()
                or "ui panels" in direction.lower())
        assert "cinematic" in direction.lower() or "professional" in direction
        assert "central aspect-safe framing" in direction
