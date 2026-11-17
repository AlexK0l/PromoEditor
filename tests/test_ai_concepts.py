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
