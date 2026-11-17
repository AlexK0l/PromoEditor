"""Premium PRO template: factual and visual regressions for the production engine."""
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image, ImageDraw

from app.editable_export import create_editable_svg, rasterize_svg
from app.render import default_brief

SVG={"s":"http://www.w3.org/2000/svg"}


def _found(root,prefix,tag=None):
    return [el for el in root.iter()
            if el.attrib.get("id","").startswith(prefix)
            and (tag is None or el.tag.endswith("}"+tag))]


def _words(root):
    return " ".join(" ".join(el.itertext())
                    for el in root.findall(".//s:text",SVG))


def _drawing():
    im=Image.new("RGB",(1200,900),"white")
    pen=ImageDraw.Draw(im)
    pen.rectangle((42,22,1140,340),outline="#292929",width=3)
    for xx in range(65,1125,28):
        pen.line((xx,40,xx,338),fill="#313131",width=2)
    for yy in (123,173,223,273):
        pen.line((42,yy,1140,yy),fill="#373737",width=2)
    pen.rectangle((490,550,715,845),outline="#333333",width=3)
    return im


def test_premium_restructures_editable_landscape_around_large_sections():
    sample=default_brief()
    sample["style"]="reference_pro"
    source=Image.new("RGBA",(1280,600),(240,184,40,255))
    secondary=Image.new("RGB",(500,370),"#edd1a3")
    svg=create_editable_svg(sample,"4x3",hero=source,
                            drawing=_drawing(),detail=secondary)
    root=ET.fromstring(svg)
    assert len(_found(root,"pro-spec-card-","polygon"))==8
    picture=_found(root,"original-product-photo","image")[0]
    technical=_found(root,"original-drawing","image")[0]
    details=_found(root,"detail-photo","image")[0]
    assert float(picture.attrib["width"])>=900
    assert float(technical.attrib["width"])>=600
    assert float(technical.attrib["height"])>=140
    assert float(details.attrib["width"])<=180
    dimension_section=_found(root,"pro3-dim-stage","rect")[0]
    assert float(dimension_section.attrib["height"])>=200
    metric_section=_found(root,"pro4-economy-card","rect")[0]
    assert float(metric_section.attrib["width"])>=750
    price_section=_found(root,"pro7-price-ribbon","polygon")[0]
    assert price_section is not None
    for phone in sample["phones"]:
        assert phone in _words(root)
    assert "229 998" in _words(root)
    for key,val in sample["specs"]+sample["dimensions"]:
        assert key.casefold() in _words(root).casefold()
        assert val in _words(root)
    assert len(_found(root,"pro7-phone-","text"))==2
    assert len(root.findall(".//s:image", SVG))==3
    png,jpg=rasterize_svg(svg)
    assert Image.open(io.BytesIO(png)).size==(1440,1080)
    assert Image.open(io.BytesIO(jpg)).size==(1440,1080)


def test_premium_uses_supplied_photographic_backdrop_as_replaceable_bitmap():
    data=default_brief()
    data["style"]="reference_pro"
    product=Image.new("RGBA",(1000,450),(238,183,45,255))
    scene=Image.new("RGB",(1450,700),(95,136,168))
    root=ET.fromstring(create_editable_svg(
        data,"4x3",hero=product,backdrop=scene))
    images=_found(root,"pro-ai-background","image")
    assert len(images)==1
    assert len(_found(root,"original-product-photo","image"))==1
    assert images[0].get("preserveAspectRatio")=="xMidYMid slice"
    assert not _found(root,"ai-product-bitmap","image")
    # ImageGen does not draw validated specs or contacts: SVG overlays do.
    assert len(_found(root,"pro-spec-value-","text"))==8
    assert "+375 (225) 72-01-03" in _words(root)


def test_premium_copies_are_not_hardcoded_to_the_sample():
    values=default_brief()
    values.update({
        "style":"reference_pro","model":"CUSTOM TRK 777",
        "price":"145000","phones":["+375 00 555 44 33"],
        "specs":[["Грузоподъёмность","29 т"],
                 ["Нагрузка на ось","11 т"]],
        "dimensions":[["Длина","11 100"]],
        "benefits":["Проверенный факт один","Проверенный факт два"],
        "hero_claims":[],
        "show_roi":False
    })
    root=ET.fromstring(create_editable_svg(values,"4x3"))
    content=_words(root)
    for phrase in ("CUSTOM TRK 777","29 т","11 т","11 100",
                   "145 000","+375 00 555 44 33"):
        assert phrase in content,phrase
    assert "ZubrTrail 500" not in content
    assert "229 998" not in content
    assert "90 501" not in content
    assert not _found(root,"pro4-economy-card","rect")
    assert len(_found(root,"pro-spec-card-","polygon"))==2


@pytest.mark.parametrize("with_benefits,with_drawing",[
    (False,False),(False,True),(True,False),(True,True)])
def test_premium_omissions_and_dense_blocks_do_not_overlap(
        with_benefits,with_drawing):
    data=default_brief()
    data["style"]="reference_pro"
    if not with_benefits:
        data["benefits"]=[]
    if not with_drawing:
        data["dimensions"]=[]
    drawing=_drawing() if with_drawing else None
    root=ET.fromstring(create_editable_svg(data,"4x3",drawing=drawing))
    if not with_drawing:
        assert not _found(root,"pro3-dim-stage","rect")
    if not with_benefits:
        assert not _found(root,"pro3-benefits-stage","rect")
    # All source facts shown in their independent source text entities.
    text=_words(root)
    for label,value in data["specs"]:
        assert value in text
    for node in root.findall(".//s:text",SVG):
        assert "…" not in "".join(node.itertext()),node.attrib.get("id")
    assert len(_found(root,"pro7-contact-ribbon","polygon"))==1


def test_9x16_keeps_existing_independent_portrait_contract():
    data=default_brief()
    data["style"]="reference_pro"
    output=create_editable_svg(data,"9x16")
    root=ET.fromstring(output)
    assert root.get("viewBox")=="0 0 1080 1920"
    assert not _found(root,"pro7-price-ribbon","polygon")
    assert _found(root,"pro-cta","rect")
    assert "ZubrTrail 500" in _words(root)
