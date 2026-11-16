"""Reference PRO visual contract: only real brief data, both sizes, editable SVG."""
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from app.editable_export import create_editable_svg, rasterize_svg
from app.main import _normalize

SVG = {"s": "http://www.w3.org/2000/svg"}
XLINK = "{http://www.w3.org/1999/xlink}href"


def brief():
    return {
        "style": "reference_pro",
        "accent": "#E31B26",
        "brand": "TEST INDUSTRIAL",
        "category": "Самосвальный полуприцеп",
        "model": "PRO 118",
        "slogan": "Проверенная конструкция для перевозок",
        "specs": [
            ["Объём кузова", "34 м³"],
            ["Грузоподъёмность", "41 т"],
            ["Полная масса", "51 т"],
            ["Собственный вес", "9,4 т"],
            ["Оси", "3 оси"],
            ["Тормоза", "Дисковые"],
            ["Дополнительная опция", "По запросу"]
        ],
        "dimensions": [["Длина", "10 440 мм"], ["Ширина", "2 550 мм"]],
        "benefits": ["Прочная конструкция", "Удобная разгрузка",
                     "Раздельные компоненты", "Сервисная поддержка"],
        "hero_claims": ["Подтверждено документом"],
        "price": "4648000", "currency": "Br", "vat": True,
        "phones": ["+375 (00) 123-45-67"]
    }


def words(root):
    return " ".join("".join(n.itertext()) for n in root.findall(".//s:text", SVG))


@pytest.mark.parametrize("format_key,dimensions", [
    ("4x3", (1440, 1080)), ("9x16", (1080, 1920))
])
def test_reference_pro_editable_svg_and_rasters(format_key, dimensions):
    img = Image.new("RGB", (1600, 900), "#d6aa28")
    logo = Image.new("RGBA", (200, 100), (25, 25, 25, 255))
    svg = create_editable_svg(brief(), format_key, hero=img, logo=logo)
    root = ET.fromstring(svg)
    assert root.attrib["viewBox"] == f"0 0 {dimensions[0]} {dimensions[1]}"
    text = words(root)
    for fact in ("PRO 118", "34 м³", "41 т", "10 440 мм",
                 "Прочная конструкция", "4 648 000", "+375 (00) 123-45-67"):
        assert fact in text
    assert "pro-header" in svg.decode()
    assert "pro-spec-card" in svg.decode()
    assert "pro-benefits-title" in svg.decode()
    assert "pro-cta" in svg.decode()
    assert "original-product-photo" in svg.decode()
    assert "original-logo" in svg.decode()
    assert not root.findall(".//s:script", SVG)
    bitmaps = root.findall(".//s:image", SVG)
    assert len(bitmaps) == 2
    assert all(node.attrib[XLINK].startswith("data:image/png;base64,")
               for node in bitmaps)
    png, jpg = rasterize_svg(svg)
    assert Image.open(io.BytesIO(png)).size == dimensions
    assert Image.open(io.BytesIO(jpg)).size == dimensions


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_sparse_no_fabricated_facts(format_key):
    data = {
        "style": "reference_pro", "model": "TEST 50",
        "brand": "TEST", "category": "Полуприцеп",
        "specs": [], "dimensions": [], "benefits": [], "phones": [],
        "price": "", "hero_claims": []
    }
    svg = create_editable_svg(data, format_key)
    text = words(ET.fromstring(svg))
    assert "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ" in text
    assert "ГАБАРИТ" not in text
    assert "м³" not in text
    assert "по запросу" not in text.lower().replace("запросите предложение", "")
    assert "pro-spec-card" not in svg.decode()
    assert "pro-dimensions-title" not in svg.decode()
    assert "pro-benefits-title" not in svg.decode()


def test_pro_style_is_accepted_and_other_styles_unchanged():
    clean = _normalize({"model":"PRO 118","style":"reference_pro"})
    assert clean["style"] == "reference_pro"
    old = create_editable_svg({"model":"Old","style":"industrial"}, "4x3")
    pro = create_editable_svg({"model":"New","style":"reference_pro"}, "4x3")
    assert b"campaign-header" in old
    assert b"pro-header" in pro
    assert b"pro-header" not in old


def test_pro_user_photos_and_drawings_keep_individual_raster_layers():
    im = Image.new("RGB", (600, 400), "#777777")
    result = create_editable_svg(
        {**brief(), "proof_points": ["Гарантия подтверждена"]},
        "4x3", hero=im, detail=im, drawing=im)
    root = ET.fromstring(result)
    images = root.findall(".//s:image", SVG)
    ids = [im.attrib["id"] for im in images]
    assert len(images) == 3
    assert len(ids) == len(set(ids))
    assert any("original-drawing" in ident for ident in ids)
    assert "Гарантия подтверждена" in words(root)
