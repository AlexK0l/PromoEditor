"""Saved-bundle import and revision regressions, with no real paid network."""
import base64
import io
import json
import time
import zipfile
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageChops
from fastapi.testclient import TestClient

from app import main, ai_poster_finish as finish, ai_poster_revision as revision
from app.ai_artwork_fit import fit_complete_artwork, artwork_geometry
from app.ai_native_art_direction import approved_full_copy
from app.approved_presets import approved_zubrtrail_500


def _bytes(image, kind="PNG"):
    b=io.BytesIO()
    image.save(b,kind)
    return b.getvalue()


def _bundle(*,invalid=None):
    """Pre-v10 bundle geometry matches the actual previous 3:2/2:3 export."""
    out=io.BytesIO()
    brief=approved_zubrtrail_500()
    geometry={}
    approved=approved_full_copy(brief)
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for fmt,size in (("4x3",(1536,1024)),("9x16",(1024,1536))):
            source=Image.new("RGB",size,(80,110,140))
            ImageDraw.Draw(source).rectangle((100,100,300,300),fill=(180,30,50))
            target=revision.FORMATS[fmt]
            geometry[fmt]=artwork_geometry(size,target)
            result=fit_complete_artwork(source,target)
            z.writestr(f"native_ai_artwork_{fmt}.png",_bytes(source))
            z.writestr(f"ai_poster_{fmt}.png",_bytes(result))
            z.writestr(f"ai_poster_{fmt}.jpg",_bytes(result,"JPEG"))
        if invalid=="geometry":
            geometry["9x16"]["content_box"][1]=0
        z.writestr("export_geometry.json",json.dumps(geometry))
        z.writestr("brief.json",json.dumps(brief,ensure_ascii=False))
        z.writestr("approved_copy.json",json.dumps(approved,ensure_ascii=False))
        z.writestr("poster_review.json",json.dumps({
            "status":"issues_found","human_review_required":True,
            "formats":{fmt:{"fields":[{"id":"model","status":"different",
                                      "observed":"wrong","region":[100,100,300,200]}]}
                       for fmt in revision.FORMATS}}))
        z.writestr("selected_photo.json",json.dumps({"selected_primary":{"name":"original.png"}}))
        asset=_bytes(Image.new("RGB",(240,180),"blue"))
        z.writestr("originals/product_photo.png",asset)
        z.writestr("rebranded_product.png",asset)
        if invalid=="path":
            z.writestr("../escape.png",asset)
        elif invalid=="duplicate":
            with pytest.warns(UserWarning):
                z.writestr("approved_copy.json","{}")
    return out.getvalue()


@pytest.fixture
def setup(monkeypatch,tmp_path):
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY","mock-only")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    calls=[]
    def edit(**kw):
        with Image.open(kw["image"]) as im:
            size=im.size
        assert kw["size"]==f"{size[0]}x{size[1]}"
        assert "mask" in kw
        calls.append(kw["prompt"])
        candidate=Image.new("RGB",size,(80,110,140))
        draw=ImageDraw.Draw(candidate)
        for y in range(size[1]):
            draw.line((0,y,size[0]-1,y),fill=(80+y%15,110+y%19,140+y%13))
        return SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(_bytes(candidate)).decode("ascii"))])
    monkeypatch.setattr(finish,"client",lambda:SimpleNamespace(images=SimpleNamespace(edit=edit)))
    reviews=[]
    def review(approved,folder,cache,**kw):
        reviews.append({fmt:(folder/f"ai_poster_{fmt}.png").read_bytes() for fmt in revision.FORMATS})
        return {"status":"no_issues_detected","human_review_required":True,"formats":{},"issues_count":0}
    monkeypatch.setattr(revision,"review_pair",review)
    return calls,reviews,tmp_path


def _import(http,raw):
    response=http.post("/api/poster-archive/import",files={"archive":("prior.zip",raw,"application/zip")})
    assert response.status_code==200,response.text
    return response.json()


def _run(http,source,action,*,fmt="9x16",region=None,verify=True,attempt="a"*32):
    result=http.post("/api/generate/start",data={
        "generation_mode":"refine_posters","source_job":source["job_id"],
        "refine_action":action,"refine_format":fmt,"refine_region":json.dumps(region),
        "refine_instruction":"Исправить только число 240.",
        "refine_attempt":attempt,"model":"gpt-image-2.5-flare","quality":"medium",
        "verify_posters":str(verify).lower(),
    })
    assert result.status_code==202,result.text
    path=result.json()["status_url"]
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        state=http.get(path).json()
        if state["status"]!="running":
            # Status is persisted just before the worker releases the slot.
            end=time.monotonic()+3
            while time.monotonic()<end:
                if main.MAIN_AI_GENERATION_SLOT.acquire(blocking=False):
                    main.MAIN_AI_GENERATION_SLOT.release()
                    break
                time.sleep(.02)
            return state
        time.sleep(.04)
    pytest.fail("Queued revision did not finish")


def test_import_expand_then_local_repair_preserves_paid_art_and_sources(setup):
    calls,reviews,storage=setup
    original=_bundle()
    with TestClient(main.app) as http:
        loaded=_import(http,original)
        assert not calls and not reviews
        assert http.get(loaded["zip"]).content==original
        assert loaded["export_geometry"]["9x16"]["outpaint"]["status"]=="not_requested"
        state=_run(http,loaded,"expand")
        assert state["status"]=="complete",state
        expanded=state["result"]
        assert expanded["refinement"]["changed_formats"]==["4x3","9x16"]
        assert len(calls)==2 and all("MASKED OUTPAINTING ONLY" in x for x in calls)
        assert len(reviews)==1
        expanded_raw=http.get(expanded["zip"]).content
        with zipfile.ZipFile(io.BytesIO(original)) as old,zipfile.ZipFile(io.BytesIO(expanded_raw)) as new:
            for fmt in revision.FORMATS:
                name=f"ai_poster_{fmt}.png"
                a=Image.open(io.BytesIO(old.read(name))).convert("RGB")
                b=Image.open(io.BytesIO(new.read(name))).convert("RGB")
                box=tuple(loaded["export_geometry"][fmt]["content_box"])
                assert ImageChops.difference(a.crop(box),b.crop(box)).getbbox() is None
                assert b.size==revision.FORMATS[fmt]
                assert new.read(name)==reviews[-1][fmt]
                assert new.read(f"native_ai_artwork_{fmt}.png")==old.read(f"native_ai_artwork_{fmt}.png")
            assert new.read("approved_copy.json")==old.read("approved_copy.json")
            assert new.read("originals/product_photo.png")==old.read("originals/product_photo.png")
        assert http.get(loaded["zip"]).content==original
        # Reopening a finished archive and asking for full bleed is free.
        again=_import(http,expanded_raw)
        state=_run(http,again,"expand",attempt="b"*32)
        assert state["status"]=="complete" and state["result"]["refinement"]["status"]=="no_change"
        assert len(calls)==2 and len(reviews)==1
        # One local correction on the vertical format only, then a fresh QA.
        region=(800,1280,1040,1510)
        state=_run(http,expanded,"repair",region=region,attempt="c"*32)
        assert state["status"]=="complete",state
        corrected=state["result"]
        assert corrected["refinement"]["changed_formats"]==["9x16"]
        assert len(calls)==3 and "LOCAL MASKED CORRECTION" in calls[-1]
        assert len(reviews)==2 and corrected["publication_status"]=="human_review_required"
        with zipfile.ZipFile(io.BytesIO(expanded_raw)) as old,zipfile.ZipFile(io.BytesIO(http.get(corrected["zip"]).content)) as new:
            for name in ("ai_poster_4x3.png","ai_poster_4x3.jpg","native_ai_artwork_9x16.png","approved_copy.json"):
                assert new.read(name)==old.read(name)
            a=Image.open(io.BytesIO(old.read("ai_poster_9x16.png"))).convert("RGB")
            b=Image.open(io.BytesIO(new.read("ai_poster_9x16.png"))).convert("RGB")
            assert ImageChops.difference(a,b).getbbox()==region
            assert json.loads(new.read("refinement_history.json"))[-1]["action"]=="repair"
        assert http.get(expanded["zip"]).content==expanded_raw


@pytest.mark.parametrize("invalid",["path","duplicate","geometry"])
def test_invalid_bundle_is_rejected_without_paid_calls(setup,invalid):
    calls,reviews,storage=setup
    with TestClient(main.app) as http:
        response=http.post("/api/poster-archive/import",files={"archive":("invalid.zip",_bundle(invalid=invalid),"application/zip")})
        assert response.status_code==400,response.text
    assert not calls and not reviews


def test_invalid_region_and_expired_source_do_not_send_images(setup):
    calls,reviews,storage=setup
    with TestClient(main.app) as http:
        loaded=_import(http,_bundle())
        state=_run(http,loaded,"repair",region=[0,0,1080,1920])
        assert state["status"]=="failed" and state["http_status"]==400
        state=_run(http,{"job_id":"f"*32},"expand")
        assert state["status"]=="failed" and state["http_status"]==404
    assert not calls and not reviews


def test_revision_without_recheck_invalidates_previous_review(setup):
    calls,reviews,storage=setup
    with TestClient(main.app) as http:
        loaded=_import(http,_bundle())
        state=_run(http,loaded,"repair",region=[800,1280,1040,1510],verify=False)
        assert state["status"]=="complete",state
        assert state["result"]["poster_review"]["status"]=="not_requested"
        assert len(calls)==1 and not reviews



def test_revision_publishes_edited_zip_before_optional_review(setup,monkeypatch):
    import threading
    calls,reviews,storage=setup
    entered=threading.Event()
    release=threading.Event()
    def review(approved,folder,cache,**kw):
        entered.set()
        assert release.wait(10)
        raise RuntimeError("private upstream failure")
    monkeypatch.setattr(revision,"review_pair",review)
    with TestClient(main.app) as http:
        loaded=_import(http,_bundle())
        try:
            response=http.post("/api/generate/start",data={
                "generation_mode":"refine_posters","source_job":loaded["job_id"],
                "refine_action":"repair","refine_format":"9x16",
                "refine_region":"[800,1280,1040,1510]","refine_instruction":"Исправить 240.",
                "refine_attempt":"a"*32,"verify_posters":"true",
            })
            assert response.status_code==202,response.text
            assert entered.wait(10)
            url=response.json()["status_url"]
            state=http.get(url).json()
            assert state["status"]=="running" and state["result"]["review_pending"]
            ready=http.get(state["result"]["zip"]).content
            with zipfile.ZipFile(io.BytesIO(ready)) as z:
                assert z.testzip() is None
                assert json.loads(z.read("poster_review.json"))["status"]=="unavailable"
            release.set()
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                state=http.get(url).json()
                if state["status"]=="complete":
                    break
                time.sleep(.04)
            assert state["status"]=="complete",state
            assert not state["result"]["review_pending"]
            assert http.get(state["result"]["zip"]).content==ready
            assert len(calls)==1
        finally:
            release.set()
