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


def _png(color="red", size=(640,420)):
    file=io.BytesIO()
    Image.new("RGB", size, color).save(file, "PNG")
    return file.getvalue()


class Images:
    def __init__(self, fail_portrait=False, wrong_size=False):
        self.calls=[]
        self.fail_portrait=fail_portrait
        self.wrong_size=wrong_size

    def edit(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_portrait and kwargs["size"]=="1152x2048":
            raise RuntimeError("simulated second API failure")
        size=(640,420) if self.wrong_size else tuple(map(int,kwargs["size"].split("x")))
        encoded=base64.b64encode(_png(size=size)).decode("ascii")
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
    assert images.calls[0]["size"]=="1536x1152"
    assert images.calls[1]["size"]=="1152x2048"
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
            data={"payload":json.dumps(default_brief(),ensure_ascii=False),
                  "expand_posters":"true"},  # stale clients must not buy outpainting
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
            readme=z.read("REVIEW_BEFORE_PUBLICATION.txt").decode("utf8")
            assert "OpenAI Images" in readme
            assert "SVG" in readme
            assert "approved_copy.json" in z.namelist()
            review=json.loads(z.read("poster_review.json"))
            assert review["status"]=="not_requested"
            assert review["human_review_required"] is True
            geometry=json.loads(z.read("export_geometry.json"))
            assert all(not info["crop"] for info in geometry.values())
            assert geometry==result["export_geometry"]
            from PIL import ImageChops
            for fmt,(target,api_size) in ai_poster_service.FORMATS.items():
                g=geometry[fmt]
                assert g["source_size"]==list(map(int,api_size.split("x")))
                assert g["content_box"]==[0,0,*target]
                assert g["outpaint"]["status"]=="not_needed"
                assert g["generation"]=="native_target_aspect"
                with Image.open(io.BytesIO(z.read(f"native_ai_artwork_{fmt}.png"))) as native:
                    with Image.open(io.BytesIO(z.read(f"ai_poster_{fmt}.png"))) as final:
                        assert ImageChops.difference(final,native.resize(target,Image.Resampling.LANCZOS)).getbbox() is None
            assert [call["size"] for call in images.calls[-2:]]==["1536x1152","1152x2048"]


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
    Image.new("RGB",(1536,1152),"red").save(cache/"4x3.png","PNG")
    images=Images()
    monkeypatch.setattr(ai_poster_service,"client",
                        lambda:type("API",(),{"images":images})())
    out=ai_poster_service.generate_full_posters(
        default_brief(),_png(),cache_dir=cache)
    assert out["4x3"].size==(1440,1080)
    assert out["9x16"].size==(1080,1920)
    assert len(images.calls)==1
    assert images.calls[0]["size"]=="1152x2048"



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
    "native_size,target,box",
    [
        ((1536,1152), (1440,1080), [0,0,1440,1080]),
        ((1152,2048), (1080,1920), [0,0,1080,1920]),
        ((1536, 1024), (1440, 1080), [0,60,1440,1020]),
        ((1024, 1536), (1080, 1920), [0,150,1080,1770]),
        ((1080,1920), (1080,1920), [0,0,1080,1920]),
        ((1024,1024), (1440,1080), [180,0,1260,1080]),
    ],
)
def test_complete_ai_raster_is_preserved_in_exact_output(native_size,target,box):
    """Customer's actual CTA and telephone digits were cut off at both sides."""
    from PIL import ImageChops, ImageDraw
    from app.ai_artwork_fit import artwork_geometry, MATTE_RGB
    src=Image.new("RGB",native_size,(235,235,235))
    w,h=src.size
    pen=ImageDraw.Draw(src)
    # Non-disposable left/right text-like blocks and distinct edge rows.
    pen.rectangle((0,0,80,h-1),fill=(240,0,0))
    pen.rectangle((w-80,0,w-1,h-1),fill=(0,0,240))
    pen.rectangle((0,0,w-1,16),fill=(25,50,75))
    pen.rectangle((0,h-17,w-1,h-1),fill=(20,100,30))
    result=ai_poster_service.finish_artwork_in_safe_aspect(src,target)
    report=artwork_geometry(native_size,target)
    assert report["crop"] is False
    assert report["content_box"] == box
    assert result.size == target
    x,y,r,b=box
    expected=src.resize((r-x,b-y),Image.Resampling.LANCZOS)
    assert ImageChops.difference(result.crop(tuple(box)),expected).getbbox() is None
    assert result.getpixel((x,(y+b)//2))==(240,0,0)
    assert result.getpixel((r-1,(y+b)//2))==(0,0,240)
    if y:
        assert result.crop((0,0,target[0],y)).getextrema()==tuple((c,c) for c in MATTE_RGB)
    if b<target[1]:
        assert result.crop((0,b,target[0],target[1])).getextrema()==tuple((c,c) for c in MATTE_RGB)


def test_ai_prompt_demands_full_native_canvas_and_no_fabricated_blueprint():
    brief=default_brief()
    for fmt in ("4x3","9x16"):
        prompt=ai_poster_service._prompt(brief,fmt,logo=False,drawing=True,reference=False)
        assert "no post-generation edge-row stretching" in prompt.lower()
        assert "no cropping" in prompt.lower()
        assert "3:2 or 2:3" not in prompt
        assert "FINAL aspect ratio" in prompt
        assert "no padding and no additional outpainting" in prompt
        assert "vertical pixel replication" in prompt
        assert "OUTER SIDE GUARD BANDS" not in prompt
        assert "preserve the whole native artwork" in prompt
        assert "NEVER redraw, reinterpret, relabel" in prompt
        assert "annual additional revenue" in prompt
        assert "difference in purchase price" in prompt
        assert "1536x1152" in prompt if fmt=="4x3" else "1152x2048" in prompt


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
    assert "preserve the whole native artwork" in p


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
    assert "full-image-no-crop" in ai_poster_service.VERSION
    assert ai_poster_service.VERSION != "full-openai-ad-poster-creative-v6-safe-crop-no-edge-extension"
    landscape, portrait = [call["prompt"].lower() for call in images.calls]
    assert "trailer must never overlap the logo area" in landscape
    assert "protected branding/header zone at the top" in portrait
    assert "logo must remain fully visible" in landscape
    assert "logo must remain fully visible" in portrait
    assert images.calls[0]["size"] == "1536x1152"
    assert images.calls[1]["size"] == "1152x2048"



def test_legacy_secondary_argument_never_reaches_images_or_changes_cache(monkeypatch,tmp_path):
    images=Images()
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(ai_poster_service,"client",lambda:type("API",(),{"images":images})())
    brief=default_brief()
    for alternate in (_png("red"),_png("blue")):
        ai_poster_service.generate_full_posters(brief,_png(),logo=_png("white"),
                                               secondary_photo=alternate,
                                               consume_cache=False,product_is_rebranded=True)
    assert len(images.calls)==2
    for call in images.calls:
        assert [f.name for f in call["image"]]==["01_real_product.png","02_logo.png"]
        assert "ONLY ONE AUTHORIZED PRODUCT VIEW" in call["prompt"]



def test_wrong_native_size_is_saved_and_never_automatically_rebought(monkeypatch,tmp_path):
    images=Images(wrong_size=True)
    monkeypatch.setattr(ai_poster_service,"client",lambda:type("API",(),{"images":images})())
    cache=tmp_path/"cache"
    for _ in range(2):
        with pytest.raises(ai_poster_service.NativePosterSizeMismatch) as error:
            ai_poster_service.generate_full_posters(default_brief(),_png(),cache_dir=cache)
        assert error.value.report=={"format":"4x3","requested_size":[1536,1152],
                                    "received_size":[640,420],"automatic_retry":False}
        assert (cache/"4x3.png").is_file()
        assert not (cache/"9x16.png").exists()
    assert len(images.calls)==1


def test_wrong_size_http_response_has_recovery_zip_not_a_padded_poster(monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","mock-no-network-key")
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    monkeypatch.setattr(main,"_guard_rate",lambda request:None)
    images=Images(wrong_size=True)
    monkeypatch.setattr(ai_poster_service,"client",lambda:type("API",(),{"images":images})())
    monkeypatch.setattr(product_rebrand_service,"client",lambda:type("API",(),{"images":images})())
    with TestClient(main.app) as http:
        for _ in range(2):
            result=http.post("/api/ai-posters",data={"payload":json.dumps(default_brief())},
                             files={"hero":("photo.png",_png(),"image/png")})
            assert result.status_code==502,result.text
            data=result.json()
            assert "1536×1152" in data["detail"]
            archive=http.get(data["recovery_zip"])
            assert archive.status_code==200
            with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
                assert json.loads(z.read("native_size_diagnostic.json"))["received_size"]==[640,420]
                assert "native_ai_artwork_4x3.png" in z.namelist()
                assert "ai_poster_4x3.png" not in z.namelist()
        assert len(images.calls)==2 # one rebrand and one paid wrong-size image
