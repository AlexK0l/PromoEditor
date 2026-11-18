"""Portrait PRO regression based on a real VPS-generated test poster.

The technical drawing must remain legible, the red measuring guide must
not cross the values, and 9:16 must not silently drop user hero claims.
"""
import math
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import io
import base64

from app.editable_export import create_editable_svg, _font
from app.render import default_brief

NS={"s":"http://www.w3.org/2000/svg"}


def _parts(root, prefix, tag):
    return [item for item in root.findall(f".//s:{tag}", NS)
            if item.get("id", "").startswith(prefix)]


def _text(root):
    return " ".join(" ".join(x.itertext())
                    for x in root.findall(".//s:text", NS))


def test_portrait_shows_all_submitted_claims_when_no_proof_points():
    data=default_brief()
    data["style"]="reference_pro"
    data["proof_points"]=[]
    portrait=ET.fromstring(create_editable_svg(data,"9x16"))
    landscape=ET.fromstring(create_editable_svg(data,"4x3"))
    for claim in data["hero_claims"]:
        assert claim in _text(portrait)
        assert claim in _text(landscape)
    assert "КЛЮЧЕВЫЕ ТЕЗИСЫ" in _text(portrait)
    assert "ПОДТВЕРЖДЁННЫЕ ФАКТЫ" not in _text(portrait)


def test_four_portrait_dimensions_with_drawing_do_not_cross_rules_or_footer():
    data=default_brief()
    data["style"]="reference_pro"
    data["dimensions"]=[
        ["Длина","12 360 мм"],
        ["Ширина","2 550 мм"],
        ["Высота","до 3 650 мм"],
        ["Колея","2 040 мм"],
    ]
    original=Image.new("RGB",(1200,530),"white")
    root=ET.fromstring(create_editable_svg(data,"9x16",drawing=original))
    cards=_parts(root,"pro-dimension-cell-","rect")
    labels=_parts(root,"pro-dimension-name-","text")
    values=_parts(root,"pro-dimension-value-","text")
    guides=_parts(root,"pro-dimension-measure-","line")
    images=_parts(root,"original-drawing","image")
    assert len(cards)==len(labels)==len(values)==len(guides)==4
    assert len(images)==1
    assert float(images[0].get("width"))>=550
    assert all(text in _text(root) for _,text in data["dimensions"])
    for card,label,value,guide in zip(cards,labels,values,guides):
        left=float(card.get("x"))
        right=left+float(card.get("width"))
        top=float(card.get("y"))
        bottom=top+float(card.get("height"))
        assert float(card.get("height"))>=50
        assert top<=float(label.get("y"))<bottom
        assert top<=float(value.get("y"))<bottom
        for node in (label,value):
            assert "…" not in "".join(node.itertext())
            font=_font(round(float(node.get("font-size"))),True)
            for line in node.findall("s:tspan", NS):
                txt=line.text or ""
                assert float(node.get("x"))+font.getlength(txt) < right-5
            last_baseline=float(node.get("y"))+sum(
                float(part.get("dy","0"))
                for part in node.findall("s:tspan",NS))
            assert last_baseline<=bottom-3
        assert float(label.get("x")) < float(value.get("x"))
        # The decorative line is now a RIGHT-SIDE EDGE, not a horizontal
        # strike-through at the text baseline.
        x1=float(guide.get("x1"));x2=float(guide.get("x2"))
        assert x1==x2
        assert float(value.get("x")) < x1
        assert math.isclose(x1,right-6,abs_tol=.1)
    footer=_parts(root,"pro-cta","rect")[0]
    assert max(float(x.get("y"))+float(x.get("height"))
               for x in cards) < float(footer.get("y"))
    assert "КЛЮЧЕВЫЕ ТЕЗИСЫ" in _text(root)


def _two_view_engineering_sheet():
    """A synthetic side+rear technical sheet, not a copied brand drawing."""
    paper=Image.new("RGB",(1200,900),"white")
    pen=ImageDraw.Draw(paper)
    pen.rectangle((42,22,1140,340),outline="#252525",width=3)
    for x in range(65,1125,28):
        pen.line((x,40,x,338),fill="#313131",width=2)
    for y in (123,173,223,273):
        pen.line((42,y,1140,y),fill="#373737",width=2)
    pen.rectangle((490,550,715,845),outline="#333333",width=3)
    for x in range(510,700,24):
        pen.line((x,560,x,825),fill="#333333",width=2)
    return paper


def test_portrait_enlarges_real_side_projection_from_two_view_drawing():
    brief=default_brief()
    brief["style"]="reference_pro"
    original=_two_view_engineering_sheet()
    root=ET.fromstring(create_editable_svg(brief,"9x16",drawing=original))
    assert _parts(root,"pro3-portrait-side-view-label","text")
    technical=_parts(root,"original-drawing","image")
    assert len(technical)==1
    href=technical[0].get("{http://www.w3.org/1999/xlink}href")
    with Image.open(io.BytesIO(base64.b64decode(href.split(",",1)[1]))) as view:
        assert view.width/view.height>2.9
        placement_width=float(technical[0].get("width"))
        placement_height=float(technical[0].get("height"))
        displayed_width=min(placement_width, placement_height*view.width/view.height)
        assert displayed_width>=495, displayed_width
    assert original.size==(1200,900)  # Source is not cropped or rewritten.
    for key,value in brief["dimensions"]:
        assert value in _text(root),(key,value)


def test_portrait_keeps_uncertain_technical_sheets_complete():
    brief=default_brief()
    brief["style"]="reference_pro"
    # No evidence of a wide side projection: do not crop arbitrary contents.
    sheet=Image.new("RGB",(900,900),"white")
    root=ET.fromstring(create_editable_svg(brief,"9x16",drawing=sheet))
    assert not _parts(root,"pro3-portrait-side-view-label","text")
    image=_parts(root,"original-drawing","image")[0]
    href=image.get("{http://www.w3.org/1999/xlink}href")
    with Image.open(io.BytesIO(base64.b64decode(href.split(",",1)[1]))) as copy:
        assert copy.size==(900,900)
