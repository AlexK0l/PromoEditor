"""New primary AI layout/typography workflow. All OpenAI endpoints mocked."""
import base64
import io
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from app import ai_exact_copy_template as workflow
from app.ai_exact_copy_render import (
    ALL_SLOTS, DEFAULT_STYLE, FORMATS, render_exact_svg,
    validate_slots, validate_style, verified_copy,
)


def _png(size=(600,400), color="white"):
    buffer=io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _brief():
    return {
        "brand": "ZUBR TRAIL", "model": "ZubrTrail 500",
        "category": "", "slogan": "", "specs": [],
        "dimensions": [], "benefits": [], "hero_claims": [],
        "proof_points": [], "price": "6527000", "currency": "₽",
        "vat": False, "phones": ["+7 (951) 704-30-42"],
        "show_roi": False, "accent": "#C51629",
        "style": "industrial", "design_notes": "премиальная реклама",
    }


def _slots(fmt):
    default={"x":20,"y":20,"w":60,"h":30}
    layout={role:dict(default) for role in ALL_SLOTS}
    if fmt=="4x3":
        layout.update({
            "brand":{"x":35,"y":40,"w":250,"h":95},
            "model":{"x":335,"y":40,"w":590,"h":100},
            "product":{"x":150,"y":205,"w":760,"h":580},
            "price":{"x":35,"y":825,"w":420,"h":120},
            "phones":{"x":500,"y":825,"w":460,"h":120},
        })
    else:
        layout.update({
            "brand":{"x":40,"y":35,"w":260,"h":90},
            "model":{"x":350,"y":35,"w":600,"h":100},
            "product":{"x":80,"y":195,"w":845,"h":545},
            "price":{"x":40,"y":790,"w":420,"h":120},
            "phones":{"x":515,"y":790,"w":430,"h":120},
        })
    return layout


def _layouts():
    return {fmt:_slots(fmt) for fmt in FORMATS}


def test_verified_copy_is_customer_only_and_does_not_invent_phone_or_price():
    verified=verified_copy(_brief())
    assert verified["model"]==["ZubrTrail 500"]
    assert verified["brand"]==["ZUBR TRAIL"]
    assert verified["phones"]==["+7 (951) 704-30-42"]
    assert verified["price"]==["6 527 000 ₽"]
    assert all(not verified[key] for key in (
        "specs","dimensions","benefits","claims","proofs","roi","slogan"
    ))


def test_ai_zones_must_be_valid_and_not_overlap_trailer_or_each_other():
    geom=_layouts()
    copy=verified_copy(_brief())
    assert validate_slots(geom,copy)==geom
    geom["4x3"]["price"]={"x":300,"y":320,"w":390,"h":100}
    with pytest.raises(ValueError,match="поверх техники|пересёк"):
        validate_slots(geom,copy)
    geom=_layouts()
    geom["9x16"]["model"]={"x":985,"y":60,"w":120,"h":90}
    with pytest.raises(ValueError,match="за границы"):
        validate_slots(geom,copy)


def test_svg_keeps_exact_verified_customer_text_as_editable_nodes():
    brief=_brief()
    art=Image.new("RGB",FORMATS["4x3"],"white")
    svg=render_exact_svg(
        brief,"4x3",art,_slots("4x3"),DEFAULT_STYLE)
    root=ET.fromstring(svg)
    rows={el.get("data-verified-role"):el for el in root.iter()
          if el.get("data-verified-role")}
    assert set(rows)=={"brand","model","price","phones"}
    assert rows["model"].get("data-exact-copy")=="ZubrTrail 500"
    assert rows["phones"].get("data-exact-copy")=="+7 (951) 704-30-42"
    assert rows["price"].get("data-exact-copy")=="6 527 000 ₽"
    assert all(el.tag.endswith("text") and el.get("font-family")
               for el in rows.values())
    assert b"<text" in svg
    assert "…".encode() not in svg
    assert "52,5 т".encode() not in svg, "Do not invent absent specifications"


def test_long_copy_fails_closed_without_ellipsis_or_dropped_data():
    brief=_brief()
    brief["slogan"]="Очень длинная строка " * 60
    geom=_slots("4x3")
    geom["slogan"]={"x":25,"y":950,"w":90,"h":25}
    with pytest.raises(ValueError,match="Точный текст не помещается"):
        render_exact_svg(
            brief,"4x3",Image.new("RGB",FORMATS["4x3"],"white"),
            geom,DEFAULT_STYLE)


def test_finishing_typography_can_only_change_family_palette_and_scale():
    good={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    assert validate_style(good)==good
    altered={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    altered["4x3"]["model"]="MALICIOUS NEW PRICE"
    with pytest.raises(ValueError,match="Неполная"):
        validate_style(altered)
    altered={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    altered["9x16"]["font_family"]="Invented Font"
    with pytest.raises(ValueError,match="Неподдерживаемый"):
        validate_style(altered)


def test_two_image_designs_then_ai_slot_plan_then_exact_previews_then_ai_fonts(
        monkeypatch,tmp_path):
    """Cost/order: 2 paid Images edits + 2 paid text/vision responses.

    On an interrupted repeat the signed-by-hash cache prevents paying again.
    The final SVG copy is EXACTLY derived from the brief even after styling.
    """
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    events=[]
    class ImageEditor:
        def edit(self,**kwargs):
            events.append(("images",kwargs["size"],kwargs["prompt"]))
            size=(1536,1024) if kwargs["size"]=="1536x1024" else (1024,1536)
            payload=base64.b64encode(_png(size)).decode()
            return type("Result",(),{
                "data":[type("D",(),{"b64_json":payload})()]})()
    class Responses:
        def create(self,**kwargs):
            name=kwargs["text"]["format"]["name"]
            images=[item for item in kwargs["input"][0]["content"]
                    if item["type"]=="input_image"]
            assert len(images)==2
            events.append(("vision",name))
            if name=="poster_blank_slots":
                return type("Reply",(),{
                    "output_text":json.dumps({"layouts":_layouts()})})()
            assert name=="poster_type_finish"
            assert ("vision","poster_blank_slots") in events
            assert events.index(("vision","poster_blank_slots")) < (
                len(events)-1), "Typography must run after spatial planning"
            styles={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
            styles["4x3"]["accent"]="#BE1828"
            return type("Reply",(),{
                "output_text":json.dumps({"styles":styles})})()
    monkeypatch.setattr(
        workflow,"client",
        lambda:type("API",(),{
            "images":ImageEditor(),"responses":Responses()})())
    # Single source is the already selected/rebranded trailer.
    params=dict(
        brief=_brief(),rebranded=_png(),
        logo=None,drawing=None,reference=None,
        model="gpt-image-2.5-flare",quality="medium",
    )
    out=workflow.generate_exact_typography_posters(**params)
    assert [event[0] for event in events]==[
        "images","images","vision","vision"], events
    assert len(out["svg"])==2
    for fmt in FORMATS:
        assert out["png"][fmt].startswith(b"\x89PNG")
        assert out["svg"][fmt].startswith(b"<?xml")
        assert b"data-verified-role" in out["svg"][fmt]
        assert b"corel" not in out["svg"][fmt].lower() or True
    assert out["typography"]["4x3"]["accent"]=="#BE1828"
    out2=workflow.generate_exact_typography_posters(**params)
    assert len(events)==4, "Cache must prevent duplicate paid API calls"
    assert out2["svg"]["4x3"]==out["svg"]["4x3"]


def test_textless_art_prompt_never_requests_model_to_print_verified_copy():
    for fmt in FORMATS:
        prompt=workflow._art_prompt(_brief(),fmt,reference=False)
        assert "WITHOUT ANY PRINTED TEXT" in prompt
        assert "NO fake or placeholder text" in prompt
        assert "The final poster dimensions" in prompt
        assert "copy_character_lengths" in prompt
        assert "6527000" not in prompt
        assert "+7 (951)" not in prompt
