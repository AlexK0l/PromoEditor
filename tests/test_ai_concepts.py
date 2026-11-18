"""End-to-end AI-first concepts: optional exemplar and factual, editable output.

Tests use a fake OpenAI layout response. No real paid calls, credential or
third-party style image is required for CI.
"""
import base64
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main, ai_layout
from app.render import default_brief

client=TestClient(main.app)
SVG={"s":"http://www.w3.org/2000/svg"}


def _box(x,y,w,h):
    return {"x":x,"y":y,"w":w,"h":h}


def _landscape():
    return {
        "header":_box(0,0,1000,130),
        "hero":_box(0,140,610,430),
        "specs":_box(620,140,380,430),
        "dimensions":_box(0,580,610,165),
        "benefits":_box(620,580,380,165),
        "roi":_box(0,755,1000,105),
        "footer":_box(0,870,1000,130),
    }


def _portrait():
    return {
        "header":_box(0,0,1000,120),
        "hero":_box(0,130,1000,270),
        "specs":_box(0,410,1000,230),
        "dimensions":_box(0,650,1000,140),
        "benefits":_box(0,795,650,95),
        "roi":_box(660,795,340,95),
        "footer":_box(0,900,1000,100),
    }


def _concepts():
    return [
        {
            "name":name,
            "rationale":"Контрастная промышленная реклама с оригинальным полуприцепом",
            "scene_prompt":"Background only: clean grain terminal without text or vehicles",
            "palette":{"background":"#F6F7F9","foreground":"#182235","accent":"#D51E2A"},
            "layouts":{"4x3":_landscape(),"9x16":_portrait()},
        }
        for name in ("Зерновой терминал","Техническая выразительность","Современная геометрия")
    ]


def _png(rgb):
    source=Image.new("RGBA",(480,300),rgb)
    stream=io.BytesIO()
    source.save(stream,format="PNG")
    return stream.getvalue()


def _uploads(include_example=False):
    result=[
        ("photos",("original-trailer.png",_png((239,183,29,255)),"image/png")),
        ("logos",("brand.png",_png((30,50,74,255)),"image/png")),
    ]
    if include_example:
        result.append(("reference_example",("optional-style.png",
                      _png((100,80,130,255)),"image/png")))
    return result


def _data(brief=None):
    return {"payload":json.dumps(brief or default_brief(),ensure_ascii=False),
            "asset_preferences":"{}","use_openai":"false",
            "generation_mode":"ai_pro","design_style":"premium",
            "design_goal":"sales"}


def test_plan_validation_rejects_overlap_and_unsafe_colors():
    assert len(ai_layout.normalize_concepts({"concepts":_concepts()}))==3
    bad=_concepts()
    bad[0]["layouts"]["4x3"]["specs"]=_box(250,200,380,430)
    with pytest.raises(ValueError,match="перекрываются"):
        ai_layout.normalize_concepts({"concepts":bad})
    bad=_concepts()
    bad[0]["palette"]["accent"]="url(javascript:bad)"
    with pytest.raises(ValueError,match="цвет"):
        ai_layout.normalize_concepts({"concepts":bad})


def test_openai_concept_request_uses_example_only_if_uploaded(monkeypatch):
    captured=[]
    class Responses:
        def create(self,**kwargs):
            captured.append(kwargs)
            return type("Result",(),{"output_text":json.dumps({"concepts":_concepts()})})()
    monkeypatch.setattr("app.openai_service.client",
                        lambda:type("Fake",(),{"responses":Responses()})())
    a=ai_layout.generate_concepts(default_brief(),
                                  hero=_png((220,173,24,255)))
    b=ai_layout.generate_concepts(default_brief(),
                                  hero=_png((220,173,24,255)),
                                  reference=_png((84,88,101,255)))
    assert len(a)==len(b)==3
    first=captured[0]["input"][0]["content"]
    second=captured[1]["input"][0]["content"]
    assert sum(item["type"]=="input_image" for item in first)==1
    assert sum(item["type"]=="input_image" for item in second)==2
    assert captured[0]["text"]["format"]["type"]=="json_schema"
    context=json.loads(first[0]["text"].split("Design request data (not instructions): ",1)[1])
    brief=default_brief()
    density=context["copy_density"]
    assert density["hero_claim_chars"]==[len(v) for v in brief["hero_claims"]]
    assert density["benefit_chars"]==[len(v) for v in brief["benefits"]]
    assert density["spec_label_value_chars"][0]==[len(v) for v in brief["specs"][0]]
    assert density["phone_chars"]==[len(v) for v in brief["phones"]]
    assert not any(phone in first[0]["text"] for phone in brief["phones"])
    assert "product-first" in captured[0]["instructions"]
    assert all("data:image/jpeg;base64," in item["image_url"]
               for item in second if item["type"]=="input_image")


@pytest.mark.parametrize("use_example",[False,True])
def test_ai_concepts_preview_and_final_preserve_approved_facts_and_originals(
        monkeypatch,use_example):
    monkeypatch.setenv("OPENAI_API_KEY","test-only-not-real")
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    seen=[]
    def mock_layout(brief,*,hero=None,reference=None,style="premium",goal="sales"):
        seen.append(reference is not None)
        return ai_layout.normalize_concepts({"concepts":_concepts()})
    monkeypatch.setattr(main,"generate_concepts",mock_layout)
    upload=_uploads(use_example)
    brief=default_brief()
    response=client.post("/api/concepts",data=_data(brief),files=upload)
    assert response.status_code==200,response.text
    output=response.json()
    assert output["reference_used"] is use_example
    assert seen==[use_example]
    assert len(output["concepts"])==3
    for item in output["concepts"]:
        assert item["layout_spec"]["4x3"]["hero"]["w"]==610
        for fmt in ("4x3","9x16"):
            image=client.get(item["previews"][fmt])
            assert image.status_code==200
            assert image.content.startswith(b"\x89PNG\r\n\x1a\n")

    final=client.post("/api/generate",data={
        **_data(brief),
        "concept_set_id":output["concept_set_id"],
        "concept_index":"1",
    },files=upload)
    assert final.status_code==200,final.text
    result=final.json()
    assert result["generation_mode"]=="ai_pro"
    assert "layout_spec" in result
    zipped=client.get(result["zip"])
    assert zipped.status_code==200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as kit:
        assert "layout_spec.json" in kit.namelist()
        spec=json.loads(kit.read("layout_spec.json"))
        assert spec["selected_concept"]["name"]=="Техническая выразительность"
        assert kit.read("originals/primary_photo.png")==upload[0][1][1]
        assert kit.read("originals/logo.png")==upload[1][1][1]
        if use_example:
            assert kit.read("originals/reference_example.png")==upload[2][1][1]
        else:
            assert not any(x.startswith("originals/reference_example")
                           for x in kit.namelist())
        for fmt in ("4x3","9x16"):
            svg=kit.read(f"corel_{fmt}.svg")
            root=ET.fromstring(svg)
            texts=" ".join(" ".join(n.itertext())
                           for n in root.findall(".//s:text",SVG))
            for wanted in ("ZubrTrail 500","229 998",
                           "44 т","+375 (225) 72-01-03"):
                assert wanted in texts,(fmt,wanted,texts[:500])
            assert len(root.findall(".//s:image",SVG))>=2
            assert kit.read(f"poster_{fmt}.png").startswith(b"\x89PNG")


def test_ai_concept_rejects_changed_price_or_source(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-only")
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    monkeypatch.setattr(main,"generate_concepts",
                        lambda brief,**kwargs:ai_layout.normalize_concepts(
                            {"concepts":_concepts()}))
    data=_data()
    initial=client.post("/api/concepts",data=data,files=_uploads())
    assert initial.status_code==200,initial.text
    identifier=initial.json()["concept_set_id"]
    changed=default_brief()
    changed["price"]="999999"
    rejected=client.post("/api/generate",data={
        **_data(changed),"concept_set_id":identifier,"concept_index":"0"
    },files=_uploads())
    assert rejected.status_code==409
    assert "изменились" in rejected.json()["detail"]


def test_template_mode_still_available_without_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    data=_data()
    data["generation_mode"]="template"
    result=client.post("/api/generate",data=data,files=_uploads())
    assert result.status_code==200,result.text
    archive=client.get(result.json()["zip"])
    with zipfile.ZipFile(io.BytesIO(archive.content)) as kit:
        assert "layout_spec.json" not in kit.namelist()
    concept=client.post("/api/concepts",data=_data(),files=_uploads())
    assert concept.status_code==400
    assert "OPENAI_API_KEY" in concept.json()["detail"]



def test_narrow_portrait_economics_keeps_all_four_labels_and_amounts():
    """Visual QA regression: avoid cropped 4-column microtype in 9:16."""
    from app.ai_concept_renderer import render_ai_concept_svg
    from app.render import compute_roi
    item=ai_layout.normalize_concepts({"concepts":_concepts()})[0]
    brief=default_brief()
    root=ET.fromstring(render_ai_concept_svg(brief,"9x16",item))
    labels=[
        " ".join(node.itertext())
        for node in root.findall(".//s:text",SVG)
        if node.get("id","").startswith("ai-roi-name-")
    ]
    values=[
        " ".join(node.itertext())
        for node in root.findall(".//s:text",SVG)
        if node.get("id","").startswith("ai-roi-value-")
    ]
    assert len(labels)==len(values)==4
    for expected in ("ЗА РЕЙС, Br","РЕЙСОВ В ГОД","ЗА ГОД, Br","БАЛАНС, Br"):
        assert expected in labels,(expected,labels)
    from app.render import compute_roi
    money=compute_roi(brief)
    for amount in (money["per_trip"],money["trips"],money["annual"],money["net"]):
        assert f"{amount:,.0f}".replace(","," ") in values
    assert all("…" not in name for name in labels)


@pytest.mark.parametrize("zone,new_height,error_fragment", [
    ("specs", 180, "строк ТТХ"),
    ("dimensions", 48, "чертежа и размеров"),
    ("benefits", 48, "преимуществ"),
    ("roi", 48, "экономики"),
])
def test_ai_layout_preflight_rejects_content_overflow(zone,new_height,error_fragment):
    """The rectangles are valid geometrically, but cannot fit factual copy."""
    from app.ai_concept_renderer import render_ai_concept_svg
    concepts = _concepts()
    concepts[0]["layouts"]["4x3"][zone]["h"] = new_height
    payload = {"concepts": concepts}
    assert len(ai_layout.normalize_concepts(payload)) == 3
    brief = default_brief()
    with pytest.raises(ValueError,match=error_fragment):
        ai_layout.normalize_concepts(payload,brief=brief)
    selected = ai_layout.normalize_concepts(payload)[0]
    with pytest.raises(ValueError,match=error_fragment):
        render_ai_concept_svg(brief,"4x3",selected)


def test_preflight_uses_actual_number_of_spec_rows():
    concepts = _concepts()
    concepts[0]["layouts"]["4x3"]["specs"]["h"] = 180
    brief = default_brief()
    brief["specs"] = [["Полная масса","52,5 т"]]
    assert len(ai_layout.normalize_concepts({"concepts":concepts},brief=brief)) == 3
    brief["specs"] = default_brief()["specs"]
    with pytest.raises(ValueError,match="строк ТТХ"):
        ai_layout.normalize_concepts({"concepts":concepts},brief=brief)


def test_drawing_preflight_uses_real_drawing_presence():
    from app.ai_concept_renderer import render_ai_concept_svg
    concepts = _concepts()
    concepts[0]["layouts"]["4x3"]["dimensions"]["h"] = 48
    item = ai_layout.normalize_concepts({"concepts":concepts})[0]
    brief = default_brief()
    brief["dimensions"] = []
    # Nothing to draw in the dimensions zone: a short empty rectangle is fine.
    render_ai_concept_svg(brief,"4x3",item)
    # But the same rectangle must not silently swallow a user-provided drawing.
    with pytest.raises(ValueError,match="чертежа и размеров"):
        render_ai_concept_svg(brief,"4x3",item,drawing=Image.new("RGB",(320,180),"white"))


def test_ai_accent_palette_is_visible_in_svg_even_with_brief_accent():
    from app.ai_concept_renderer import render_ai_concept_svg
    concepts = _concepts()
    concepts[0]["palette"]["accent"] = "#126BA8"
    item = ai_layout.normalize_concepts({"concepts":concepts})[0]
    brief = default_brief()
    assert brief["accent"] != item["palette"]["accent"]
    svg = render_ai_concept_svg(brief,"4x3",item)
    root = ET.fromstring(svg)
    # Scene.id() appends a numeric suffix to every editable SVG object.
    underline = next((node for node in root.iter()
                      if node.get("id","").startswith("ai-hero-underline-")),None)
    assert underline is not None
    assert underline.get("fill") == "#126BA8"



@pytest.mark.parametrize("fmt", ["4x3", "9x16"])
def test_ai_pro_preserves_sales_claims_when_benefits_are_also_present(fmt):
    """All supplied hero claims survive instead of being dropped for benefits."""
    from app.ai_concept_renderer import render_ai_concept_svg
    brief=default_brief()
    assert brief["hero_claims"] and brief["benefits"]
    selected=ai_layout.normalize_concepts({"concepts":_concepts()})[0]
    root=ET.fromstring(render_ai_concept_svg(brief,fmt,selected))
    labels=[node for node in root.findall(".//s:text",SVG)
            if node.get("id","").startswith("ai-hero-claim-")
            and not node.get("id","").startswith("ai-hero-claims-heading")]
    assert len(labels)==4
    full_text=" ".join(" ".join(n.itertext()) for n in labels)
    for phrase in brief["hero_claims"]:
        assert phrase in full_text,(fmt,phrase,full_text)
    assert "…" not in full_text
    assert "КЛЮЧЕВЫЕ ТЕЗИСЫ" in " ".join(
        " ".join(n.itertext()) for n in root.findall(".//s:text",SVG))


def test_ai_pro_footer_matches_palette_and_bright_accents_use_dark_price_text():
    from app.ai_concept_renderer import render_ai_concept_svg
    items=_concepts()
    items[0]["palette"]["accent"]="#FFEA4C"
    selected=ai_layout.normalize_concepts({"concepts":items})[0]
    root=ET.fromstring(render_ai_concept_svg(default_brief(),"4x3",selected))
    price=[node for node in root.findall(".//s:text",SVG)
           if node.get("id","").startswith("ai-price-")]
    assert len(price)==1 and price[0].get("fill")=="#172235"
    contact=[node for node in root.iter()
             if node.get("id","").startswith("ai-cta-contacts-")]
    assert len(contact)==1
    assert contact[0].get("fill") not in ("#A31324", "#FFEA4C")


def test_verbose_ai_descriptions_are_safely_compacted_without_extra_paid_calls(monkeypatch):
    """An overlong model rationale must not waste the whole paid AI request."""
    concepts=_concepts()
    concepts[0]["rationale"]="Сильная рекламная композиция. " * 25
    concepts[1]["name"]="Инженерная композиция и подробные преимущества " * 4
    concepts[2]["scene_prompt"]="Background only, empty industrial terminal, no text. " * 35
    concepts[2]["rationale"]="   \n  "
    captured=[]
    class Responses:
        def create(self, **kwargs):
            captured.append(kwargs)
            return type("Result",(),{
                "output_text":json.dumps({"concepts":concepts},ensure_ascii=False)
            })()
    monkeypatch.setattr("app.openai_service.client",
                        lambda:type("API",(),{"responses":Responses()})())
    results=ai_layout.generate_concepts(default_brief())
    assert len(captured)==1  # No second Responses API request.
    assert len(results)==3
    assert all(len(item["name"])<=75 and
               len(item["rationale"])<=260 and
               len(item["scene_prompt"])<=600 for item in results)
    assert results[0]["rationale"].endswith("…")
    assert results[1]["name"].endswith("…")
    assert results[2]["scene_prompt"].endswith("…")
    assert results[2]["rationale"]=="План макета с фотографией товара, характеристиками и контактами."
    assert results[0]["layouts"]==concepts[0]["layouts"]
    assert results[0]["palette"]==concepts[0]["palette"]
    # The original JSON-like data is not rewritten or used as factual copy.
    assert len(concepts[0]["rationale"])>260
    instructions=captured[0]["instructions"]
    assert "rationale under 260 characters" in instructions


@pytest.mark.parametrize("field,value", [
    ("name", None),
    ("rationale", ["not", "a", "string"]),
    ("scene_prompt", 42),
])
def test_ai_concept_keeps_invalid_metadata_types_rejected(field,value):
    concept=_concepts()[0]
    concept[field]=value
    with pytest.raises(ValueError, match=f"Неверное поле концепта: {field}"):
        ai_layout.validate_concept(concept)


def test_ai_concept_explanation_260_characters_is_not_ellipsized():
    concept=_concepts()[0]
    concept["rationale"]="Я" * 260
    normalized=ai_layout.validate_concept(concept)
    assert normalized["rationale"]=="Я" * 260




@pytest.mark.parametrize("field", ["name", "rationale", "scene_prompt"])
def test_blank_ai_metadata_uses_safe_nonfactual_fallback(field):
    concept=_concepts()[0]
    concept[field]="  \n\t "
    result=ai_layout.validate_concept(concept)
    assert isinstance(result[field],str) and result[field].strip()
    assert len(result[field])<={"name":75,"rationale":260,"scene_prompt":600}[field]
    assert "  \n\t "==concept[field]  # Do not mutate the model response.


def test_paid_model_roi_footer_overlap_is_repaired_without_another_api_call(monkeypatch):
    """Reproduce a real 4:3 ROI/footer collision reported after a paid call."""
    raw=_concepts()
    raw[0]["layouts"]["4x3"]["roi"]["h"]=130  # y=755..885, footer starts at 870
    assert raw[0]["layouts"]["4x3"]["roi"]["y"]==755
    with pytest.raises(ValueError, match="roi и footer перекрываются в 4x3"):
        ai_layout.normalize_concepts({"concepts":raw},brief=default_brief())

    calls=[]
    class Responses:
        def create(self,**kwargs):
            calls.append(kwargs)
            return type("Reply",(),{"output_text":json.dumps({"concepts":raw})})()
    monkeypatch.setattr("app.openai_service.client",
                        lambda:type("API",(),{"responses":Responses()})())
    repaired=ai_layout.generate_concepts(default_brief())
    assert len(calls)==1
    assert len(repaired)==3
    assert repaired[0]["layouts"]["4x3"]["roi"]["y"]==755
    assert repaired[0]["layouts"]["4x3"]["roi"]["h"]<130
    assert repaired[0]["layouts"]["9x16"]==raw[0]["layouts"]["9x16"]
    assert "адаптировано" in repaired[0]["rationale"]
    assert repaired[0]["layout_repair"]=={"4x3":"repaired","9x16":"original"}
    assert raw[0]["layouts"]["4x3"]["roi"]["h"]==130  # source unchanged
    from app.ai_concept_renderer import render_ai_concept_svg
    for item in repaired:
        for fmt in ("4x3","9x16"):
            assert ET.fromstring(render_ai_concept_svg(default_brief(),fmt,item)).tag.endswith("svg")


def test_paid_ai_response_with_severe_overlap_recovers_distinct_safe_compositions():
    """An AI layout can be badly broken without consuming another call."""
    from app.ai_concept_renderer import render_ai_concept_svg
    raw=_concepts()
    for item in raw:
        item["layouts"]["4x3"]["specs"]=_box(200,200,380,430)
        item["layouts"]["9x16"]["footer"]=_box(0,850,1000,140)
    fixed=ai_layout.normalize_paid_ai_concepts({"concepts":raw},default_brief())
    assert len(fixed)==3
    assert len({tuple(sorted((z,b["x"],b["y"])
                 for z,b in item["layouts"]["4x3"].items()))
                for item in fixed})==3
    for item in fixed:
        assert "адаптировано" in item["rationale"]
        assert item["layout_repair"]=={"4x3":"fallback","9x16":"fallback"}
        for fmt in ("4x3","9x16"):
            ai_layout.validate_concept({k:v for k,v in item.items()
                                        if k not in ("id","layout_repair")})
            assert ET.fromstring(render_ai_concept_svg(default_brief(),fmt,item)).tag.endswith("svg")


def test_paid_layout_recovery_preserves_valid_and_rejects_untrusted_palette():
    raw=_concepts()
    exact=ai_layout.normalize_paid_ai_concepts({"concepts":raw},default_brief())
    assert all(item["layouts"]==raw[i]["layouts"] for i,item in enumerate(exact))
    assert all("адаптировано" not in item["rationale"] for item in exact)
    assert all(item["layout_repair"]=={"4x3":"original","9x16":"original"}
               for item in exact)
    bad=_concepts()
    bad[0]["palette"]["accent"]="url(javascript:alert(1))"
    with pytest.raises(ValueError,match="цвет"):
        ai_layout.normalize_paid_ai_concepts({"concepts":bad},default_brief())


def test_paid_ai_layout_preflight_failure_uses_readable_no_cost_fallback():
    """Eight spec rows must not be compressed to unreadable output."""
    raw=_concepts()
    raw[2]["layouts"]["4x3"]["specs"]["h"]=180
    brief=default_brief()
    corrected=ai_layout.normalize_paid_ai_concepts({"concepts":raw},brief)
    assert corrected[2]["layouts"]["4x3"]["specs"]["h"]>=300
    for concept in corrected:
        ai_layout.validate_renderability(concept,brief,"4x3")
        ai_layout.validate_renderability(concept,brief,"9x16")
    assert raw[2]["layouts"]["4x3"]["specs"]["h"]==180




@pytest.mark.parametrize("fmt", ["4x3", "9x16"])
@pytest.mark.parametrize("bad_ink", ["#FFFFFF", "#F7F7F7", "#D9DDE1"])
def test_ai_pro_pale_foreground_is_replaced_for_readability(fmt,bad_ink):
    """Reproduce the washed-out specs, headings, benefits and ROI from VPS."""
    from app.ai_concept_renderer import render_ai_concept_svg, _contrast_ratio
    concepts=_concepts()
    concepts[0]["palette"]["foreground"]=bad_ink
    item=ai_layout.normalize_concepts({"concepts":concepts})[0]
    root=ET.fromstring(render_ai_concept_svg(default_brief(),fmt,item))
    ids=("ai-spec-name-","ai-benefit-text-","ai-slogan-",
         "ai-roi-name-","ai-dim-name-")
    for prefix in ids:
        nodes=[node for node in root.findall(".//s:text",SVG)
               if node.get("id","").startswith(prefix)]
        assert nodes,(fmt,prefix)
        assert all(_contrast_ratio(node.get("fill"),"#FFFFFF")>=4.5
                   for node in nodes),(fmt,prefix,bad_ink)


def test_ai_pro_preserves_accessible_dark_foreground():
    from app.ai_concept_renderer import render_ai_concept_svg
    root=ET.fromstring(render_ai_concept_svg(
        default_brief(),"4x3",
        ai_layout.normalize_concepts({"concepts":_concepts()})[0]))
    nodes=[n for n in root.findall(".//s:text",SVG)
           if n.get("id","").startswith("ai-spec-name-")]
    assert nodes and all(node.get("fill")=="#182235" for node in nodes)
