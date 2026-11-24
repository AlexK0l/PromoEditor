"""No paid network: verify visual audit contract, conservative comparison and cache."""
import base64
import io
import json
import zipfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from app import ai_poster_review, ai_poster_service, main, product_rebrand_service
from app.ai_native_art_direction import approved_full_copy
from app.approved_presets import approved_zubrtrail_500


def _png():
    buf=io.BytesIO()
    Image.new("RGB",(420,270),"yellow").save(buf,"PNG")
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
                                    "observation":"Проверено визуально"} for v in visual_keys]})
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
            b64_json=base64.b64encode(_png()).decode("ascii"))])
    def create(**kw):
        review_calls.append(kw)
        content=kw["input"][0]["content"]
        images=[x for x in content if x["type"]=="input_image"]
        assert len(images)==4  # two final posters + drawing + rebranded photo
        for item,size in zip(images,[(1440,1080),(1080,1920)]):
            with Image.open(io.BytesIO(base64.b64decode(item["image_url"].split(",",1)[1]))) as image:
                assert image.size==size
        assert "7 550 мм" not in content[0]["text"]
        assert "6 527 000" not in content[0]["text"]
        return SimpleNamespace(output_text=json.dumps(_observations(
            approved,["readability","unwanted_blueprint","product","drawing_consistency"])))
    api=SimpleNamespace(images=SimpleNamespace(edit=edit),responses=SimpleNamespace(create=create))
    monkeypatch.setattr(ai_poster_service,"client",lambda:api)
    monkeypatch.setattr(product_rebrand_service,"client",lambda:api)
    monkeypatch.setattr(ai_poster_review,"client",lambda:api)
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
    def fail(**kw):
        calls.append(kw)
        raise RuntimeError("secret upstream response")
    monkeypatch.setattr(ai_poster_review,"client",
                        lambda:SimpleNamespace(responses=SimpleNamespace(create=fail)))
    approved=approved_full_copy(approved_zubrtrail_500())
    r=ai_poster_review.review_pair(approved,folder,tmp_path/"cache")
    assert r["status"]=="unavailable" and r["human_review_required"]
    assert "secret" not in json.dumps(r)
    assert ai_poster_review.review_pair(approved,folder,tmp_path/"cache")==r
    assert len(calls)==1
