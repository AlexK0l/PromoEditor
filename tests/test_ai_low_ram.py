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
                    "product":{"x":150,"y":205,"w":760,"h":460},
                    "price":{"x":35,"y":825,"w":420,"h":120},
                    "phones":{"x":500,"y":825,"w":460,"h":120}})
    else:
        box.update({"brand":{"x":40,"y":35,"w":260,"h":90},
                    "model":{"x":350,"y":35,"w":600,"h":100},
                    "product":{"x":80,"y":195,"w":845,"h":460},
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


def test_paid_cached_art_with_small_legacy_specs_box_is_locally_recomposed(
        monkeypatch,tmp_path):
    """The NEW editorial panel fixes tiny AI slots without buying new art.

    Previously, a tiny 4:3 'specs' rectangle forced a customer-visible error
    or the deletion of technical claims. The renderer owns its own integrated
    technical strip and depends only on the actual photographed product bbox.
    """
    import xml.etree.ElementTree as ET
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    values=brief()
    values["specs"]=[
        ["Грузоподъёмность","44 т"],
        ["Объём кузова","55 м³"],
        ["Собственный вес","8,3 т"],
    ]
    selected=png()
    cache=pipeline._cache_dir(
        values,selected,None,None,None,"gpt-image-2.5-flare","medium")
    cache.mkdir(parents=True,exist_ok=True)
    for fmt,size in (
        ("4x3",(1536,1024)),("9x16",(1024,1536)),
    ):
        with Image.new("RGB",size,"white") as art:
            art.save(cache/(fmt+".png"),format="PNG")
    raw={fmt:zones(fmt) for fmt in FORMATS}
    raw["4x3"]["specs"]={"x":720,"y":260,"w":75,"h":30}
    pipeline._save_json(cache,"layout_raw.json",raw)
    pipeline._save_json(cache,"typography.json",{
        fmt:dict(DEFAULT_STYLE) for fmt in FORMATS
    })
    monkeypatch.setattr(
        pipeline,"client",
        lambda:pytest.fail("Cached artwork/layout must never pay OpenAI"),
    )
    result=pipeline.generate_exact_typography_posters(
        values,selected,logo=None,drawing=None,reference=None,
        model="gpt-image-2.5-flare",quality="medium",
        output_dir=tmp_path/"recovered",
    )
    for fmt in FORMATS:
        svg=result["svg"][fmt].read_bytes()
        root=ET.fromstring(svg)
        facts=[node.get("data-exact-copy") for node in root.iter()
               if node.get("data-verified-role")=="specs"]
        assert facts==[
            "Грузоподъёмность: 44 т","Объём кузова: 55 м³",
            "Собственный вес: 8,3 т",
        ]
        assert result["png"][fmt].is_file()
    assert pipeline._load_json(cache,"layout_raw.json")==raw
    assert all((cache/(fmt+".png")).is_file() for fmt in FORMATS)


def test_native_raster_worker_oom_failure_is_reported(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline.subprocess,"run",
        lambda *args,**kw:SimpleNamespace(returncode=-9))
    with pytest.raises(RuntimeError,match="нехватка памяти"):
        pipeline._rasterize_in_worker(
            tmp_path/"test.svg",tmp_path/"test.png",tmp_path/"test.jpg")


def test_main_zip_uses_disk_backed_exports_without_reloading_pngs(
        monkeypatch,tmp_path):
    """Primary route archives files rather than accumulating six byte blobs."""
    import zipfile
    from app import main
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"rebrand_selected_photo",
                        lambda brief,raw,**kw:png())
    seen=[]
    def fake_file_backed(brief,rebranded,*,logo,drawing,reference,
                         model,quality,output_dir,progress=None):
        seen.append((rebranded,output_dir))
        outputs={"svg":{},"png":{},"jpeg":{},"artwork_paths":{}}
        for fmt in FORMATS:
            outputs["svg"][fmt]=output_dir/("corel_"+fmt+".svg")
            outputs["svg"][fmt].write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"/>')
            outputs["png"][fmt]=output_dir/("ai_poster_"+fmt+".png")
            outputs["png"][fmt].write_bytes(png())
            outputs["jpeg"][fmt]=output_dir/("ai_poster_"+fmt+".jpg")
            Image.new("RGB",(40,24),"white").save(
                outputs["jpeg"][fmt],format="JPEG")
            outputs["artwork_paths"][fmt]=output_dir/(
                "ai_template_"+fmt+".png")
            outputs["artwork_paths"][fmt].write_bytes(png())
        return {
            **outputs,"file_backed":True,
            "layout":{fmt:zones(fmt) for fmt in FORMATS},
            "typography":{fmt:dict(DEFAULT_STYLE) for fmt in FORMATS},
            "verified_copy":{"model":["ZubrTrail 500"]},
            "cache_dir":tmp_path/"fake_paid_cache",
        }
    monkeypatch.setattr(
        main,"generate_exact_typography_posters",fake_file_backed)
    source=png()
    result=main._exact_typography_posters_sync(
        brief(),source,None,None,None,
        "gpt-image-2.5-flare","medium",
        selected_source={"id":"photo_1","name":"selected.png"})
    assert len(seen)==1 and seen[0][0]==png()
    assert result["raster_only"] is False
    output=tmp_path/result["job_id"]/"ai_typographic_posters.zip"
    with zipfile.ZipFile(output) as archive:
        files=archive.namelist()
        assert "originals/product_photo.png" in files
        assert archive.read("originals/product_photo.png")==source
        for fmt in FORMATS:
            assert archive.read("corel_"+fmt+".svg").startswith(b"<svg")
            assert archive.read("ai_poster_"+fmt+".png")==png()
            assert "ai_template_"+fmt+".png" in files


def test_uploaded_large_logo_is_downscaled_before_rgba_embedding(monkeypatch):
    """Avoid expanding a huge uploaded logo to RGBA at its full dimensions."""
    from app.ai_exact_copy_render import render_exact_svg
    from app.editable_export import Scene

    source=Image.new("RGB",(3200,2400),"red")
    raw=io.BytesIO()
    source.save(raw,format="JPEG",quality=84)
    source.close()
    boxed=zones("4x3")
    boxed["logo"]={"x":45,"y":145,"w":200,"h":54}
    passed=[]
    bitmap=Scene.bitmap
    def inspect(self,group,image,x,y,w,h,name):
        passed.append((name,image.size))
        return bitmap(self,group,image,x,y,w,h,name)
    monkeypatch.setattr(Scene,"bitmap",inspect)
    artwork=Image.new("RGB",FORMATS["4x3"],"white")
    try:
        svg=__import__(
            "app.ai_exact_copy_render",fromlist=["render_exact_svg"]
        ).render_exact_svg(
            brief(),"4x3",artwork,boxed,dict(DEFAULT_STYLE),
            logo=raw.getvalue())
    finally:
        artwork.close()
    assert b"exact-uploaded-logo" in svg
    assert len(passed)==1
    name,(w,h)=passed[0]
    assert name=="exact-uploaded-logo"
    assert w<=900 and h<=175,(
        "Full-size logo was converted before downsampling: "+str((w,h)))


def test_failed_paid_exact_copy_gives_private_partial_art_zip(monkeypatch,tmp_path):
    """A text-zone failure must not leave the customer empty-handed."""
    import zipfile
    from app import main
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","0")
    monkeypatch.setenv("PROMO_AI_TEXT_CALLS_PER_DAY","0")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    source=png()
    monkeypatch.setattr(main,"cached_rebrand_photo",lambda folder:None)
    monkeypatch.setattr(main,"rebrand_selected_photo",
                        lambda brief,raw,**kwargs:source)
    def failure_after_one_paid_art(brief,rebranded,*,output_dir,**kwargs):
        assert rebranded==source
        (output_dir/"ai_template_4x3.png").write_bytes(source)
        raise ValueError("AI не оставил достаточно свободного места для «model» (9x16)")
    monkeypatch.setattr(main,"generate_exact_typography_posters",
                        failure_after_one_paid_art)
    with pytest.raises(main.PartialPosterFailure) as failure:
        main._exact_typography_posters_sync(
            brief(),source,None,None,None,"gpt-image-2.5-flare","medium")
    assert failure.value.cause_type=="ValueError"
    url=failure.value.recovery_zip
    assert url.startswith("/files/") and url.endswith("/ai_failed_generation.zip")
    job_id=url.split("/")[2]
    archive=tmp_path/job_id/"ai_failed_generation.zip"
    with zipfile.ZipFile(archive) as bundle:
        names=bundle.namelist()
        assert "ai_template_4x3.png" in names
        assert "rebranded_product.png" in names
        assert "READ_ME_FIRST.txt" in names
        assert bundle.read("ai_template_4x3.png")==source
        assert "ai_poster_9x16.png" not in bundle.namelist()
        assert "Генерация НЕ завершена" in bundle.read(
            "READ_ME_FIRST.txt").decode("utf-8")
    # Never present partial files as a finished advertising ZIP.
    assert not (tmp_path/job_id/"ai_typographic_posters.zip").is_file()
