"""Low-memory production path: no paid APIs in CI."""
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app import ai_exact_copy_template as pipeline
from app.ai_exact_copy_render import ALL_SLOTS, DEFAULT_STYLE, FORMATS


def png(size=(410,260)):
    out=io.BytesIO()
    Image.new("RGB",size,"white").save(out,format="PNG")
    return out.getvalue()


def brief():
    return {"brand":"ZUBR TRAIL","model":"ZubrTrail 500",
            "category":"","slogan":"","specs":[],"dimensions":[],
            "benefits":[],"hero_claims":[],"proof_points":[],
            "price":"6527000","currency":"₽","vat":False,
            "phones":["+7 (951) 704-30-42"],"show_roi":False,
            "accent":"#C51629","style":"industrial"}


def zones(fmt):
    box={role:{"x":20,"y":20,"w":60,"h":30} for role in ALL_SLOTS}
    if fmt=="4x3":
        box.update({"brand":{"x":35,"y":40,"w":250,"h":95},
                    "model":{"x":335,"y":40,"w":590,"h":100},
                    "product":{"x":150,"y":205,"w":760,"h":580},
                    "price":{"x":35,"y":825,"w":420,"h":120},
                    "phones":{"x":500,"y":825,"w":460,"h":120}})
    else:
        box.update({"brand":{"x":40,"y":35,"w":260,"h":90},
                    "model":{"x":350,"y":35,"w":600,"h":100},
                    "product":{"x":80,"y":195,"w":845,"h":545},
                    "price":{"x":40,"y":790,"w":420,"h":120},
                    "phones":{"x":515,"y":790,"w":430,"h":120}})
    return box


def test_file_backed_ai_outputs_and_cache_resume(monkeypatch,tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    calls=[]
    class Images:
        def edit(self,**kw):
            size=kw["size"]
            calls.append(("image",size))
            dims=(1536,1024) if size=="1536x1024" else (1024,1536)
            return SimpleNamespace(data=[SimpleNamespace(
                b64_json=base64.b64encode(png(dims)).decode())])
    class Responses:
        def create(self,**kw):
            name=kw["text"]["format"]["name"]
            calls.append(("vision",name))
            if name=="poster_blank_slots":
                value={"layouts":{fmt:zones(fmt) for fmt in FORMATS}}
            else:
                assert name=="poster_type_finish"
                value={"styles":{fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}}
            return SimpleNamespace(output_text=json.dumps(value))
    monkeypatch.setattr(pipeline,"client",
        lambda:SimpleNamespace(images=Images(),responses=Responses()))
    subprocess_calls=[]
    real_render=pipeline._rasterize_in_worker
    def capture(svg,png_file,jpeg):
        subprocess_calls.append(Path(svg).name)
        real_render(svg,png_file,jpeg)
    monkeypatch.setattr(pipeline,"_rasterize_in_worker",capture)
    options=dict(brief=brief(),rebranded=png(),
                 logo=None,drawing=None,reference=None,
                 model="gpt-image-2.5-flare",quality="medium")
    first=tmp_path/"first"
    result=pipeline.generate_exact_typography_posters(
        **options,output_dir=first)
    assert result["file_backed"] is True
    assert subprocess_calls==["corel_4x3.svg","corel_9x16.svg"]
    assert [c[0] for c in calls]==["image","image","vision","vision"],calls
    assert not any(isinstance(value,Image.Image)
                   for value in result.values())
    for fmt,dims in FORMATS.items():
        assert result["svg"][fmt]==first/("corel_"+fmt+".svg")
        assert result["artwork_paths"][fmt].is_file()
        assert b"data-verified-role" in result["svg"][fmt].read_bytes()
        with Image.open(result["png"][fmt]) as image:
            assert image.size==dims and image.format=="PNG"
        with Image.open(result["jpeg"][fmt]) as image:
            assert image.size==dims and image.format=="JPEG"
    # A second attempt must reuse the paid images/vision JSON after a crash.
    second=pipeline.generate_exact_typography_posters(
        **options,output_dir=tmp_path/"resume")
    assert len(calls)==4
    assert len(subprocess_calls)==4
    assert second["png"]["4x3"].is_file()
    assert len(list(Path(result["cache_dir"]).glob("*.png")))==2


def test_native_raster_worker_oom_failure_is_reported(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline.subprocess,"run",
        lambda *args,**kw:SimpleNamespace(returncode=-9))
    with pytest.raises(RuntimeError,match="нехватка памяти"):
        pipeline._rasterize_in_worker(
            tmp_path/"test.svg",tmp_path/"test.png",tmp_path/"test.jpg")
