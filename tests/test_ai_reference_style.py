"""Customer's actual 4:3 + 9:16 reference style acceptance regression.

The reference is a high-information ZubrTrail poster: logo, full product,
photo inset, ALL 10 TTH, ALL 7 dimension entries and original drawing,
marketing statements, real ROI, clear price and exact contacts INSIDE BOTH
ads. CI generates images with synthetic source material, NEVER paid AI.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import cairosvg
import pytest
from PIL import Image

from app.ai_exact_copy_render import DEFAULT_STYLE, FORMATS, verified_copy
from app.ai_reference_render import (
    render_reference_svg, reference_poster_copy, _roi_data,
)


def _brief():
    return {
        "brand":"ZUBR TRAIL",
        "model":"ZubrTrail 500",
        "category":"ПОЛУПРИЦЕП-ЗЕРНОВОЗ",
        "slogan":"Алюминиевый зерновоз, который везёт больше в каждом рейсе",
        "specs":[
            ["Грузоподъёмность","44 т"],["Полная масса","52,5 т"],
            ["Собственный вес","8,3 т"],["Объём кузова","55 м³"],
            ["Кузов","Высокопрочный алюминиевый сплав"],
            ["Оси","4 оси SAF Intra CD, нагрузка 9 т"],
            ["Тормоза","Дисковые"],["Тормозная система","WABCO TEBS-E"],
            ["Колёса","Легкосплавные литые диски"],
            ["Гидроцилиндр","ATLANT, до 250 бар"],
        ],
        "dimensions":[
            ["Длина","12 360 мм"],["Ширина","2 550 мм"],
            ["Высота","до 3 650 мм"],
            ["Высота задней части","3 500 мм"],
            ["Высота ССУ","1 150 мм"],
            ["Межосевое расстояние","1 310 × 3 мм"],
            ["Колея задней тележки","2 040 мм"],
        ],
        "hero_claims":[
            "Легче на 2,5 т","Больше полезной нагрузки",
            "Не боится коррозии","Выше доходность рейсов",
        ],
        "proof_points":[
            "На 2,5 т легче стального аналога",
            "На 2,5 т больше полезной нагрузки в каждом рейсе",
            "За 5 лет дополнительная выручка: 5 400 000 ₽",
            "Итоговый эффект: +3 115 550 ₽; окупаемость ≈ 2,12 года",
        ],
        "benefits":[
            "Высокопрочный алюминиевый сплав для тяжёлой зерновой логистики",
            "Проверенные компоненты SAF, WABCO и ATLANT",
            "4 оси по 9 т и дисковые тормоза",
            "Меньше коррозии и ниже собственный вес",
            "Больше полезной нагрузки и рентабельность",
            "Поддержка клиента и профессиональный расчёт выгоды под маршрут",
        ],
        "price":"6527000","currency":"₽","vat":True,
        "phones":["+7 (951) 704-30-42","+7 (951) 704-29-95"],
        "roi":{
            "extra_payload":"2.5","distance":"300","rate":"6",
            "trips":"240","years":"5","baseline_price":"4242550",
        },
        "show_roi":True,
        "accent":"#E31B26","style":"reference_pro",
    }


def _img(size=(1200,800),color="#E8EBF0"):
    buf=io.BytesIO()
    with Image.new("RGB",size,color) as im:
        im.save(buf,format="PNG")
    return buf.getvalue()


def _root(fmt, *, with_all_assets=True):
    d=_brief()
    with Image.new("RGB",FORMATS[fmt],"#EFF3F8") as art:
        svg=render_reference_svg(
            d,fmt,art,{},DEFAULT_STYLE,
            hero=_img() if with_all_assets else None,
            detail=_img((1100,620),"#DDE4F0") if with_all_assets else None,
            drawing=_img((920,600),"white") if with_all_assets else None,
            logo=_img((450,370),"white") if with_all_assets else None,
            copy_override=reference_poster_copy(
                d,drawing=with_all_assets,
            ),
        )
    return ET.fromstring(svg),svg


@pytest.mark.parametrize("fmt",["4x3","9x16"])
def test_reference_ad_prints_all_specs_dimensions_roi_and_business_copy(fmt):
    root,svg=_root(fmt)
    groups=[el for el in root.iter() if el.get("data-verified-role")]
    roles={}
    for node in groups:
        roles.setdefault(node.get("data-verified-role"),[]).append(
            node.get("data-exact-copy"))
    full=verified_copy(_brief())
    assert roles["specs"]==full["specs"], "All TEN specs must be on the ad"
    assert roles["dimensions"]==full["dimensions"], "ALL SEVEN measurements on ad"
    assert roles["claims"]==full["claims"][:4]
    assert roles["proofs"]==full["proofs"][:4]
    assert roles["benefits"]==full["benefits"][:6]
    assert roles["price"]==full["price"]
    assert roles["phones"]==full["phones"]
    assert roles["model"]==full["model"]
    assert roles["category"]==full["category"]
    assert roles["slogan"]==full["slogan"]
    roi=[lab+": "+val for lab,val in _roi_data(_brief())]
    assert roles["roi"]==roi
    assert len(roi)>=6
    assert all("None" not in (x or "") for xs in roles.values() for x in xs)
    assert b"..." not in svg, "No fake abbreviated technical facts"
    assert b"data-source" in svg
    sources=[node.get("data-source") for node in root.iter()
             if node.get("data-source")]
    assert "original-customer-drawing" in sources
    assert "original-customer-logo" in sources
    assert "rebranded-customer-product" in sources
    # Printed texts must remain independently editable SVG text.
    for node in groups:
        if node.get("data-verified-role") in ("specs","dimensions","roi"):
            assert node.tag.endswith("g")
            assert any(ch.tag.endswith("text") for ch in node.iter())
        else:
            assert node.tag.endswith("text")
    # Actual rasterization, not just well-formed XML.
    png=cairosvg.svg2png(bytestring=svg,output_width=480)
    with Image.open(io.BytesIO(png)) as img:
        assert img.size==(480,round(FORMATS[fmt][1]*480/FORMATS[fmt][0]))


def test_portrait_and_landscape_are_distinct_information_compositions():
    wide,_=_root("4x3")
    tall,_=_root("9x16")
    def rect(root,ident):
        return next(el for el in root.iter() if ident in el.get("id",""))
    assert float(rect(wide,"ref-original-drawing-wide").get("y"))<700
    assert float(rect(tall,"ref-original-drawing-tall").get("y"))>700
    assert float(rect(wide,"ref-inset-wide").get("y"))<400
    assert float(rect(tall,"ref-inset-tall").get("y"))>400
    wide_price=next(el for el in wide.iter()
                    if el.get("data-verified-role")=="price")
    tall_price=next(el for el in tall.iter()
                    if el.get("data-verified-role")=="price")
    assert float(wide_price.get("y"))<1050
    assert float(tall_price.get("y"))>1700


def test_no_roi_inputs_means_no_invented_economics():
    b=_brief()
    b["roi"]={}
    assert _roi_data(b)==[]
    assert reference_poster_copy(b,drawing=True)["roi"]==[]


def test_poster_fails_closed_instead_of_truncating_excess_specs():
    b=_brief()
    b["specs"].append(["Extra approved line","Real user text"])
    with pytest.raises(ValueError,match="10 ТТХ"):
        reference_poster_copy(b,drawing=True)
