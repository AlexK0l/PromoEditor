"""Visual-layout regression: editorial 4:3 and *independent* portrait 9:16.

This exercises the customer's reported failure: random white type on dark
round-box overlays, disconnected original engineering drawing, and a vertical
poster resembling a cropped landscape with fake icon rows. No paid AI.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import cairosvg
import pytest
from PIL import Image, ImageDraw

from app.ai_integrated_render import (
    _palette, _contrast, render_integrated_svg,
)
from app.ai_exact_copy_render import DEFAULT_STYLE, FORMATS, poster_copy
from app.ai_exact_copy_template import _integrated_layout_copy


def _brief():
    return {
        "brand":"ZUBR TRAIL","model":"ZubrTrail 500",
        "category":"ПОЛУПРИЦЕП-ЗЕРНОВОЗ",
        "slogan":"Премиальный зерновоз для тяжёлых рейсов",
        "specs":[
            ["Грузоподъёмность","44 т"],
            ["Объём кузова","55 м³"],
            ["Собственный вес","8,3 т"],
            ["Оси","4 оси SAF Intra"],
        ],
        "dimensions":[
            ["Длина","12 360 мм"],["Ширина","2 550 мм"],
            ["Высота","до 3 650 мм"],
        ],
        "benefits":[],"hero_claims":["Легче на 2,5 т"],
        "phones":["+7 (951) 704-30-42","+7 (951) 704-29-95"],
        "proof_points":[],"show_roi":False,
        "price":"6527000","currency":"₽","vat":True,
        "accent":"#E31B26","style":"reference_pro",
    }


def _drawing():
    image=Image.new("RGB",(920,540),"white")
    pen=ImageDraw.Draw(image)
    pen.rectangle((70,75,850,430),outline="#15212D",width=4)
    for x in (480,570,660,750):
        pen.ellipse((x,385,x+58,443),outline="#15212D",width=4)
    buffer=io.BytesIO()
    image.save(buffer,format="JPEG",quality=85)
    return buffer.getvalue()


def _plans():
    # Product geometry from the real uploaded 2026-11-23 paid ZIP.
    return {
        "4x3":{"product":{"x":55,"y":195,"w":650,"h":540}},
        "9x16":{"product":{"x":40,"y":270,"w":760,"h":360}},
    }


def _markup(fmt,drawing=True):
    art=Image.new("RGB",FORMATS[fmt],color="#16191C")
    style=dict(DEFAULT_STYLE,
               font_family="DejaVu Sans Condensed",
               ink="#F7F8FA",muted="#B8C0C8",accent="#FFD21A")
    layout,approved=_integrated_layout_copy(_plans(),_brief())
    return render_integrated_svg(
        _brief(),fmt,art,layout[fmt],style,
        drawing=_drawing() if drawing else None,
        copy_override=approved,
    )


@pytest.mark.parametrize("fmt",["4x3","9x16"])
def test_both_ads_contain_actual_original_drawing_and_full_key_facts(fmt):
    svg=_markup(fmt)
    root=ET.fromstring(svg)
    copies=[
        (e.get("data-verified-role"),e.get("data-exact-copy"),e)
        for e in root.iter() if e.get("data-verified-role")
    ]
    expected=poster_copy(_brief())
    for role in ("brand","model","category","claims","price"):
        assert [value for r,value,_ in copies if r==role]==expected[role][:1]
    for role in ("specs","dimensions","phones"):
        assert [value for r,value,_ in copies if r==role]==expected[role]
    drawings=[e for e in root.iter()
              if e.get("data-source")=="original-customer-drawing"]
    assert len(drawings)==1
    assert drawings[0].tag.endswith("image")
    assert any("data:image/jpeg;base64," in value
               for value in drawings[0].attrib.values())
    assert "readability-underlay-" not in svg.decode()
    assert "fake-icon" not in svg.decode()
    image_node=[e for e in root.iter()
                if "paid-ai-illustration" in e.get("id","")]
    assert len(image_node)==1
    assert float(image_node[0].get("width"))==FORMATS[fmt][0]
    assert float(image_node[0].get("height"))==FORMATS[fmt][1]
    # The actual customer data remains selectable/editable in SVG.
    for role,value,node in copies:
        assert node.tag.endswith("text")
        assert value
        assert node.get("font-family")=="DejaVu Sans Condensed"
    png=cairosvg.svg2png(bytestring=svg,output_width=540)
    with Image.open(io.BytesIO(png)) as rendered:
        assert rendered.size == (
            540, round(FORMATS[fmt][1]*540/FORMATS[fmt][0])
        )


def test_portrait_reflow_is_not_a_crop_of_landscape_layout():
    wide=ET.fromstring(_markup("4x3"))
    tall=ET.fromstring(_markup("9x16"))
    def one(root,role):
        return next(e for e in root.iter()
                    if e.get("data-verified-role")==role)
    assert float(one(wide,"price").get("y"))<210
    assert float(one(tall,"price").get("y"))>1750
    wide_drawing=next(e for e in wide.iter()
                      if e.get("data-source")=="original-customer-drawing")
    tall_drawing=next(e for e in tall.iter()
                      if e.get("data-source")=="original-customer-drawing")
    assert float(wide_drawing.get("y"))>800
    assert float(tall_drawing.get("y"))>1305
    assert float(one(tall,"model").get("y"))<325
    assert float(one(tall,"specs").get("y"))>1305
    assert "portrait-technical-stage" in ET.tostring(tall,encoding="unicode")
    assert "integrated-tech-panel-wide" in ET.tostring(wide,encoding="unicode")


def test_ai_white_and_yellow_typography_is_rejected_on_light_red_brand():
    style=dict(DEFAULT_STYLE,ink="#F7F8FA",
               accent="#FFD21A",muted="#B8C0C8")
    p=_palette(_brief(),style)
    assert p["accent"]=="#E31B26"  # approved brand red, never random yellow
    assert p["ink"]!="#F7F8FA"
    assert _contrast(p["ink"],"#F7F8FA")>=7
    assert _contrast(p["muted"],"#F7F8FA")>=4.5
    assert "FFFFFF" not in p["ink"]


def test_product_cannot_be_covered_by_bottom_technical_panel():
    for fmt in FORMATS:
        plan=_plans()
        plan[fmt]["product"]={"x":20,"y":140,"w":900,"h":760}
        with pytest.raises(ValueError,match="Прицеп перекрывает"):
            _integrated_layout_copy(plan,_brief())


def test_optional_drawing_absent_does_not_break_full_facts_or_price():
    for fmt in FORMATS:
        root=ET.fromstring(_markup(fmt,drawing=False))
        assert not any(
            e.get("data-source")=="original-customer-drawing"
            for e in root.iter()
        )
        assert len([e for e in root.iter()
                    if e.get("data-verified-role")=="specs"])==3
        assert len([e for e in root.iter()
                    if e.get("data-verified-role")=="price"])==1


def test_integrated_poster_metadata_matches_actual_printed_layers():
    """After the customer's earlier missing-data ZIP, metadata must be honest."""
    from app.ai_integrated_render import integrated_copy
    info=_brief()
    info["show_roi"]=True
    info["hero_claims"]=["Легче на 2,5 т","Больше рейсов"]
    info["proof_points"]=["Гарантия","Одобрено"]
    displayed=integrated_copy(info,drawing=True)
    assert displayed["specs"]==poster_copy(info)["specs"]
    assert displayed["dimensions"]==poster_copy(info)["dimensions"]
    assert displayed["claims"]==["Легче на 2,5 т"]
    assert displayed["slogan"]==[]
    assert displayed["roi"]==[]
    assert displayed["proofs"]==[]
    # The exact editable SVG, not just a JSON claim, contains every
    # advertised field in BOTH formats.
    layout,_=_integrated_layout_copy(_plans(),info,has_drawing=True)
    for fmt in FORMATS:
        with Image.new("RGB",FORMATS[fmt],"#17191C") as photo:
            root=ET.fromstring(render_integrated_svg(
                info,fmt,photo,layout[fmt],dict(DEFAULT_STYLE),
                drawing=_drawing(),copy_override=displayed))
        roles={}
        for el in root.iter():
            role=el.get("data-verified-role")
            if role:
                roles.setdefault(role,[]).append(el.get("data-exact-copy"))
        assert roles["specs"]==displayed["specs"]
        assert roles["dimensions"]==displayed["dimensions"]
        assert roles["claims"]==displayed["claims"]
        assert "roi" not in roles
        assert "slogan" not in roles
