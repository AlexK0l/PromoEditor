"""Art-direction regression tests: real silhouette occupancy, no layout collisions.

These use synthetic source files. The customer's source photos and engineering
drawing are used only for local visual QA and are not committed to the repo.
"""
import base64
import hashlib
import io
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

from app.campaign_pro_v4 import _tight_product_photo
from app.editable_export import create_editable_svg, rasterize_svg
from app.render import default_brief

XLINK="{http://www.w3.org/1999/xlink}href"
SVG={"s":"http://www.w3.org/2000/svg"}


def _by_id(root, prefix):
    return next(el for el in root.iter() if el.get("id","").startswith(prefix))


def _alpha_rendered_width(el):
    payload=base64.b64decode(el.get(XLINK).split(",",1)[1])
    with Image.open(io.BytesIO(payload)) as bitmap:
        box=bitmap.convert("RGBA").getchannel("A").getbbox()
        assert box is not None
        w,h=bitmap.size
    screen_w=float(el.get("width"))
    screen_h=float(el.get("height"))
    scale=min(screen_w/w,screen_h/h)
    return (box[2]-box[0])*scale


def _padded_source():
    product=Image.new("RGBA",(1600,1000),(0,0,0,0))
    canvas=ImageDraw.Draw(product)
    canvas.rectangle((205,190,1395,820),fill=(244,186,31,255))
    canvas.line((215,788,1300,788),fill=(37,39,41,255),width=18)
    return product


def test_pro_real_vehicle_is_not_shrunk_by_empty_alpha_margins():
    product=_padded_source()
    original=product.tobytes()
    crop=_tight_product_photo(product)
    assert crop.size[0] < product.width
    assert crop.size[1] < product.height
    assert product.tobytes() == original

    brief=default_brief()
    brief["style"]="reference_pro"
    svg=create_editable_svg(brief,"4x3",hero=product)
    root=ET.fromstring(svg)
    hero=_by_id(root,"original-product-photo")
    stage=_by_id(root,"pro5-studio-background")
    dim=_by_id(root,"pro3-dim-stage")
    visible=_alpha_rendered_width(hero)
    # The alpha silhouette (not just the oversized SVG image box) must
    # dominate over 60% of the 944px stage for this wide product source.
    assert visible > 600,visible
    assert float(stage.get("y")) == 148
    assert float(stage.get("height")) >= 370
    assert float(dim.get("height")) >= 200
    assert float(stage.get("y"))+float(stage.get("height")) <= float(dim.get("y"))
    assert float(dim.get("y"))+float(dim.get("height")) <= 730

    png,_=rasterize_svg(svg)
    with Image.open(io.BytesIO(png)) as rendered:
        assert rendered.size == (1440,1080)


def test_opaque_product_sources_are_not_cut_or_distorted():
    source=Image.new("RGB",(1600,1000),"#d4a323")
    result=_tight_product_photo(source)
    assert result.size==source.size


def test_engineering_view_label_is_above_the_bitmap():
    brief=default_brief()
    brief["style"]="reference_pro"
    drawing=Image.new("RGB",(1200,900),"white")
    pen=ImageDraw.Draw(drawing)
    pen.rectangle((42,22,1140,340),outline="black",width=3)
    for x in range(65,1125,28):
        pen.line((x,40,x,338),fill="#222222",width=2)
    for y in (123,173,223,273):
        pen.line((42,y,1140,y),fill="#333333",width=2)
    pen.rectangle((490,550,715,845),outline="black",width=3)
    root=ET.fromstring(create_editable_svg(brief,"4x3",drawing=drawing))
    label=_by_id(root,"pro6-projection-label")
    bitmap=_by_id(root,"original-drawing")
    assert "БОКОВОЙ ВИД" in "".join(label.itertext())
    # Baseline ends above the bitmap, so no lettering obscures source lines.
    assert float(label.get("y"))+3 < float(bitmap.get("y"))
    for key,value in brief["dimensions"]:
        assert value in " ".join(t.text or "" for t in root.findall(".//s:tspan",SVG))
