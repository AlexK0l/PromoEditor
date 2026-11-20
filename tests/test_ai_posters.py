"""Real OpenAI Images poster workflow; mocked SDK, no paid CI traffic."""
import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai_poster_service, product_rebrand_service, main
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
    monkeypatch.setattr(product_rebrand_service,"client",
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
        assert len(images.calls)==3
        assert result["rebranding_applied"] is True
        assert result["rebranded_photo"].endswith("rebranded_product.png")
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
            assert "rebranded_product.png" in names
            assert "selected_photo.json" in names
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
    # The separate paid rebranding edit is mocked too: this test only
    # checks conversion of a poster-stage quota error to HTTP 429.
    monkeypatch.setattr(main,"rebrand_selected_photo",
                        lambda *args,**kwargs:_png())
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



def test_transparent_vehicle_png_gets_a_clean_light_model_reference():
    cutout=Image.new("RGBA",(120,80),(0,0,0,0))
    for x in range(20,100):
        for y in range(20,61):
            cutout.putpixel((x,y),(225,30,30,255))
    raw=io.BytesIO()
    cutout.save(raw,"PNG")
    result=ai_poster_service._input_png(raw.getvalue(),"vehicle")
    with Image.open(result) as img:
        assert img.getpixel((0,0))==(245,247,250)
        red=img.getpixel((60,40))
        assert red[0]>200 and red[1]<70


@pytest.mark.parametrize(
    "format_key,native_size,target",
    [
        ("4x3", (1536, 1024), (1440, 1080)),
        ("9x16", (1024, 1536), (1080, 1920)),
    ],
)
def test_full_ai_poster_never_crops_left_right_or_distorts(
        format_key, native_size, target):
    """Model draws content near native edges; nothing may be cut off.

    Old ImageOps.fit cut 11.1%/15.6% of horizontal artwork. This
    deterministically checks the exact edges of both native API ratios.
    """
    from PIL import ImageDraw
    src = Image.new("RGB", native_size, (235, 235, 235))
    draw = ImageDraw.Draw(src)
    W, H = native_size
    draw.rectangle((0, 0, 45, H), fill=(245, 0, 0))
    draw.rectangle((W-46, 0, W-1, H), fill=(0, 0, 245))
    draw.rectangle((46, 0, W-47, 44), fill=(0, 230, 0))
    draw.rectangle((46, H-46, W-47, H-1), fill=(240, 210, 10))
    output = ai_poster_service.preserve_artwork_without_crop(src, target)
    assert output.size == target
    mid = target[1] // 2
    assert output.getpixel((8, mid))[0] > 200, "Left logo/label was cropped"
    assert output.getpixel((target[0]-9, mid))[2] > 200, "Right price/headline was cropped"
    assert output.getpixel((target[0]//2, 3))[1] > 160, "Top bleed lost poster colors"
    assert output.getpixel((target[0]//2, target[1]-4))[0] > 170, "Bottom bleed lost poster colors"
    assert target[0]/target[1] in (4/3, 9/16)


def test_image_prompt_never_requests_aspect_ratio_crop():
    brief = default_brief()
    for fmt in ("4x3", "9x16"):
        prompt = ai_poster_service._prompt(
            brief, fmt, logo=False, drawing=False, reference=False)
        assert "WITHOUT CROPPING OR STRETCHING" in prompt
        assert "central 78%" not in prompt
        assert "central 88%" not in prompt


def test_4x3_ai_prompt_protects_logo_from_trailer_overlap():
    """The paid full-Images engine must give a logo its own safe zone."""
    p = ai_poster_service._prompt(
        default_brief(), "4x3", logo=True, drawing=False, reference=False
    ).lower()
    assert "protected branding zone in the top-left" in p
    assert "logo must remain fully visible" in p
    assert "trailer must never overlap the logo area" in p
    assert "not oversized" in p
    assert "right-side specifications panel" in p
    assert "bottom price / cta strip" in p
    assert "trailer must not enter the top-left protected brand zone" in p
    assert "not a request for rigid ui boxes or a template" in p
    assert "first source image is the real product" in p


def test_9x16_ai_prompt_protects_header_and_whole_vehicle():
    p = ai_poster_service._prompt(
        default_brief(), "9x16", logo=True, drawing=True, reference=False
    ).lower()
    assert "protected branding/header zone at the top" in p
    assert "logo must remain fully visible" in p
    assert "vehicle must not overlap the brand zone" in p
    assert "every wheel, axle and extremity" in p
    assert "bottom price / cta strip" in p
    assert "outside the right specifications" not in p
    assert "without cropping or stretching" in p


def test_both_paid_image_edit_requests_include_safe_layout_not_old_cache(
        monkeypatch, tmp_path):
    """Verify the actual model calls, not merely an unused prompt helper."""
    images = Images()
    monkeypatch.setattr(
        ai_poster_service, "client",
        lambda: type("API", (), {"images": images})()
    )
    ai_poster_service.generate_full_posters(
        default_brief(), _png(), logo=_png("white"),
        cache_dir=tmp_path / "safe_brand_test",
    )
    assert len(images.calls) == 2
    assert "v4-rebranded-hero" in ai_poster_service.VERSION
    landscape, portrait = [call["prompt"].lower() for call in images.calls]
    assert "trailer must never overlap the logo area" in landscape
    assert "protected branding/header zone at the top" in portrait
    assert "logo must remain fully visible" in landscape
    assert "logo must remain fully visible" in portrait
    assert images.calls[0]["size"] == "1536x1024"
    assert images.calls[1]["size"] == "1024x1536"
