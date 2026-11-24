"""No paid network: verify visual audit contract, conservative comparison and cache."""
import asyncio
import base64
import io
import json
import threading
import time
import zipfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from app import ai_poster_review, ai_poster_service, main, product_rebrand_service
from app.ai_native_art_direction import approved_full_copy
from app.approved_presets import approved_zubrtrail_500


def _png(size=(420,270)):
    buf=io.BytesIO()
    Image.new("RGB",size,"yellow").save(buf,"PNG")
    return buf.getvalue()


def _observations(approved, visual_keys, *, fail=True):
    formats=[]
    for fmt in ("4x3","9x16"):
        rows=[{"id":f["id"],"observed":f["expected"],"state":"readable"}
              for f in ai_poster_review.expected_fields(approved)]
        if fail and fmt=="4x3":
            next(r for r in rows if r["id"]=="dim_4")["observed"]="7 550 мм"
            next(r for r in rows if r["id"]=="phone_1")["observed"]="+7 (951) 704-29"
        if fail and fmt=="9x16":
            rows=[r for r in rows if r["id"]!="roi_annual_additional_revenue"]
        formats.append({"format":fmt,"fields":rows,
                        "visuals":[{"id":v,"state":"no_issue_detected",
                                    "observation":"Проверено визуально"} for v in visual_keys],
                        "vehicle_instances":[{
                            "location":"Главное фото","view_state":"same_as_selected",
                            "visible_axles":4,"axle_visibility":"complete",
                            "observed_brand":approved["brand"],"observed_model":approved["model"],
                            "manufacturer_marks":[approved["brand"],approved["model"]],
                            "markings_readable":True,"observation":"Четыре оси, один ракурс",
                        }]})
    return {"formats":formats}


def test_wrong_numbers_and_missing_roi_never_pass():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["readability","unwanted_blueprint"]
    report=ai_poster_review.compare_review(approved,_observations(approved,keys),keys)
    assert report["status"]=="issues_found"
    assert report["issues_count"]==3
    assert report["human_review_required"] is True
    checks={c["id"]:c for c in report["formats"]["4x3"]["fields"]}
    assert checks["dim_4"]["expected"]=="1 150 мм"
    assert checks["dim_4"]["observed"]=="7 550 мм"
    assert checks["dim_4"]["status"]=="different"
    assert checks["phone_1"]["status"]=="different"
    absent={c["id"]:c for c in report["formats"]["9x16"]["fields"]}
    assert absent["roi_annual_additional_revenue"]["status"]=="unverified"


def test_duplicate_or_absent_evidence_is_not_approval():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["readability","unwanted_blueprint"]
    raw=_observations(approved,keys,fail=False)
    clean=ai_poster_review.compare_review(approved,raw,keys)
    assert clean["status"]=="no_issues_detected"
    assert clean["human_review_required"]
    raw["formats"][0]["fields"].append(raw["formats"][0]["fields"][0])
    raw["formats"][1]["visuals"].pop()
    bad=ai_poster_review.compare_review(approved,raw,keys)
    assert bad["status"]=="issues_found"
    assert bad["issues_count"]==2


def test_opted_in_http_route_reviews_both_real_final_rasters_once_and_caches(
        monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","fake-test-key")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    image_calls=[]
    review_calls=[]
    brief=approved_zubrtrail_500()
    approved=approved_full_copy(main._normalize(brief))
    def edit(**kw):
        image_calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(_png(tuple(map(int,kw["size"].split("x"))))).decode("ascii"))])
    async def create(**kw):
        review_calls.append(kw)
        content=kw["input"][0]["content"]
        images=[x for x in content if x["type"]=="input_image"]
        assert len(images)==5  # two final posters + drawing + original + rebranded photo
        assert any("ORIGINAL SELECTED PRODUCT" in x.get("text","") for x in content)
        assert "manufacturer_marks" in content[0]["text"]
        for item,size in zip(images,[(1440,1080),(1080,1920)]):
            with Image.open(io.BytesIO(base64.b64decode(item["image_url"].split(",",1)[1]))) as image:
                assert image.size==size
        assert "7 550 мм" not in content[0]["text"]
        assert "6 527 000" not in content[0]["text"]
        return SimpleNamespace(output_text=json.dumps(_observations(
            approved,["readability","unwanted_blueprint","product","source_geometry","drawing_consistency"])))
    async def close():
        pass
    api=SimpleNamespace(images=SimpleNamespace(edit=edit),responses=SimpleNamespace(create=create),close=close)
    monkeypatch.setattr(ai_poster_service,"client",lambda:api)
    monkeypatch.setattr(product_rebrand_service,"client",lambda:api)
    monkeypatch.setattr(ai_poster_review,"async_client",lambda:api)
    with TestClient(main.app) as http:
        def submit(verify):
            return http.post("/api/generate",data={
                "payload":json.dumps(brief,ensure_ascii=False),
                "generation_mode":"hybrid","use_openai":"true",
                "verify_posters":str(verify).lower(),
            },files=[("hero",("photo.png",_png(),"image/png")),
                     ("drawing",("drawing.png",_png(),"image/png"))])
        no_review=submit(False)
        assert no_review.status_code==200,no_review.text
        assert no_review.json()["poster_review"]["status"]=="not_requested"
        assert len(image_calls)==3 and not review_calls
        first=submit(True)
        assert first.status_code==200,first.text
        result=first.json()
        assert result["publication_status"]=="human_review_required"
        assert result["review_gate"]=="blocked"
        assert result["poster_review"]["status"]=="issues_found",result["poster_review"]
        assert len(image_calls)==3 and len(review_calls)==1
        archive=http.get(result["zip"])
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert json.loads(z.read("poster_review.json"))==result["poster_review"]
            assert z.read("originals/drawing_preview.png")==_png()
        again=submit(True)
        assert again.status_code==200,again.text
        assert again.json()["poster_review"]==result["poster_review"]
        assert len(image_calls)==3 and len(review_calls)==1


def test_failed_review_does_not_discard_or_auto_retry_paid_images(monkeypatch,tmp_path):
    folder=tmp_path/"job"
    folder.mkdir()
    for fmt in ("4x3","9x16"):
        (folder/f"ai_poster_{fmt}.png").write_bytes(_png())
    calls=[]
    async def fail(**kw):
        calls.append(kw)
        raise RuntimeError("secret upstream response")
    async def close():
        pass
    monkeypatch.setattr(ai_poster_review,"async_client",
                        lambda:SimpleNamespace(responses=SimpleNamespace(create=fail),close=close))
    approved=approved_full_copy(approved_zubrtrail_500())
    r=ai_poster_review.review_pair(approved,folder,tmp_path/"cache")
    assert r["status"]=="unavailable" and r["human_review_required"]
    assert "secret" not in json.dumps(r)
    assert ai_poster_review.review_pair(approved,folder,tmp_path/"cache")==r
    assert len(calls)==1



def test_roi_numeric_presentation_is_not_a_factual_mismatch():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["readability","unwanted_blueprint"]
    raw=_observations(approved,keys,fail=False)
    for fmt in raw["formats"]:
        fields={x["id"]:x for x in fmt["fields"]}
        fields["roi_scenario_years"]["observed"]="5 лет"
        fields["roi_net_economic_effect"]["observed"]="+3 115 550 ₽"
        fields["roi_payback_years"]["observed"]="≈ 2.12 года"
        fields["roi_trips_per_year"]["observed"]="240 рейсов в год"
    clean=ai_poster_review.compare_review(approved,raw,keys)
    assert clean["status"]=="no_issues_detected"
    fields={x["id"]:x for x in raw["formats"][0]["fields"]}
    fields["roi_net_economic_effect"]["observed"]="−3 115 550 ₽"
    fields["roi_scenario_years"]["observed"]="5 месяцев"
    fields["roi_payback_years"]["observed"]="≈ 2,13 года"
    fields["roi_trips_per_year"]["observed"]="2400 рейсов"
    fields["roi_annual_additional_revenue"]["observed"]="1 080 000 $"
    fields["price"]["observed"]="6 527 000 ₽ без НДС"
    assert ai_poster_review.compare_review(approved,raw,keys)["issues_count"]==6


def test_visual_evidence_blocks_extra_axle_old_brand_and_unapproved_angle():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["readability","unwanted_blueprint","product","logo"]
    raw=_observations(approved,keys,fail=False)
    assert ai_poster_review.compare_review(approved,raw,keys)["status"]=="no_issues_detected"
    # A generic AI opinion cannot overrule structured observations.
    wide,tall=raw["formats"]
    wide["vehicle_instances"][0]["visible_axles"]=5
    tall["vehicle_instances"][0]["manufacturer_marks"].append("OLD-MAKER")
    tall["vehicle_instances"][0]["observed_model"]=""
    tall["vehicle_instances"][0]["view_state"]="different"
    tall["vehicle_instances"].append(dict(tall["vehicle_instances"][0],location="Вставка"))
    report=ai_poster_review.compare_review(approved,raw,keys)
    assert report["status"]=="issues_found"
    assert report["formats"]["4x3"]["vehicle_check"]["expected_axles"]==4
    assert report["formats"]["4x3"]["vehicle_check"]["status"]=="issue"
    assert any("OLD-MAKER" in msg for msg in report["formats"]["9x16"]["vehicle_check"]["issues"])
    assert report["human_review_required"] is True


def test_missing_vehicle_evidence_cannot_pass():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["product"]
    raw=_observations(approved,keys,fail=False)
    raw["formats"][0].pop("vehicle_instances")
    raw["formats"][1]["vehicle_instances"][0]["axle_visibility"]="partial"
    raw["formats"][1]["vehicle_instances"][0]["markings_readable"]=False
    report=ai_poster_review.compare_review(approved,raw,keys)
    assert report["status"]=="issues_found"
    assert all(report["formats"][fmt]["vehicle_check"]["status"]=="issue" for fmt in ("4x3","9x16"))



def test_located_fields_keep_only_valid_coordinates():
    approved=approved_full_copy(approved_zubrtrail_500())
    keys=["readability","unwanted_blueprint"]
    raw=_observations(approved,keys,fail=False)
    fields=raw["formats"][1]["fields"]
    fields[0].update(state="conflicting",region=[800,600,970,640],observed="ZUBR TRAIL ZUBR TRAIL")
    fields[1]["region"]=[10,20,1200,50]
    fields[2]["region"]=[True,20,100,50]
    report=ai_poster_review.compare_review(approved,raw,keys)
    rows=report["formats"]["9x16"]["fields"]
    assert rows[0]["region"]==[800,600,970,640]
    assert rows[0]["status"]=="conflicting"
    assert rows[1]["region"] is None
    assert rows[2]["region"] is None



def test_review_has_absolute_deadline_even_with_active_connection(monkeypatch,tmp_path):
    folder=tmp_path/"job"
    folder.mkdir()
    for fmt in ("4x3","9x16"):
        (folder/f"ai_poster_{fmt}.png").write_bytes(_png())
    calls=[]
    cancelled=[]
    async def slow(**kw):
        calls.append(kw)
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)
    async def close():
        pass
    monkeypatch.setattr(ai_poster_review,"async_client",lambda:SimpleNamespace(
        responses=SimpleNamespace(create=slow),close=close))
    monkeypatch.setattr(ai_poster_review,"REVIEW_DEADLINE_SECONDS",.03)
    approved=approved_full_copy(approved_zubrtrail_500())
    result=ai_poster_review.review_pair(approved,folder,tmp_path/"cache")
    assert result["status"]=="unavailable" and "лимит времени" in result["reason"]
    assert len(calls)==1 and cancelled==[True]
    assert ai_poster_review.review_pair(approved,folder,tmp_path/"cache")==result
    assert len(calls)==1



def test_background_generation_publishes_downloadable_zip_before_review(monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","fake-test-key")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    entered=threading.Event()
    release=threading.Event()
    calls=[]
    def edit(**kw):
        calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(_png(tuple(map(int,kw["size"].split("x"))))).decode("ascii"))])
    api=SimpleNamespace(images=SimpleNamespace(edit=edit))
    monkeypatch.setattr(ai_poster_service,"client",lambda:api)
    monkeypatch.setattr(product_rebrand_service,"client",lambda:api)
    def review(approved,folder,cache,**kw):
        assert (folder/"ai_posters.zip").is_file()
        entered.set()
        assert release.wait(10)
        return {"status":"issues_found","formats":{},"issues_count":1,"human_review_required":True}
    monkeypatch.setattr(main,"review_pair",review)
    with TestClient(main.app) as http:
        try:
            started=http.post("/api/generate/start",data={
                "payload":json.dumps(approved_zubrtrail_500(),ensure_ascii=False),
                "generation_mode":"hybrid","verify_posters":"true","use_openai":"true",
            },files={"hero":("photo.png",_png(),"image/png")})
            assert started.status_code==202,started.text
            assert entered.wait(10)
            url=started.json()["status_url"]
            state=http.get(url).json()
            assert state["status"]=="running"
            assert state["result"]["review_pending"] is True
            result=state["result"]
            original=http.get(result["zip"]).content
            with zipfile.ZipFile(io.BytesIO(original)) as z:
                assert z.testzip() is None
                assert json.loads(z.read("poster_review.json"))["status"]=="unavailable"
                assert len([name for name in z.namelist() if name.startswith("native_ai_artwork")])==2
            release.set()
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                state=http.get(url).json()
                if state["status"]=="complete":
                    break
                time.sleep(.03)
            assert state["status"]=="complete",state
            assert state["result"]["review_pending"] is False
            final=http.get(result["zip"]).content
            with zipfile.ZipFile(io.BytesIO(original)) as a,zipfile.ZipFile(io.BytesIO(final)) as b:
                assert json.loads(b.read("poster_review.json"))["status"]=="issues_found"
                for name in a.namelist():
                    if name!="poster_review.json":
                        assert a.read(name)==b.read(name)
            assert len(calls)==3
        finally:
            release.set()
