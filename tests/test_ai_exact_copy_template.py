"""New primary AI layout/typography workflow. All OpenAI endpoints mocked."""
import base64
import io
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from app import ai_exact_copy_template as workflow
from app.ai_exact_copy_render import (
    ALL_SLOTS, DEFAULT_STYLE, FORMATS, render_exact_svg,
    validate_slots, validate_style, verified_copy, poster_copy,
)
from app.ai_slot_repair import repair_ai_slots



def _png(size=(600,400), color="white"):
    buffer=io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _brief():
    return {
        "brand": "ZUBR TRAIL", "model": "ZubrTrail 500",
        "category": "", "slogan": "", "specs": [],
        "dimensions": [], "benefits": [], "hero_claims": [],
        "proof_points": [], "price": "6527000", "currency": "₽",
        "vat": False, "phones": ["+7 (951) 704-30-42"],
        "show_roi": False, "accent": "#C51629",
        "style": "industrial", "design_notes": "премиальная реклама",
    }


def _slots(fmt):
    default={"x":20,"y":20,"w":60,"h":30}
    layout={role:dict(default) for role in ALL_SLOTS}
    if fmt=="4x3":
        layout.update({
            "brand":{"x":35,"y":40,"w":250,"h":95},
            "model":{"x":335,"y":40,"w":590,"h":100},
            "product":{"x":150,"y":205,"w":760,"h":580},
            "price":{"x":35,"y":825,"w":420,"h":120},
            "phones":{"x":500,"y":825,"w":460,"h":120},
        })
    else:
        layout.update({
            "brand":{"x":40,"y":35,"w":260,"h":90},
            "model":{"x":350,"y":35,"w":600,"h":100},
            "product":{"x":80,"y":195,"w":845,"h":545},
            "price":{"x":40,"y":790,"w":420,"h":120},
            "phones":{"x":515,"y":790,"w":430,"h":120},
        })
    return layout


def _layouts():
    return {fmt:_slots(fmt) for fmt in FORMATS}


def test_verified_copy_is_customer_only_and_does_not_invent_phone_or_price():
    verified=verified_copy(_brief())
    assert verified["model"]==["ZubrTrail 500"]
    assert verified["brand"]==["ZUBR TRAIL"]
    assert verified["phones"]==["+7 (951) 704-30-42"]
    assert verified["price"]==["6 527 000 ₽"]
    assert all(not verified[key] for key in (
        "specs","dimensions","benefits","claims","proofs","roi","slogan"
    ))


def test_ai_zones_must_be_valid_and_not_overlap_trailer_or_each_other():
    geom=_layouts()
    copy=verified_copy(_brief())
    assert validate_slots(geom,copy)==geom
    geom["4x3"]["price"]={"x":300,"y":320,"w":390,"h":100}
    with pytest.raises(ValueError,match="поверх техники|пересёк"):
        validate_slots(geom,copy)
    geom=_layouts()
    geom["9x16"]["model"]={"x":985,"y":60,"w":120,"h":90}
    with pytest.raises(ValueError,match="за границы"):
        validate_slots(geom,copy)




def _overlapping_category_and_benefits():
    """Real 9:16 regression: both roles active, overlapping on the poster."""
    layouts=_layouts()
    # The landscape artwork has its own already-valid active text regions.
    # Repair must leave those untouched when only 9:16 is defective.
    layouts["4x3"]["category"]={"x":40,"y":145,"w":250,"h":45}
    layouts["4x3"]["benefits"]={"x":310,"y":140,"w":610,"h":60}
    portrait=layouts["9x16"]
    # Give AI art a generous empty editorial region between the product
    # and price strip. Only CATEGORY overlaps the longer BENEFITS region.
    portrait["product"]={"x":90,"y":230,"w":820,"h":400}
    portrait["benefits"]={"x":80,"y":650,"w":630,"h":110}
    portrait["category"]={"x":470,"y":680,"w":320,"h":68}
    return layouts


def test_ai_overlap_between_category_and_benefits_9x16_is_repaired_without_template():
    brief=_brief()
    brief["category"]="Самосвальный полуприцеп"
    brief["benefits"]=[
        "Надёжный кузов", "Удобная разгрузка",
    ]
    original=_overlapping_category_and_benefits()
    copy=verified_copy(brief)
    with pytest.raises(ValueError,match="category и benefits"):
        validate_slots(original,copy)
    repaired=repair_ai_slots(original,copy)
    assert validate_slots(repaired,copy)==repaired
    assert repaired["4x3"]==original["4x3"]
    assert repaired["9x16"]["product"]==original["9x16"]["product"]
    assert repaired["9x16"]["benefits"]==original["9x16"]["benefits"]
    assert repaired["9x16"]["category"]!=original["9x16"]["category"]
    assert original["9x16"]["category"]=={
        "x":470,"y":680,"w":320,"h":68}, "Do not mutate the paid AI response"
    svg=render_exact_svg(
        brief,"9x16",Image.new("RGB",FORMATS["9x16"],"white"),
        repaired["9x16"],DEFAULT_STYLE,
    )
    root=ET.fromstring(svg)
    roles={element.get("data-verified-role"):element.get("data-exact-copy")
           for element in root.iter() if element.get("data-verified-role")}
    assert roles["category"]=="Самосвальный полуприцеп"
    assert roles["benefits"]=="Надёжный кузов\nУдобная разгрузка"
    assert roles["model"]=="ZubrTrail 500"


def test_slot_repair_does_not_move_any_valid_ai_zones():
    geom=_layouts()
    copy=verified_copy(_brief())
    assert repair_ai_slots(geom,copy)==geom


def test_paid_raw_layout_survives_invalid_collision_and_retry_requires_no_vision_call(
        monkeypatch,tmp_path):
    """A paid vision answer is cached BEFORE geometric reconciliation."""
    brief=_brief()
    brief["category"]="Самосвальный полуприцеп"
    brief["benefits"]=["Надёжный кузов","Удобная разгрузка"]
    art={fmt:Image.new("RGB",FORMATS[fmt],"white") for fmt in FORMATS}
    calls=[]
    class Responses:
        def create(self,**kwargs):
            calls.append(kwargs["text"]["format"]["name"])
            return type("Result",(),{
                "output_text":json.dumps({
                    "layouts":_overlapping_category_and_benefits()
                }),
            })()
    monkeypatch.setattr(
        workflow,"client",
        lambda:type("API",(),{"responses":Responses()})())
    original_repair=workflow.repair_ai_slots
    def temporary_failure(*args,**kwargs):
        raise ValueError("Временная ошибка проверки геометрии")
    monkeypatch.setattr(workflow,"repair_ai_slots",temporary_failure)
    with pytest.raises(ValueError,match="Временная ошибка"):
        workflow._layout_plan(
            brief,art,has_logo=False,has_drawing=False,folder=tmp_path)
    assert (tmp_path/"layout_raw.json").is_file()
    assert calls==["poster_blank_slots"]
    monkeypatch.setattr(workflow,"repair_ai_slots",original_repair)
    repaired=workflow._layout_plan(
        brief,art,has_logo=False,has_drawing=False,folder=tmp_path)
    assert calls==["poster_blank_slots"], "Do not repay for same layout"
    assert validate_slots(repaired,poster_copy(brief))==repaired


def test_svg_keeps_exact_verified_customer_text_as_editable_nodes():
    brief=_brief()
    art=Image.new("RGB",FORMATS["4x3"],"white")
    svg=render_exact_svg(
        brief,"4x3",art,_slots("4x3"),DEFAULT_STYLE)
    root=ET.fromstring(svg)
    rows={el.get("data-verified-role"):el for el in root.iter()
          if el.get("data-verified-role")}
    assert set(rows)=={"brand","model","price","phones"}
    assert rows["model"].get("data-exact-copy")=="ZubrTrail 500"
    assert rows["phones"].get("data-exact-copy")=="+7 (951) 704-30-42"
    assert rows["price"].get("data-exact-copy")=="6 527 000 ₽"
    assert all(el.tag.endswith("text") and el.get("font-family")
               for el in rows.values())
    assert b"<text" in svg
    assert "…".encode() not in svg
    assert "52,5 т".encode() not in svg, "Do not invent absent specifications"


def test_long_copy_fails_closed_without_ellipsis_or_dropped_data():
    brief=_brief()
    brief["slogan"]="Очень длинная строка " * 60
    geom=_slots("4x3")
    geom["slogan"]={"x":25,"y":950,"w":90,"h":25}
    with pytest.raises(ValueError,match="Точный текст не помещается|Недостаточно места"):
        render_exact_svg(
            brief,"4x3",Image.new("RGB",FORMATS["4x3"],"white"),
            geom,DEFAULT_STYLE)


def test_finishing_typography_can_only_change_family_palette_and_scale():
    good={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    assert validate_style(good)==good
    altered={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    altered["4x3"]["model"]="MALICIOUS NEW PRICE"
    with pytest.raises(ValueError,match="Неполная"):
        validate_style(altered)
    altered={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    altered["9x16"]["font_family"]="Invented Font"
    with pytest.raises(ValueError,match="Неподдерживаемый"):
        validate_style(altered)


def test_two_image_designs_then_ai_slot_plan_then_exact_previews_then_ai_fonts(
        monkeypatch,tmp_path):
    """Cost/order: 2 paid Images edits + 2 paid text/vision responses.

    On an interrupted repeat the signed-by-hash cache prevents paying again.
    The final SVG copy is EXACTLY derived from the brief even after styling.
    """
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    events=[]
    class ImageEditor:
        def edit(self,**kwargs):
            events.append(("images",kwargs["size"],kwargs["prompt"]))
            size=(1536,1024) if kwargs["size"]=="1536x1024" else (1024,1536)
            payload=base64.b64encode(_png(size)).decode()
            return type("Result",(),{
                "data":[type("D",(),{"b64_json":payload})()]})()
    class Responses:
        def create(self,**kwargs):
            name=kwargs["text"]["format"]["name"]
            images=[item for item in kwargs["input"][0]["content"]
                    if item["type"]=="input_image"]
            assert len(images)==2
            events.append(("vision",name))
            if name=="poster_blank_slots":
                return type("Reply",(),{
                    "output_text":json.dumps({"layouts":_layouts()})})()
            assert name=="poster_type_finish"
            assert ("vision","poster_blank_slots") in events
            assert events.index(("vision","poster_blank_slots")) < (
                len(events)-1), "Typography must run after spatial planning"
            styles={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
            styles["4x3"]["accent"]="#BE1828"
            return type("Reply",(),{
                "output_text":json.dumps({"styles":styles})})()
    monkeypatch.setattr(
        workflow,"client",
        lambda:type("API",(),{
            "images":ImageEditor(),"responses":Responses()})())
    # Single source is the already selected/rebranded trailer.
    params=dict(
        brief=_brief(),rebranded=_png(),
        logo=None,drawing=None,reference=None,
        model="gpt-image-2.5-flare",quality="medium",
    )
    out=workflow.generate_exact_typography_posters(**params)
    assert [event[0] for event in events]==[
        "images","images","vision","vision"], events
    assert len(out["svg"])==2
    for fmt in FORMATS:
        assert out["png"][fmt].startswith(b"\x89PNG")
        assert out["svg"][fmt].startswith(b"<?xml")
        assert b"data-verified-role" in out["svg"][fmt]
    assert out["typography"]["4x3"]["accent"]=="#BE1828"
    out2=workflow.generate_exact_typography_posters(**params)
    assert len(events)==4, "Cache must prevent duplicate paid API calls"
    assert out2["svg"]["4x3"]==out["svg"]["4x3"]


def test_textless_art_prompt_never_requests_model_to_print_verified_copy():
    for fmt in FORMATS:
        prompt=workflow._art_prompt(_brief(),fmt,reference=False)
        assert "WITHOUT ANY PRINTED TEXT" in prompt
        assert "NO fake or placeholder text" in prompt
        assert "The final poster dimensions" in prompt
        assert "copy_character_lengths" in prompt
        assert "6527000" not in prompt
        assert "+7 (951)" not in prompt


def test_main_zip_contains_exact_text_svgs_blank_ai_art_and_originals(
        monkeypatch,tmp_path):
    """Single main-request export transaction, without any paid OpenAI calls."""
    import zipfile
    from app import main
    from app.editable_export import rasterize_svg
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    # Explicitly mocked paid rebranding. Selected photo remains immutable.
    selected=_png((500,310),"gold")
    changed=_png((500,310),"purple")
    original_logo=_png((120,70),"blue")
    called=[]
    def rebrand(brief,raw,**kwargs):
        called.append(("rebrand",raw,kwargs.get("logo")))
        return changed
    def render(brief,raw,*,logo,drawing,reference,model,quality,
               output_dir=None):
        called.append(("render",raw,logo))
        artworks={fmt:Image.new("RGB",FORMATS[fmt],"white")
                  for fmt in FORMATS}
        slots={fmt:_slots(fmt) for fmt in FORMATS}
        # An uploaded logo can be placed independently of its appearance
        # inside the AI-rebranded photograph.
        for fmt in FORMATS:
            slots[fmt]["logo"]={"x":42,"y":152,"w":140,"h":34}
        svg={
            fmt:render_exact_svg(
                brief,fmt,artworks[fmt],slots[fmt],DEFAULT_STYLE,logo=logo)
            for fmt in FORMATS
        }
        pngjpeg={fmt:rasterize_svg(svg[fmt]) for fmt in FORMATS}
        return {
            "png":{fmt:pngjpeg[fmt][0] for fmt in FORMATS},
            "jpeg":{fmt:pngjpeg[fmt][1] for fmt in FORMATS},
            "svg":svg,"artwork":artworks,"layout":slots,
            "typography":{fmt:dict(DEFAULT_STYLE) for fmt in FORMATS},
            "verified_copy":verified_copy(brief),
            "cache_dir":tmp_path/"successful-cache",
        }
    monkeypatch.setattr(main,"rebrand_selected_photo",rebrand)
    monkeypatch.setattr(main,"generate_exact_typography_posters",render)
    result=main._exact_typography_posters_sync(
        _brief(),selected,original_logo,None,None,
        "gpt-image-2.5-flare","medium",
        selected_source={"id":"photo_2","name":"side-view.png"})
    assert [v[0] for v in called]==["rebrand","render"]
    assert called[0][1] == selected
    assert called[1][1] == changed
    assert result["raster_only"] is False
    assert result["generation_mode"]=="ai_template_exact_copy"
    assert result["corel"]["9x16"].endswith(".svg")
    folder=tmp_path/result["job_id"]
    with zipfile.ZipFile(folder/"ai_typographic_posters.zip") as archive:
        names=set(archive.namelist())
        for fmt in FORMATS:
            for name in (f"ai_template_{fmt}.png",f"corel_{fmt}.svg",
                         f"ai_poster_{fmt}.png",f"ai_poster_{fmt}.jpg"):
                assert name in names,name
            root=ET.fromstring(archive.read(f"corel_{fmt}.svg"))
            rows=[e for e in root.iter() if e.get("data-verified-role")]
            assert any(e.get("data-verified-role")=="model"
                       and e.get("data-exact-copy")=="ZubrTrail 500"
                       for e in rows)
        assert archive.read("originals/product_photo.png")==selected
        assert archive.read("originals/customer_logo.png")==original_logo
        assert archive.read("rebranded_product.png")==changed
        chosen=json.loads(archive.read("selected_photo.json"))
        assert chosen["selected_primary"]["id"]=="photo_2"
        typography=json.loads(archive.read("typography_style.json"))
        assert typography["4x3"]["font_family"]=="DejaVu Sans Condensed"
        assert "verified_copy.json" in names
        assert "REVIEW_BEFORE_PUBLICATION.txt" in names
    assert selected==_png((500,310),"gold")
