"""Regression for lost drawing and 10+7 facts in a paid customer ZIP.

The source ZIP had all specs in brief/verified_copy but EMPTY poster_copy
and no drawing SVG layer. These tests use synthetic artwork, never paid AI.
"""
import base64
import io
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

from app.ai_exact_copy_render import poster_copy, verified_copy
from app.ai_technical_sheet import render_technical_sheet
from app import ai_exact_copy_template as pipeline


def _brief():
    return {
        "brand":"ZUBR TRAIL",
        "model":"ZubrTrail 500",
        "category":"ПОЛУПРИЦЕП-ЗЕРНОВОЗ",
        "slogan":"Алюминиевый зерновоз, который везёт больше в каждом рейсе",
        "price":"6527000","currency":"₽","vat":True,
        "specs":[
            ["Грузоподъёмность","44 т"],
            ["Полная масса","52,5 т"],
            ["Собственный вес","8,3 т"],
            ["Объём кузова","55 м³"],
            ["Кузов","Высокопрочный алюминиевый сплав"],
            ["Оси","4 оси SAF Intra CD, нагрузка 9 т"],
            ["Тормоза","Дисковые"],
            ["Тормозная система","WABCO TEBS-E"],
            ["Колёса","Легкосплавные литые диски"],
            ["Гидроцилиндр","ATLANT, до 250 бар"],
        ],
        "dimensions":[
            ["Длина","12 360 мм"],
            ["Ширина","2 550 мм"],
            ["Высота","до 3 650 мм"],
            ["Высота задней части","3 500 мм"],
            ["Высота ССУ","1 150 мм"],
            ["Межосевое расстояние","1 310 × 3 мм"],
            ["Колея задней тележки","2 040 мм"],
        ],
        "hero_claims":["Легче на 2,5 т","Больше полезной нагрузки"],
        "phones":["+7 (951) 704-30-42","+7 (951) 704-29-95"],
        "benefits":[],"proof_points":[],"show_roi":False,
        "accent":"#E31B26","style":"industrial",
    }


def _drawing():
    im=Image.new("RGB",(800,580),"white")
    artist=ImageDraw.Draw(im)
    artist.rectangle((50,80,720,430),outline="black",width=4)
    artist.line((55,477,725,477),fill="black",width=3)
    artist.text((70,500),"12360",fill="black")
    buffer=io.BytesIO()
    im.save(buffer,format="PNG")
    return buffer.getvalue()


def test_customer_sources_always_keep_approved_key_technical_facts():
    copy=poster_copy(_brief())
    full=verified_copy(_brief())
    assert len(full["specs"])==10
    assert len(full["dimensions"])==7
    assert len(copy["specs"])==3
    assert len(copy["dimensions"])==2
    assert "Грузоподъёмность: 44 т" in copy["specs"]
    assert "Объём кузова: 55 м³" in copy["specs"]
    assert "Длина: 12 360 мм" in copy["dimensions"]
    assert "Ширина: 2 550 мм" in copy["dimensions"]


def test_full_technical_page_contains_original_drawing_and_17_exact_fact_layers():
    drawing=_drawing()
    svg=render_technical_sheet(_brief(),drawing)
    root=ET.fromstring(svg)
    facts=[el for el in root.iter()
           if el.get("data-verified-role") in ("specs","dimensions")]
    assert len(facts)==17
    actual=[el.get("data-exact-copy") for el in facts]
    expected=verified_copy(_brief())
    assert actual[:10]==expected["specs"]
    assert actual[10:]==expected["dimensions"]
    assert all(el.tag.endswith("text") for el in facts)
    assert all(not value.endswith("…") for value in actual)
    sources=[el for el in root.iter()
             if el.get("data-source")=="original-customer-drawing"]
    assert len(sources)==1
    assert any("data:image/jpeg;base64," in value
               for value in sources[0].attrib.values())
    assert svg.startswith(b"<?xml")
    # Exported technical sheet must be rasterizable as a real user image.
    import cairosvg
    preview=cairosvg.svg2png(bytestring=svg,output_width=540)
    with Image.open(io.BytesIO(preview)) as image:
        assert image.size==(540,960)
        assert image.getbbox() is not None


def test_paid_image_creation_uses_uploaded_drawing_as_reference(monkeypatch,tmp_path):
    """The original source image is actually passed to Images, not only ZIP."""
    drawing=_drawing()
    image_buffer=io.BytesIO()
    Image.new("RGB",(1536,1024),"white").save(image_buffer,format="PNG")
    from types import SimpleNamespace
    seen=[]
    class Images:
        def edit(self,**kwargs):
            seen.append(kwargs)
            assert len(kwargs["image"])==2
            assert kwargs["image"][0].name=="01_selected_rebranded_trailer.png"
            assert kwargs["image"][1].name=="02_customer_engineering_drawing.png"
            assert "engineering drawing" in kwargs["prompt"]
            dims=(1536,1024) if kwargs["size"]=="1536x1024" else (1024,1536)
            buf=io.BytesIO()
            Image.new("RGB",dims,"white").save(buf,format="PNG")
            return SimpleNamespace(data=[
                SimpleNamespace(b64_json=base64.b64encode(buf.getvalue()).decode())
            ])
    monkeypatch.setattr(
        pipeline,"client",
        lambda:SimpleNamespace(images=Images()),
    )
    result=pipeline.generate_templates(
        _brief(),_drawing(),drawing=drawing,reference=None,
        model="gpt-image-2.5-flare",quality="medium",folder=tmp_path,
    )
    assert len(seen)==2
    for image in result.values():
        image.close()
