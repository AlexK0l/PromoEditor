"""Real OpenAI Images poster workflow; mocked SDK, no paid CI traffic."""
import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai_poster_service, main
from app.render import default_brief


def _png(color="red"):
    file=io.BytesIO()
    Image.new("RGB", (640, 420), color).save(file, "PNG")
    return file.getvalue()


class Images:
    def __init__(self, fail_portrait=False):
        self.calls=[]
        self.fail_portrait=fail_portrait

    def edit(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_portrait and kwargs["size"]=="1024x1536":
            raise RuntimeError("simulated second API failure")
        encoded=base64.b64encode(_png()).decode("ascii")
        return type("Reply",(),{
            "data":[type("Datum",(),{"b64_json":encoded})()]})()


def test_no_exemplar_full_image_generator_uses_two_actual_paid_image_edits(
        monkeypatch,tmp_path):
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    out=ai_poster_service.generate_full_posters(
        default_brief(),_png(),cache_dir=tmp_path/"poster_cache")
    assert out["4x3"].size==(1440,1080)
    assert out["9x16"].size==(1080,1920)
    assert len(images.calls)==2
    assert all(len(item["image"])==1 for item in images.calls)
    assert images.calls[0]["size"]=="1536x1024"
    assert images.calls[1]["size"]=="1024x1536"
    prompt=images.calls[0]["prompt"]
    assert "NO EXAMPLE IMAGE WAS PROVIDED" in prompt
    assert "not a JSON plan" in prompt
    assert "44 т" in prompt and "ZubrTrail 500" in prompt
    assert "commercial" in prompt.lower()
    assert not (tmp_path/"poster_cache"/"4x3.png").exists()


def test_reference_photo_logo_and_drawing_are_optional_model_inputs(
        monkeypatch,tmp_path):
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    ai_poster_service.generate_full_posters(
        default_brief(),_png(),logo=_png("white"),
        drawing=_png("black"),reference=_png("yellow"),
        cache_dir=tmp_path/"poster_cache")
    assert len(images.calls)==2
    assert all(len(c["image"])==4 for c in images.calls)
    assert all("STYLE REFERENCE ONLY" in c["prompt"] for c in images.calls)
    assert all("Never import claims" in c["prompt"] for c in images.calls)


def test_paid_aspect_survives_second_image_api_failure(monkeypatch,tmp_path):
    images=Images(fail_portrait=True)
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    params=dict(brief=default_brief(),product_photo=_png(),
                cache_dir=tmp_path/"paid_cache")
    with pytest.raises(RuntimeError,match="second API failure"):
        ai_poster_service.generate_full_posters(**params)
    assert (tmp_path/"paid_cache"/"4x3.png").exists()
    images.fail_portrait=False
    images_out=ai_poster_service.generate_full_posters(**params)
    assert len(images.calls)==3
    assert images_out["9x16"].size==(1080,1920)


def test_invalid_photo_model_and_quality_never_send_paid_request(
        monkeypatch,tmp_path):
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    with pytest.raises(ValueError,match="исходное фото"):
        ai_poster_service.generate_full_posters(default_brief(),b"")
    with pytest.raises(ValueError,match="модель"):
        ai_poster_service.generate_full_posters(
            default_brief(),_png(),model="unverified_model")
    with pytest.raises(ValueError,match="качество"):
        ai_poster_service.generate_full_posters(
            default_brief(),_png(),quality="ultra")
    assert images.calls==[]


def test_ai_poster_route_without_exemplar_downloads_raster_and_originals(
        monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","mock-no-network-key")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda req:None)
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    with TestClient(main.app) as client:
        response=client.post(
            "/api/ai-posters",
            data={"payload":json.dumps(default_brief(),ensure_ascii=False)},
            files={"hero":("vehicle.png",_png(),"image/png")})
        assert response.status_code==200,response.text
        result=response.json()
        assert result["reference_used"] is False
        assert result["raster_only"] is True
        assert result["generation_mode"]=="openai_full_poster"
        assert len(images.calls)==2
        a=client.get(result["images"]["4x3"])
        b=client.get(result["images"]["9x16"])
        assert a.status_code==b.status_code==200
        assert Image.open(io.BytesIO(a.content)).size==(1440,1080)
        assert Image.open(io.BytesIO(b.content)).size==(1080,1920)
        zip_response=client.get(result["zip"])
        assert zip_response.status_code==200
        with zipfile.ZipFile(io.BytesIO(zip_response.content)) as z:
            names=z.namelist()
            assert "ai_poster_4x3.png" in names
            assert "ai_poster_9x16.png" in names
            assert "REVIEW_BEFORE_PUBLICATION.txt" in names
            assert z.read("originals/product_photo.png")==_png()
            assert "AI-макет" in z.read(
                "REVIEW_BEFORE_PUBLICATION.txt").decode("utf8")


def test_ai_poster_route_requires_actual_product_photo_without_spending(
        monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","mock-no-network-key")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda req:None)
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    with TestClient(main.app) as client:
        response=client.post(
            "/api/ai-posters",
            data={"payload":json.dumps(default_brief())})
    assert response.status_code==400
    assert "главное фото" in response.json()["detail"]
    assert images.calls==[]


def test_quota_error_for_full_poster_is_429_without_network(monkeypatch,tmp_path):
    from app.ai_quota import QuotaExceeded
    monkeypatch.setenv("OPENAI_API_KEY","mock-no-network-key")
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda req:None)
    def quota(*a,**kw):
        raise QuotaExceeded("CI: quota blocked")
    monkeypatch.setattr(main,"generate_full_posters",quota)
    with TestClient(main.app) as client:
        response=client.post(
            "/api/ai-posters",data={
                "payload":json.dumps(default_brief())},
            files={"hero":("vehicle.png",_png(),"image/png")})
    assert response.status_code==429
    assert "quota blocked" in response.json()["detail"]


def test_untrusted_reference_is_not_promoted_to_factual_source():
    base=default_brief()
    prompt=ai_poster_service._prompt(
        base, "4x3", logo=False, drawing=False, reference=True)
    assert "Never import claims" in prompt
    assert "not its product, claims or branding" in prompt
    assert "44 т" in prompt



def test_two_paid_images_require_two_available_daily_calls_before_start(
        monkeypatch,tmp_path):
    from app.ai_quota import QuotaExceeded
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","1")
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    with pytest.raises(QuotaExceeded,match="Ни один новый платный"):
        ai_poster_service.generate_full_posters(
            default_brief(),_png(),cache_dir=tmp_path/"cache")
    assert images.calls==[]


def test_partial_cached_poster_needs_only_one_remaining_daily_call(
        monkeypatch,tmp_path):
    import sqlite3
    from app.ai_quota import _utc_day
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("PROMO_AI_IMAGE_CALLS_PER_DAY","2")
    with sqlite3.connect(tmp_path/"openai_call_quota.sqlite3") as db:
        db.execute("CREATE TABLE paid_call_usage "
                   "(utc_day TEXT,category TEXT,attempts INTEGER)")
        db.execute("INSERT INTO paid_call_usage VALUES (?,?,?)",
                   (_utc_day(),"image",1))
    cache=tmp_path/"existing"
    cache.mkdir()
    Image.new("RGB",(640,420),"red").save(cache/"4x3.png","PNG")
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    out=ai_poster_service.generate_full_posters(
        default_brief(),_png(),cache_dir=cache)
    assert out["4x3"].size==(1440,1080)
    assert out["9x16"].size==(1080,1920)
    assert len(images.calls)==1
    assert images.calls[0]["size"]=="1024x1536"
