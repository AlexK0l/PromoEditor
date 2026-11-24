"""A successful paid ZIP can be recomposed locally with zero AI calls."""
import io
import json
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw

from app.ai_exact_copy_render import DEFAULT_STYLE, FORMATS
from scripts.recompose_paid_zip import recompose


def _png(dims):
    out=io.BytesIO()
    Image.new("RGB",dims,"#121923").save(out,format="PNG")
    return out.getvalue()


def _brief():
    return {
        "brand":"ZUBR TRAIL","model":"ZubrTrail 500",
        "category":"ПОЛУПРИЦЕП-ЗЕРНОВОЗ",
        "specs":[["Грузоподъёмность","44 т"],
                 ["Объём кузова","55 м³"],["Собственный вес","8,3 т"]],
        "dimensions":[["Длина","12 360 мм"],["Ширина","2 550 мм"]],
        "hero_claims":["Легче на 2,5 т"],
        "benefits":[],"proof_points":[],"slogan":"",
        "phones":["+7 (951) 704-30-42","+7 (951) 704-29-95"],
        "price":"6527000","currency":"₽","vat":True,
        "accent":"#E31B26","style":"reference_pro","show_roi":False,
    }


def _drawing():
    im=Image.new("RGB",(900,540),"white")
    ImageDraw.Draw(im).rectangle((100,90,810,430),outline="black",width=5)
    out=io.BytesIO()
    im.save(out,format="JPEG")
    return out.getvalue()


def test_paid_art_is_reused_verbatim_with_integrated_vector_technical_copy(
        tmp_path,monkeypatch):
    from app import ai_exact_copy_template
    monkeypatch.setattr(
        ai_exact_copy_template,"client",
        lambda: (_ for _ in ()).throw(
            AssertionError("Recomposing already paid image cannot call OpenAI")),
    )
    orig=tmp_path/"paid.zip"
    rebuilt=tmp_path/"new_review.zip"
    brief=_brief()
    layouts={
        "4x3":{"product":{"x":55,"y":195,"w":650,"h":540}},
        "9x16":{"product":{"x":40,"y":270,"w":760,"h":360}},
    }
    with zipfile.ZipFile(orig,"w",zipfile.ZIP_STORED) as z:
        for name,obj in (
            ("brief.json",brief),
            ("typography_layout.json",layouts),
            ("typography_style.json",{
                fmt:dict(DEFAULT_STYLE) for fmt in FORMATS
            }),
            ("poster_copy.json",{"specs":[],"dimensions":[]}),
        ):
            z.writestr(name,json.dumps(obj,ensure_ascii=False))
        z.writestr("originals/drawing_preview.jpg",_drawing())
        z.writestr("technical_sheet.svg",b"<svg/>")
        for fmt,size in FORMATS.items():
            source=_png(size)
            z.writestr("ai_template_"+fmt+".png",source)
            z.writestr("ai_poster_"+fmt+".png",b"old bad raster")
            z.writestr("corel_"+fmt+".svg",b"old bad SVG")
    recompose(orig,rebuilt)
    assert orig.is_file() and rebuilt.is_file()
    with zipfile.ZipFile(orig) as z:
        assert z.read("ai_poster_4x3.png")==b"old bad raster"
    with zipfile.ZipFile(rebuilt) as z:
        assert z.read("originals/drawing_preview.jpg")==_drawing()
        assert z.read("technical_sheet.svg")==b"<svg/>"
        for fmt in FORMATS:
            assert z.read("ai_template_"+fmt+".png")==_png(FORMATS[fmt])
            assert z.read("ai_poster_"+fmt+".png").startswith(
                bytes([137,80,78,71]))
            root=ET.fromstring(z.read("corel_"+fmt+".svg"))
            assert len([node for node in root.iter()
                        if node.get("data-source")
                        =="original-customer-drawing"])==1
            assert len([node for node in root.iter()
                        if node.get("data-verified-role")=="specs"])==3
            assert len([node for node in root.iter()
                        if node.get("data-verified-role")=="dimensions"])==2
            assert len([node for node in root.iter()
                        if node.get("data-verified-role")=="price"])==1
        copy=json.loads(z.read("poster_copy.json"))
        assert len(copy["specs"])==3
        assert len(copy["dimensions"])==2


def test_existing_or_same_output_is_never_overwritten(tmp_path):
    path=tmp_path/"source.zip"
    path.write_bytes(b"source bytes")
    try:
        recompose(path,path)
    except ValueError:
        pass
    else:
        raise AssertionError("Must not overwrite paid archive")
    assert path.read_bytes()==b"source bytes"
