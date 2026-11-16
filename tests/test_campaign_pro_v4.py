"""PRO v4 factual completeness, readability, raster export, photo contour."""
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image, ImageDraw

from app.render import default_brief
from app.editable_export import create_editable_svg, rasterize_svg

SVG = {"s": "http://www.w3.org/2000/svg"}


def words(root):
    return " ".join(" ".join(n.itertext()) for n in root.findall(".//s:text", SVG))


def named(root, prefix, suffix=None):
    return [n for n in root.iter()
            if n.attrib.get("id", "").startswith(prefix)
            and (suffix is None or n.tag.endswith("}"+suffix))]


@pytest.mark.parametrize("key,size", [
    ("4x3", (1440, 1080)), ("9x16", (1080, 1920))
])
def test_pro_v4_source_facts_preserved_in_both_formats(key, size):
    data = default_brief()
    data["style"] = "reference_pro"
    hero = Image.new("RGBA", (1400, 700), (238, 188, 45, 255))
    svg = create_editable_svg(data, key, hero=hero)
    root = ET.fromstring(svg)
    text = words(root)
    for label, value in data["specs"] + data["dimensions"]:
        assert label.casefold() in text.casefold(), (key,label)
        assert value in text, (key, value)
    for value in data["benefits"] + data["phones"]:
        assert value in text, (key, value)
    assert "229 998" in text
    assert not any("…" in "".join(n.itertext())
                   for n in root.findall(".//s:text", SVG))
    png, jpg = rasterize_svg(svg)
    assert Image.open(io.BytesIO(png)).size == size
    assert Image.open(io.BytesIO(jpg)).size == size


def test_pro_v4_verified_copy_falls_back_only_to_supplied_hero_claims():
    data = default_brief()
    data["style"] = "reference_pro"
    root = ET.fromstring(create_editable_svg(data, "4x3"))
    text = words(root)
    for value in data["hero_claims"]:
        assert value in text
    assert "КЛЮЧЕВЫЕ ТЕЗИСЫ" in text
    assert "ЗА РЕЙС" in text and "ЗА ГОД" in text
    assert "ПОДТВЕРЖДЁННЫЕ ФАКТЫ" not in text


def test_pro_v4_line_art_requires_actual_transparent_product_photo():
    data = default_brief()
    data["style"] = "reference_pro"
    image = Image.new("RGBA", (400, 220), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 41, 370, 154),
                   fill="#FFB526", outline="#292A2B", width=4)
    draw.ellipse((50, 144, 100, 194), fill="#252529")
    draw.ellipse((280, 144, 330, 194), fill="#252529")
    result = create_editable_svg(data, "4x3", hero=image)
    text = words(ET.fromstring(result))
    assert "КОНТУР ПО ФОТО" in text
    assert b"pro4-photo-contour-note" in result
    assert b"original-product-photo" in result
    assert "ГАБАРИТНЫЕ РАЗМЕРЫ" in text
    # Opaque photographs do NOT get fake technical blueprints.
    plain = Image.new("RGB", (700, 350), "#F3CC25")
    opaque = create_editable_svg(data, "4x3", hero=plain)
    assert b"pro4-photo-contour-note" not in opaque


def test_pro_v4_big_spec_values_and_benefits_are_not_tiny():
    data = default_brief()
    data["style"] = "reference_pro"
    root = ET.fromstring(create_editable_svg(data, "4x3"))
    assert len(named(root, "pro-spec-card-", "polygon")) == 8
    labels = named(root, "pro-spec-name-", "text")
    values = named(root, "pro-spec-value-", "text")
    assert len(labels) == len(values) == 8
    assert float(values[0].get("font-size")) >= 32
    assert float(labels[0].get("font-size")) >= 18
    benefits = named(root, "pro-benefit-", "text")
    assert len(benefits) == 4
    assert min(float(t.get("font-size")) for t in benefits) >= 19


def test_pro_v4_missing_sections_are_absent_not_fabricated():
    brief = {"style":"reference_pro","model":"TRAIL X",
             "specs":[],"dimensions":[],"benefits":[],
             "hero_claims":[],"proof_points":[],"phones":[],"price":""}
    text = words(ET.fromstring(create_editable_svg(brief, "4x3")))
    assert "ГАБАРИТНЫЕ РАЗМЕРЫ" not in text
    assert "КЛЮЧЕВЫЕ ТЕЗИСЫ" not in text
    assert "44 т" not in text
    assert "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ" in text


def test_pro_v4_long_user_approved_copy_survives():
    data = default_brief()
    data["style"] = "reference_pro"
    data["proof_points"] = [
        "Подтверждённая гарантия при соблюдении условий договора",
        "Отдельное сервисное обслуживание по условиям договора",
        "Наличие документации на все основные комплектующие",
        "Техническая консультация по вопросам эксплуатации",
    ]
    root = ET.fromstring(create_editable_svg(data,"4x3"))
    text = words(root)
    for value in data["proof_points"]:
        assert value in text
    assert all("…" not in "".join(n.itertext())
               for n in named(root,"pro4-proof-statement-","text"))
