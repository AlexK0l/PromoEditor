"""AI-first art director: optional references, two actual AI layouts and exact SVG facts."""
import base64
import copy
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai_director, main
from app.render import default_brief

client=TestClient(main.app)


def blueprint():
    return {
        "concept":"Cinematic original industrial premium advertising",
        "scene_prompt":"Realistic grain logistics terminal with dramatic natural light",
        "ink":"#141923","surface":"#FFFFFF","support":"#E9EFF4",
        "layouts":{
            "4x3":{
                "header":[0,0,1000,145],
                "hero":[0,145,645,380],
                "specs":[650,145,350,380],
                "drawing":[0,525,1000,155],
                "benefits":[0,680,1000,75],
                "proof":[0,755,1000,55],
                "finance":[0,810,1000,70],
                "footer":[0,880,1000,120],
            },
            "9x16":{
                "header":[0,0,1000,120],
                "hero":[0,120,1000,230],
                "specs":[0,350,1000,185],
                "drawing":[0,535,1000,125],
                "benefits":[0,660,1000,95],
                "proof":[0,755,1000,70],
                "finance":[0,825,1000,80],
                "footer":[0,905,1000,95],
            },
        }
    }


def png(color="#f2b12f"):
    out=io.BytesIO()
    Image.new("RGB",(720,400),color).save(out,format="PNG")
    return out.getvalue()


class StubAI:
    def __init__(self):
        self.requests=[]
        self.calls=[]
        self.responses=self
        self.images=self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return type("Response",(),{"status":"completed",
                                   "output_text":json.dumps(blueprint())})()

    def generate(self, **kwargs):
        self.calls.append(("generate",kwargs))
        return self._picture()

    def edit(self, **kwargs):
        self.calls.append(("edit",kwargs))
        return self._picture()

    def _picture(self):
        payload=png("#dbe5eb")
        item=type("ImageItem",(),{"b64_json":base64.b64encode(payload).decode()})()
        return type("ImageResult",(),{"data":[item]})()


def test_reference_is_optional_in_schema_planner_and_image_calls(monkeypatch):
    stub=StubAI()
    monkeypatch.setattr(ai_director,"client",lambda:stub)
    brief=default_brief()
    plan=ai_director.generate_plan(brief,references=[])
    assert plan["layouts"]["4x3"]["hero"]==[0,145,645,380]
    assert len(stub.requests)==1
    content=stub.requests[0]["input"][0]["content"]
    assert sum(x["type"]=="input_image" for x in content)==0
    assert '"has_reference": false' in content[0]["text"]
    art=ai_director.generate_artwork(brief,plan,references=[],model="gpt-image-2.5-flare")
    assert set(art)=={"4x3","9x16"}
    assert [method for method,_ in stub.calls]==["generate","generate"]
    assert all("No text" in kwargs["prompt"] or "NO readable text" in kwargs["prompt"]
               for _,kwargs in stub.calls)

    ref=png("#b53333")
    stub.requests.clear()
    stub.calls.clear()
    ai_director.generate_plan(brief,references=[ref])
    assert sum(x["type"]=="input_image" for x in
               stub.requests[0]["input"][0]["content"])==1
    ai_director.generate_artwork(brief,plan,references=[ref])
    assert [method for method,_ in stub.calls]==["edit","edit"]
    assert all(len(kwargs["image"])==1 for _,kwargs in stub.calls)


def test_plan_geometry_rejects_overlaps_and_illegible_sections():
    data=default_brief()
    valid=blueprint()
    assert ai_director.validate_plan(valid,data)==valid

    broken=copy.deepcopy(valid)
    broken["layouts"]["4x3"]["footer"]=[0,750,1000,120]
    with pytest.raises(ValueError,match="пересекаются"):
        ai_director.validate_plan(broken,data)

    broken=copy.deepcopy(valid)
    broken["layouts"]["4x3"]["specs"]=[650,150,190,410]
    with pytest.raises(ValueError,match="слишком мала"):
        ai_director.validate_plan(broken,data)

    broken=copy.deepcopy(valid)
    broken["layouts"]["9x16"]["hero"]=[0,500,1200,220]
    with pytest.raises(ValueError,match="выходит за постер"):
        ai_director.validate_plan(broken,data)


def test_render_has_source_product_separate_from_ai_art_and_all_exact_facts():
    import xml.etree.ElementTree as ET
    from app.editable_export import rasterize_svg
    brief=default_brief()
    plan=blueprint()
    hero=Image.new("RGBA",(800,420),(245,192,54,255))
    drawing=Image.new("RGB",(900,520),"white")
    logo=Image.new("RGB",(270,120),"white")
    art=Image.new("RGB",(720,450),"#8cbbce")
    for key,size in (("4x3",(1440,1080)),("9x16",(1080,1920))):
        svg=ai_director.render_ai_poster(
            brief,key,plan,art,hero=hero,logo=logo,drawing=drawing)
        root=ET.fromstring(svg)
        names=[el.attrib.get("id","") for el in root.iter()]
        assert any(s.startswith("ai-art-director-artwork") for s in names)
        assert any(s.startswith("original-product-photo") for s in names)
        assert any(s.startswith("original-drawing") for s in names)
        assert any(s.startswith("original-logo") for s in names)
        text=" ".join(" ".join(e.itertext()) for e in root.iter()
                      if e.tag.endswith("}text"))
        for label,value in brief["specs"]+brief["dimensions"]:
            assert str(value) in text,(key,value)
        for value in brief["phones"]:
            assert value in text,(key,value)
        assert "229 998" in text
        output,_=rasterize_svg(svg)
        with Image.open(io.BytesIO(output)) as image:
            assert image.size==size


def test_new_ui_is_ai_first_and_reference_field_is_not_required():
    response=client.get("/")
    assert response.status_code==200
    html=response.text
    assert 'name="design-mode" value="ai_first" checked' in html
    assert 'name="design-mode" value="vector"' in html
    assert html.count('id="references"')==1
    assert html.index('id="references"') < html.index('id="advanced-settings"')
    assert 'Эталон необязателен' in html
    config=client.get("/api/config").json()
    assert config["reference_optional"] is True
    assert config["design_modes"]==["ai_first","vector"]
    js=client.get("/static/app.js").text
    assert "form.append('design_mode',designMode())" in js


def test_ai_first_requires_key_and_never_silently_changes_to_template(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    data={"payload":json.dumps(default_brief(),ensure_ascii=False),
          "design_mode":"ai_first","use_openai":"false"}
    result=client.post("/api/generate",data=data)
    assert result.status_code==400
    assert "OPENAI_API_KEY" in result.json()["detail"]


def test_ai_first_end_to_end_generate_and_export_optional_reference(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","fake-ci-key")
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    stub=StubAI()
    monkeypatch.setattr(ai_director,"client",lambda:stub)
    brief=default_brief()
    brief["style"]="reference_pro"
    hero_raw=png()
    data={"payload":json.dumps(brief,ensure_ascii=False),
          "design_mode":"ai_first","use_openai":"false",
          "use_demo":"false","model":"gpt-image-2.5-flare",
          "quality":"medium"}
    # No reference upload at all: this is the PRIMARY, supported workflow.
    result=client.post("/api/generate",data=data,files=[
        ("hero",("trailer.png",hero_raw,"image/png")),
    ])
    assert result.status_code==200,result.text
    response=result.json()
    assert response["ai_used"] is True
    assert response["design_mode"]=="ai_first"
    assert response["reference_used"] is False
    assert len(stub.requests)==1 and len(stub.calls)==2
    assert all(method=="generate" for method,_ in stub.calls)
    with zipfile.ZipFile(io.BytesIO(client.get(response["zip"]).content)) as z:
        filenames=set(z.namelist())
        assert {"ai_design_plan.json","ai_art_4x3.png","ai_art_9x16.png",
                "corel_4x3.svg","corel_9x16.svg"}.issubset(filenames)
        plan=json.loads(z.read("ai_design_plan.json"))
        assert plan["concept"]==blueprint()["concept"]
        svg=z.read("corel_4x3.svg")
        assert b"ai-art-director-artwork" in svg
        assert b"original-product-photo" in svg
        assert b"ai-price" in svg
        stored=json.loads(z.read("brief.json"))
        assert stored["_metadata"]["design_mode"]=="ai_first"
        assert stored["_metadata"]["reference_supplied"] is False

    stub.requests.clear()
    stub.calls.clear()
    # Reference is optional, but when supplied it affects both AI steps.
    reference=png("#c1a3a3")
    second=client.post("/api/generate",data=data,files=[
        ("hero",("trailer.png",hero_raw,"image/png")),
        ("references",("mood.png",reference,"image/png")),
    ])
    assert second.status_code==200,second.text
    assert second.json()["reference_used"] is True
    assert len(stub.requests)==1 and len(stub.calls)==2
    assert [method for method,_ in stub.calls]==["edit","edit"]



def test_ai_plan_moves_real_svg_regions_not_only_background_pixels():
    import xml.etree.ElementTree as ET
    brief=default_brief()
    art=Image.new("RGB",(120,90),"#d9e1ea")
    hero=Image.new("RGB",(640,360),"yellow")
    first=blueprint()
    second=copy.deepcopy(first)
    second["layouts"]["4x3"]["hero"]=[0,145,615,380]
    second["layouts"]["4x3"]["specs"]=[620,145,380,380]
    assert ai_director.validate_plan(second,brief)
    originals=ET.fromstring(ai_director.render_ai_poster(
        brief,"4x3",first,art,hero=hero))
    changed=ET.fromstring(ai_director.render_ai_poster(
        brief,"4x3",second,art,hero=hero))
    def product_w(xml):
        return next(float(e.get("width"))
                    for e in xml.iter()
                    if e.get("id","").startswith("original-product-photo"))
    def spec_x(xml):
        return next(float(e.get("x"))
                    for e in xml.iter()
                    if e.get("id","").startswith("ai-spec-panel"))
    assert product_w(originals)>product_w(changed)
    assert spec_x(originals)!=spec_x(changed)


def test_invalid_ai_layout_stops_before_paid_image_requests(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","fake-ci-key")
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    class InvalidPlan(StubAI):
        def create(self,**kwargs):
            self.requests.append(kwargs)
            broken=blueprint()
            broken["layouts"]["4x3"]["footer"]=[0,750,1000,120]
            return type("Result",(),{"status":"completed",
                                     "output_text":json.dumps(broken)})()
    stub=InvalidPlan()
    monkeypatch.setattr(ai_director,"client",lambda:stub)
    payload={
        "payload":json.dumps(default_brief(),ensure_ascii=False),
        "design_mode":"ai_first","use_openai":"false",
    }
    result=client.post("/api/generate",data=payload)
    assert result.status_code==400,result.text
    assert "пересекаются" in result.json()["detail"]
    assert len(stub.requests)==1
    assert not stub.calls  # no paid image API request


def test_typography_preflight_catches_truncated_critical_numbers():
    brief=default_brief()
    brief["specs"][0][1]="Очень длинное документально подтверждённое значение "*12
    with pytest.raises(ValueError,match="обрезан|не помещается"):
        ai_director.preflight_typography(brief,blueprint())
