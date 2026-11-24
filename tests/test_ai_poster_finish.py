"""Network-free regressions for masked generative expansion and local repair."""
import base64
import io

import pytest
from PIL import Image,ImageChops,ImageDraw

from app import ai_poster_finish as finish
from app.ai_artwork_fit import artwork_geometry,fit_complete_artwork,MATTE_RGB


def _source(size):
    image=Image.new("RGB",size,(80,110,140))
    draw=ImageDraw.Draw(image)
    draw.rectangle((size[0]//4,size[1]//4,size[0]//2,size[1]//2),fill=(210,20,30))
    return image


def _mock_api(monkeypatch,tmp_path,*,flat=False,wrong_size=False):
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    calls=[]
    class Images:
        def edit(self,**kw):
            with Image.open(kw["image"]) as im:
                size=im.size
            with Image.open(kw["mask"]) as mask:
                alpha=mask.getchannel("A")
                assert mask.size==size
                assert alpha.getextrema()==(0,255)
                calls.append({"size":size,"mask":alpha.copy(),"prompt":kw["prompt"]})
            assert kw["size"]==f"{size[0]}x{size[1]}"
            if wrong_size:
                size=(420,270)
            # Deliberately replace ALL pixels, including the protected region.
            # The application's composition must restore the untouched source.
            im=Image.new("RGB",size,MATTE_RGB if flat else (75,105,135))
            if not flat:
                draw=ImageDraw.Draw(im)
                for y in range(size[1]):
                    draw.line((0,y,size[0]-1,y),fill=(75+y%17,105+y%23,135+y%29))
                for x in range(0,size[0],9):
                    draw.line((x,0,x,size[1]-1),fill=(95,120,150))
            buff=io.BytesIO()
            im.save(buff,"PNG")
            return type("Reply",(),{"data":[type("Datum",(),{
                "b64_json":base64.b64encode(buff.getvalue()).decode()})()]})()
    monkeypatch.setattr(finish,"client",lambda:type("API",(),{"images":Images()})())
    return calls


@pytest.mark.parametrize("native,target",[
    ((1536,1024),(1440,1080)),((1024,1536),(1080,1920)),
    ((1024,1024),(1440,1080)),
])
def test_outpaint_preserves_every_content_pixel_and_exact_size(monkeypatch,tmp_path,native,target):
    calls=_mock_api(monkeypatch,tmp_path)
    source=fit_complete_artwork(_source(native),target)
    geometry=artwork_geometry(native,target)
    box=tuple(geometry["content_box"])
    first,report=finish.expand_artwork(source,box,model="gpt-image-2.5-flare",quality="medium")
    assert report["status"]=="complete"
    assert first.size==target
    assert ImageChops.difference(first.crop(box),source.crop(box)).getbbox() is None
    assert ImageChops.difference(first,source).getbbox() is not None
    for entry in report["generated_bands"]:
        assert first.crop(tuple(entry["box"])).getextrema()!=tuple((v,v) for v in MATTE_RGB)
    second,again=finish.expand_artwork(source,box,model="gpt-image-2.5-flare",quality="medium")
    assert again==report and ImageChops.difference(first,second).getbbox() is None
    assert len(calls)==1


@pytest.mark.parametrize("flat,wrong_size",[(True,False),(False,True)])
def test_failed_outpaint_keeps_paid_source_and_no_automatic_repurchase(monkeypatch,tmp_path,flat,wrong_size):
    calls=_mock_api(monkeypatch,tmp_path,flat=flat,wrong_size=wrong_size)
    source=fit_complete_artwork(_source((1024,1536)),(1080,1920))
    geometry=artwork_geometry((1024,1536),source.size)
    for _ in range(2):
        final,report=finish.try_expand_artwork(source,geometry,model="gpt-image-2.5-flare",quality="medium")
        assert report["status"]=="failed"
        assert ImageChops.difference(final,source).getbbox() is None
    assert len(calls)==1


def test_local_repair_preserves_every_pixel_outside_rectangle(monkeypatch,tmp_path):
    calls=_mock_api(monkeypatch,tmp_path)
    source=_source((1080,1920))
    region=(800,1280,1040,1510)
    final,report=finish.repair_artwork(source,region,"Исправить число: 240",
                                      model="gpt-image-2.5-flare",quality="medium")
    assert report["status"]=="complete" and final.size==source.size
    diff=ImageChops.difference(final,source)
    assert diff.getbbox()==region
    assert len(calls)==1
    assert "LOCAL MASKED CORRECTION" in calls[0]["prompt"]
    assert calls[0]["mask"].getpixel((0,0))==255


def test_no_purchase_for_exact_size_or_invalid_region(monkeypatch,tmp_path):
    calls=_mock_api(monkeypatch,tmp_path)
    source=_source((1440,1080))
    final,report=finish.expand_artwork(source,(0,0,1440,1080),
                                       model="gpt-image-2.5-flare",quality="medium")
    assert report["status"]=="not_needed"
    assert ImageChops.difference(source,final).getbbox() is None
    with pytest.raises(ValueError):
        finish.repair_artwork(source,(-1,0,500,500),"fix",model="gpt-image-2.5-flare",quality="medium")
    with pytest.raises(ValueError):
        finish.repair_artwork(source,(0,0,1440,1080),"fix",model="gpt-image-2.5-flare",quality="medium")
    assert not calls
