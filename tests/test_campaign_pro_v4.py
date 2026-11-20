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



def test_pro_v4_verified_ribbon_headline_is_not_truncated():
    brief = default_brief()
    brief["style"] = "reference_pro"
    brief["proof_points"] = [
        "Только подтверждённый текст", "Подтверждено документом"
    ]
    root = ET.fromstring(create_editable_svg(brief, "4x3"))
    titles = named(root, "pro4-trust-title-text", "text")
    assert len(titles) == 1
    caption = "".join(titles[0].itertext())
    assert "…" not in caption
    assert caption == "ПОДТВЕРЖДЕНО"


def test_pro_v5_photo_is_primary_and_fictional_silos_are_gone():
    """Fallback background should not pretend to be a verified grain terminal."""
    data = default_brief()
    data["style"] = "reference_pro"
    hero = Image.new("RGBA", (1400, 680), (236, 180, 36, 255))
    root = ET.fromstring(create_editable_svg(data, "4x3", hero=hero))
    assert named(root, "pro5-studio-background", "rect")
    assert named(root, "pro5-stage-floor", "polygon")
    assert not named(root, "pro3-silo-", "rect")
    assert not named(root, "pro3-horizon-", "polygon")
    bitmap = named(root, "original-product-photo", "image")
    assert len(bitmap) == 1
    assert float(bitmap[0].attrib["width"]) >= 900


def test_pro_v5_roi_metrics_share_a_single_readable_row():
    data = default_brief()
    data["style"] = "reference_pro"
    root = ET.fromstring(create_editable_svg(data, "4x3"))
    values = named(root, "pro-roi-value-", "text")
    assert len(values) == 4
    assert len({float(node.attrib["y"]) for node in values}) == 1
    assert min(float(node.attrib["font-size"]) for node in values) >= 24
    assert {"142", "240", "34 200", "90 501"}.issubset(
        {"".join(node.itertext()) for node in values})


def test_pro_v5_does_not_invent_photo_background_when_none_uploaded():
    data = default_brief()
    data["style"] = "reference_pro"
    svg = create_editable_svg(data, "4x3")
    root = ET.fromstring(svg)
    assert named(root, "pro5-studio-background", "rect")
    assert not named(root, "pro-ai-background", "image")
    assert not named(root, "ai-product-bitmap", "image")



def _two_projection_sheet():
    """Synthetic 2-view engineering document; no proprietary sample needed."""
    canvas=Image.new("RGB",(1200,900),"white")
    pencil=ImageDraw.Draw(canvas)
    pencil.rectangle((42,22,1140,340),outline="#252525",width=3)
    for xx in range(65,1125,28):
        pencil.line((xx,40,xx,338),fill="#313131",width=2)
    for yy in (123,173,223,273):
        pencil.line((42,yy,1140,yy),fill="#373737",width=2)
    pencil.rectangle((490,550,715,845),outline="#333333",width=3)
    for xx in range(510,700,24):
        pencil.line((xx,560,xx,825),fill="#333333",width=2)
    return canvas


def test_two_projection_drawing_is_cropped_to_source_side_elevation():
    """A tall side+rear sheet should not shrink to the size of a thumbnail."""
    from app.campaign_pro_v4 import _side_elevation
    original=_two_projection_sheet()
    cropped,detected=_side_elevation(original)
    assert detected is True
    assert cropped.width/cropped.height > 2.9
    assert cropped.height <= original.height*.38
    assert original.size==(1200,900)  # source unchanged

    brief=default_brief()
    brief["style"]="reference_pro"
    detail=Image.new("RGB",(530,410),"#efb324")
    result=create_editable_svg(brief,"4x3",drawing=original,detail=detail)
    root=ET.fromstring(result)
    assert named(root,"pro6-projection-label","text")
    technical=named(root,"original-drawing","image")
    assert len(technical)==1
    assert named(root,"detail-photo","image")
    assert named(root,"pro6-technical-stage","rect")
    for label,value in brief["dimensions"]:
        assert value in words(root),(label,value)

    # The embedded drawing must hold the actual wide PROFILE crop, not
    # the full side+rear sheet squashed into a tiny aspect ratio.
    import base64
    href=technical[0].get("{http://www.w3.org/1999/xlink}href")
    cropped_png=base64.b64decode(href.split(",",1)[1])
    with Image.open(io.BytesIO(cropped_png)) as img:
        assert img.width/img.height>2.9
    assert float(technical[0].get("width"))>400
    assert float(technical[0].get("height"))>=105
    png,_=rasterize_svg(result)
    assert Image.open(io.BytesIO(png)).size==(1440,1080)


def test_drawing_without_second_projection_is_not_arbitrarily_cropped():
    from app.campaign_pro_v4 import _side_elevation
    tall=Image.new("RGB",(1000,800),"white")
    pencil=ImageDraw.Draw(tall)
    # Single-view geometry spanning most of both upper and lower rows.
    for yy in range(10,780,44):
        pencil.line((40,yy,960,yy),fill="#181818",width=3)
    chosen,cropped=_side_elevation(tall)
    assert cropped is False
    assert chosen.size==tall.size
    result=create_editable_svg(
        {**default_brief(),"style":"reference_pro"},
        "4x3",drawing=tall)
    root=ET.fromstring(result)
    assert len(named(root,"original-drawing","image"))==1
    assert not named(root,"pro6-projection-label","text")


def test_pro6_full_original_data_survives_when_drawing_is_present():
    data={**default_brief(),"style":"reference_pro"}
    original=_two_projection_sheet()
    result=create_editable_svg(data,"4x3",drawing=original)
    root=ET.fromstring(result)
    all_words=words(root)
    for label,value in data["specs"]+data["dimensions"]:
        assert value in all_words, (label,value)
    assert "БОКОВОЙ ВИД" in all_words
    for text in root.findall(".//s:text",SVG):
        assert "…" not in "".join(text.itertext()), text.get("id")



def test_dimension_labels_do_not_overlap_values():
    from app.editable_export import _font
    data={**default_brief(),"style":"reference_pro"}
    root=ET.fromstring(create_editable_svg(
        data,"4x3",drawing=_two_projection_sheet()))
    names=named(root,"pro-dimension-name-","text")
    values=named(root,"pro-dimension-value-","text")
    assert len(names)==len(values)==3
    for label,value in zip(names,values):
        rendered_label="".join(label.itertext())
        rendered_value="".join(value.itertext())
        label_font=_font(round(float(label.get("font-size"))),True)
        value_font=_font(round(float(value.get("font-size"))),True)
        # Check true glyph advance in the renderer's own DejaVu typeface.
        label_right=float(label.get("x"))+label_font.getlength(rendered_label)
        value_start=float(value.get("x"))
        value_right=value_start+value_font.getlength(rendered_value)
        assert label_right+3 < value_start,(
            rendered_label,label_right,rendered_value,value_start)
        assert value_right < 934, (rendered_value,value_right)
        assert "…" not in rendered_label+rendered_value



def test_approved_rear_height_label_is_complete_in_landscape():
    """The real four-row ZubrTrail layout must not show 'ВЫСОТА...'."""
    from app.approved_presets import approved_zubrtrail_500
    brief = approved_zubrtrail_500()
    root = ET.fromstring(create_editable_svg(
        brief, "4x3", drawing=_two_projection_sheet()))
    labels = named(root, "pro-dimension-name-", "text")
    assert len(labels) == 4
    captions = ["".join(n.itertext()) for n in labels]
    assert "ВЫСОТА ЗАДНЕЙ ЧАСТИ" in captions
    assert not any("…" in caption for caption in captions)
    assert all(len(list(node)) <= 2 for node in labels)
