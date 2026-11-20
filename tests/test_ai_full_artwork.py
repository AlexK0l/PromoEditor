"""Primary AI workflow: OpenAI paints all poster artwork, not only scenery."""
import base64
import io
from xml.etree import ElementTree as ET

from PIL import Image

from app import ai_full_artwork_service as service
from app.ai_full_poster import render_ai_full_poster_svg
from app.ai_layout import _safe_layout
from app.approved_presets import approved_zubrtrail_500


def _concept():
    return {
        "id": "hybrid_sales", "name": "Рекламный арт-дизайн",
        "rationale": "Большая техника и выразительная рекламная графика.",
        "scene_prompt": "Strong premium industrial art.",
        "palette": {"background": "#E7EDF4", "foreground": "#172235",
                    "accent": "#E31B26"},
        "layouts": {fmt: _safe_layout(fmt, 0) for fmt in ("4x3", "9x16")},
    }


def _response():
    buff=io.BytesIO()
    Image.new("RGB",(300,200),"white").save(buff,"PNG")
    data=type("Data",(),{"b64_json":base64.b64encode(buff.getvalue()).decode("ascii")})()
    return type("Result",(),{"data":[data]})()


def test_ai_prompts_request_complete_illustrated_ad_not_background_only():
    brief=approved_zubrtrail_500()
    for fmt in ("4x3","9x16"):
        prompt=service._prompt(brief,_concept(),fmt)
        assert "ACTUAL FINISHED VISUAL DESIGN" in prompt
        assert "not just a background generator" in prompt
        assert "all_reserved_regions" in prompt
        assert "No pseudo-text" in prompt
        assert "No watermarks" in prompt
        assert "No digits" in prompt
        assert "source product" not in prompt.lower() or "product" in prompt.lower()
    # Exact model-output coordinate system differs from final crop.
    wide=service._output_box("4x3",{"x":0,"y":0,"w":1000,"h":1000})
    portrait=service._output_box("9x16",{"x":0,"y":0,"w":1000,"h":1000})
    assert 50 < wide["x"] < 60
    assert 75 < portrait["x"] < 85
    assert wide["w"] < 1000
    assert portrait["w"] < 1000


def test_complete_artwork_two_paid_images_and_retry_cache(monkeypatch,tmp_path):
    brief=approved_zubrtrail_500()
    concept=_concept()
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    calls=[]
    class API:
        class Images:
            def generate(self,**kwargs):
                calls.append(kwargs)
                return _response()
        images=Images()
    monkeypatch.setattr(service,"client",lambda: API())
    monkeypatch.setattr(service,"check_paid_capacity",lambda *args: None)
    out=service.generate_complete_artworks(
        brief,concept,consume_cache=False)
    assert len(calls)==2
    assert all("ACTUAL FINISHED VISUAL DESIGN" in call["prompt"]
               for call in calls)
    assert out["4x3"].size==(1440,1080)
    assert out["9x16"].size==(1080,1920)
    second=service.generate_complete_artworks(
        brief,concept,consume_cache=False)
    assert len(calls)==2, "Identical retry must not incur new paid Images calls"
    assert second["4x3"].size==(1440,1080)


def test_full_artwork_exact_text_and_sources_not_drawn_by_algorithm(monkeypatch):
    brief=approved_zubrtrail_500()
    background=Image.new("RGB",(800,600),"white")
    product=Image.new("RGBA",(300,180),"yellow")
    logo=Image.new("RGBA",(90,90),"red")
    for fmt in ("4x3","9x16"):
        svg=render_ai_full_poster_svg(
            brief,fmt,_concept(),artwork=background,hero=product,logo=logo)
        root=ET.fromstring(svg)
        img_ids=[e.get("id","") for e in root.iter()
                 if e.tag.endswith("image")]
        assert len([x for x in img_ids
                    if x.startswith("ai-complete-poster-artwork")])==1
        assert any(x.startswith("original-product-photo") for x in img_ids)
        assert any(x.startswith("original-logo") for x in img_ids)
        ids=[e.get("id","") for e in root.iter()]
        assert not any("hybrid-header-slash" in x for x in ids)
        assert not any("hybrid-benefits-rail" in x for x in ids)
        assert not any("hybrid-economy-red-rail" in x for x in ids)
        text=" ".join(" ".join(e.itertext()) for e in root.iter()
                      if e.tag.endswith("text"))
        assert "ZubrTrail 500" in text
        assert "6 527 000" in text
        assert "+7 (951) 704-30-42" in text
        assert "229 998" not in text
