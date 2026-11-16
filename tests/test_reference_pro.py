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
    # Each SVG tspan is a visually separate line; preserve its word boundary.
    return " ".join(" ".join(t for t in n.itertext() if t) for n in root.findall(".//s:text", SVG))


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


def test_pro_v2_numeric_units_and_dimension_cards():
    data = {**brief(), "show_roi": True, "roi": {
        "extra_payload": "2.5", "distance": "300", "rate": "0.19",
        "trips": "240", "years": "5", "baseline_price": "149499"}}
    for format_key in ("4x3", "9x16"):
        svg = create_editable_svg(data, format_key)
        root = ET.fromstring(svg)
        text = words(root)
        assert "ЗА РЕЙС, Br" in text
        assert "ЗА ГОД, Br" in text
        assert "БАЛАНС, Br" in text
        assert "10 440 мм" in text
        assert "2 550 мм" in text
        assert "pro-dimension-measure-0" in svg.decode()
        assert "pro-benefit-halo-0" in svg.decode()
        assert "pro-hero-depth-0" in svg.decode()
        assert not root.findall(".//s:script", SVG)


@pytest.mark.parametrize("format_key,expected", [
    ("4x3", (1440, 1080)), ("9x16", (1080, 1920))
])
def test_pro_v2_dense_and_sparse_campaigns(format_key, expected):
    from app.render import default_brief
    dense = default_brief()
    dense["style"] = "reference_pro"
    dense["proof_points"] = [
        "Проверенный документ 1", "Проверенный документ 2",
        "Проверенный документ 3", "Проверенный документ 4"]
    dense["benefits"] += ["Проверенное преимущество 5", "Проверенное преимущество 6"]
    image = Image.new("RGB", (940, 560), "#f3e4c1")
    original_drawing = Image.new("RGB", (1200, 440), "white")
    svg = create_editable_svg(dense, format_key, hero=image,
                              drawing=original_drawing)
    root = ET.fromstring(svg)
    assert root.attrib["viewBox"] == f"0 0 {expected[0]} {expected[1]}"
    assert "Проверенный документ 4" in words(root)
    assert "Проверенное преимущество 6" in words(root)
    assert "original-drawing" in svg.decode()
    assert "pro-spec-value-7" in svg.decode()
    assert "pro-price" in svg.decode()
    # No invented raster background / decorative pseudo-blueprint.
    assert len(root.findall(".//s:image", SVG)) == 2
    png, jpg = rasterize_svg(svg)
    assert Image.open(io.BytesIO(png)).size == expected
    assert Image.open(io.BytesIO(jpg)).size == expected


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_v2_unprovided_dimensions_and_claims_are_absent(format_key):
    minimal = {
        "style": "reference_pro", "model": "TRAIL 50",
        "specs": [["Полезная нагрузка", "20 т"]],
        "dimensions": [], "benefits": [], "proof_points": [],
        "phones": [], "price": "",
    }
    svg = create_editable_svg(minimal, format_key).decode()
    text = words(ET.fromstring(svg))
    assert "Полезная нагрузка" in text
    assert "20 т" in text
    assert "ГАБАРИТ" not in svg
    assert "pro-dimensions-title" not in svg
    assert "pro-proof-panel" not in svg
    assert "pro-benefit-halo" not in svg


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_v2_fact_labels_and_values_do_not_ellipsis(format_key):
    from app.render import default_brief
    sample = default_brief()
    sample["style"] = "reference_pro"
    root = ET.fromstring(create_editable_svg(sample, format_key))
    for element in root.findall(".//s:text", SVG):
        if element.get("id", "").startswith(("pro-spec-value-", "pro-spec-name-")):
            assert "…" not in "".join(element.itertext()), (
                format_key, element.get("id"), list(element.itertext()))


def _shape(root, prefix, tag):
    for el in root.findall(f".//s:{tag}", SVG):
        if el.attrib.get("id","").startswith(prefix):
            return el
    raise AssertionError(f"Missing SVG shape {prefix}")


def _area_iou(expected, actual):
    ex,ey,ew,eh=expected
    ax,ay,aw,ah=actual
    x1=max(ex,ax)
    y1=max(ey,ay)
    x2=min(ex+ew,ax+aw)
    y2=min(ey+eh,ay+ah)
    overlap=max(0,x2-x1)*max(0,y2-y1)
    return overlap/(ew*eh+aw*ah-overlap)


def test_pro_v3_landscape_anchors_match_reference_structure():
    """Geometry benchmark taken from sections of the supplied 1280x960 ref.

    We compare editorial zones, NOT another product's photos, brand or numbers.
    Minor variances are intentional because the product and claims differ.
    """
    from app.render import default_brief
    sample=default_brief()
    sample["style"]="reference_pro"
    sample["proof_points"]=["Подтверждённое условие"]
    svg=create_editable_svg(sample,"4x3")
    root=ET.fromstring(svg)
    assert "pro3-" in svg.decode()
    sections=(
        # expected reference bounding zones normalized to 1440x1080
        ("pro-header", "rect", (0,0,1440,166), .90),
        ("pro3-hero-scene","rect",(0,166,920,405),.80),
        ("pro3-dim-stage","rect",(0,555,920,180),.75),
        ("pro3-benefits-stage","rect",(0,741,1440,142),.77),
        ("pro-cta","rect",(0,968,1440,112),.88),
    )
    for ident,tag,expected,minimum in sections:
        el=_shape(root,ident,tag)
        actual=tuple(float(el.attrib[k]) for k in ("x","y","width","height"))
        assert _area_iou(expected,actual)>=minimum,(ident,actual)
    spec_first=_shape(root,"pro-spec-card-0","polygon")
    assert float(spec_first.attrib["points"].split()[0].split(",")[0])>=930
    assert "ZubrTrail 500" in words(root)
    assert "44 т" in words(root)
    assert "8,3 т" in words(root)


def _pixel_regions(png):
    im=Image.open(io.BytesIO(png)).convert("RGB").resize((144,108))
    regions=((0,16),(17,55),(73,87),(97,108))
    result=[]
    for start,stop in regions:
        colors=[im.getpixel((x,y)) for y in range(start,stop) for x in range(144)]
        red=sum(1 for r,g,b in colors if r>120 and r>g*1.65 and r>b*1.5)
        result.append(red/len(colors))
    return result


def test_pro_v3_poster_has_reference_color_anchors():
    """Upper/lower dramatic red, readable mid band; not a pixel copy."""
    from app.render import default_brief
    sample=default_brief()
    sample["style"]="reference_pro"
    # Avoid accidental product-color matching: use a neutral fixture.
    photo=Image.new("RGBA",(850,390),(232,201,62,255))
    png,_=rasterize_svg(create_editable_svg(sample,"4x3",hero=photo))
    top,hero,benefits,footer=_pixel_regions(png)
    assert top>.45
    assert hero>.045
    assert benefits>.07
    assert footer>.44


def test_pro_v3_missing_sections_never_claim_dimensions_or_warranty():
    clean={"style":"reference_pro","model":"Model X",
           "specs":[["Материал","Сталь"]],
           "dimensions":[],"benefits":[],"proof_points":[],
           "price":"","phones":[]}
    for aspect in ("4x3","9x16"):
        source=create_editable_svg(clean,aspect).decode("utf-8")
        assert "pro-dimensions-title" not in source
        assert "pro-proof-panel" not in source
        assert "ГАРАНТИЯ" not in source
        assert "Сталь" in source


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_v3_default_verified_data_remains_complete(format_key):
    """All eight facts, three dimensions and contact details must be complete."""
    from app.render import default_brief
    data=default_brief()
    data["style"]="reference_pro"
    root=ET.fromstring(create_editable_svg(data,format_key))
    all_text=words(root)
    for key,value in data["specs"]+data["dimensions"]:
        assert key.casefold() in all_text.casefold(),(format_key,key)
        assert str(value) in all_text,(format_key,value)
    for value in data["benefits"]+data["phones"]:
        assert value in all_text,(format_key,value)
    assert "229 998" in all_text
    for node in root.findall(".//s:text", SVG):
        assert "…" not in "".join(node.itertext()), (format_key,node.get("id"))
    # No text or brand is imported from the other advertised trailer.
    assert "ZUBRTRAIL 118" not in all_text


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_v3_long_verified_proof_claims_are_not_cut(format_key):
    from app.render import default_brief
    data=default_brief()
    data["style"]="reference_pro"
    data["proof_points"]=[
        "Подтверждённая гарантия при соблюдении условий договора",
        "Отдельное сервисное обслуживание по условиям договора",
        "Наличие документации на все основные комплектующие",
        "Техническая консультация по вопросам эксплуатации",
    ]
    root=ET.fromstring(create_editable_svg(data,format_key))
    content=words(root)
    for fact in data["proof_points"]:
        assert fact in content,(format_key,fact)
    for element in root.findall(".//s:text",SVG):
        if element.get("id","").startswith("pro3-proof-"):
            assert "…" not in "".join(element.itertext())


@pytest.mark.parametrize("format_key", ["4x3", "9x16"])
def test_pro_v3_dense_text_fits_inside_its_visual_band(format_key):
    from app.render import default_brief
    data=default_brief()
    data["style"]="reference_pro"
    data["benefits"] += [
        "Подтверждённое преимущество номер пять",
        "Подтверждённое преимущество номер шесть"]
    data["proof_points"]=[
        "Подтверждённая гарантия при соблюдении условий договора",
        "Отдельное сервисное обслуживание по условиям договора",
        "Наличие документации на все основные комплектующие",
        "Техническая консультация по вопросам эксплуатации",
    ]
    root=ET.fromstring(create_editable_svg(data,format_key))
    bounds={}
    for shape in root.findall(".//s:rect",SVG):
        ident=shape.get("id","")
        if ident.startswith("pro3-benefits-stage"):
            bounds["benefit"]=float(shape.get("y"))+float(shape.get("height"))
        if ident.startswith("pro-proof-panel"):
            bounds["proof"]=float(shape.get("y"))+float(shape.get("height"))
    assert set(bounds)=={"benefit","proof"}
    for node in root.findall(".//s:text",SVG):
        ident=node.get("id","")
        if ident.startswith("pro-benefit-"):
            lower=bounds["benefit"]
        elif ident.startswith("pro3-proof-") and not "slug" in ident:
            lower=bounds["proof"]
        else:
            continue
        fontsize=float(node.get("font-size"))
        baseline=float(node.get("y"))
        baseline+=sum(float(span.get("dy","0"))
                      for span in node.findall("s:tspan",SVG))
        assert baseline+fontsize*.20<=lower-3,(format_key,ident,baseline,lower)
