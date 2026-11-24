"""No-credit reproduction of the user's first-artwork APIConnectionError.

The uploaded recovery ZIP confirmed a successful rebrand and complete
technical sheet, but no ai_template_4x3.png. Neither the ZIP nor the old
status recorded the underlying socket/timeout reason. Keep SDK messages
private and never automatically replay an uncertain paid Images request.
"""
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from io import BytesIO

from app.ai_transport import OpenAIImageConnectionFailure, connection_report
from app import ai_exact_copy_template as workflow


def _png(size=(350,200)):
    buf=BytesIO()
    Image.new("RGB",size,"white").save(buf,format="PNG")
    return buf.getvalue()


def _fake_error(kind, root, secret="PRIVATE-SDK-MESSAGE-NEVER-SHARE"):
    wrapper=type(kind,(Exception,),{})
    underlying=type(root,(Exception,),{})
    exception=wrapper(secret)
    exception.__cause__=underlying(secret)
    return exception


@pytest.mark.parametrize("root,expected",[
    ("ReadTimeout","read_timeout"),
    ("ConnectTimeout","connect_timeout"),
    ("gaierror","dns"),
    ("SSLCertVerificationError","tls"),
    ("ProxyError","proxy"),
    ("RemoteProtocolError","connection_reset"),
    ("ConnectError","connect_error"),
])
def test_classify_transport_without_raw_sdk_text(root,expected):
    err=_fake_error("APIConnectionError",root)
    report=connection_report(err,format_name="4x3",started_at=0.0)
    assert report is not None
    assert report["reason_code"]==expected
    assert report["format"]=="4x3"
    assert report["automatic_retry"] is False
    assert report["billing_uncertain"] is True
    assert "PRIVATE-SDK" not in json.dumps(report,ensure_ascii=False)


def test_api_timeout_is_classified_without_exposing_error_details():
    err=_fake_error("APITimeoutError","ReadTimeout")
    report=connection_report(err,format_name="9x16",started_at=0)
    assert report["reason_code"]=="read_timeout"
    assert report["sdk_exception"]=="APITimeoutError"
    assert connection_report(
        ValueError("unrelated"),format_name="4x3",started_at=0) is None


def test_image_call_does_not_retry_and_writes_safe_recovery_diagnostic(
        tmp_path,monkeypatch):
    count=[]
    error=_fake_error("APIConnectionError","ReadTimeout")
    def edit(**kwargs):
        count.append(kwargs)
        raise error
    api=SimpleNamespace(images=SimpleNamespace(edit=edit))
    monkeypatch.setenv("PROMO_OPENAI_ART_TIMEOUT_SECONDS","480")
    with pytest.raises(OpenAIImageConnectionFailure) as caught:
        workflow._edit_artwork(
            api,"4x3",output_dir=tmp_path,
            model="mock",image=[object()],prompt="PRIVATE PROMPT",
            size="1536x1024",quality="medium",output_format="png",
        )
    assert len(count)==1, "Paid image connection errors must not auto-retry"
    assert count[0]["timeout"]==480
    report=json.loads(
        (tmp_path/"openai_connection_diagnostic.json").read_text())
    assert report["reason_code"]=="read_timeout"
    assert report["phase"]=="paid_artwork_images_edit"
    assert report["billing_uncertain"] is True
    raw=json.dumps(report,ensure_ascii=False)
    assert "PRIVATE PROMPT" not in raw
    assert "PRIVATE-SDK-MESSAGE" not in raw
    assert "PRIVATE-SDK-MESSAGE" not in str(caught.value)


def test_image_timeout_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv("PROMO_OPENAI_ART_TIMEOUT_SECONDS","2")
    assert workflow._artwork_timeout_seconds()==180
    monkeypatch.setenv("PROMO_OPENAI_ART_TIMEOUT_SECONDS","9999")
    assert workflow._artwork_timeout_seconds()==600
    monkeypatch.setenv("PROMO_OPENAI_ART_TIMEOUT_SECONDS","unrecognized")
    assert workflow._artwork_timeout_seconds()==480


def test_main_recovery_zip_includes_safe_reason_and_saved_rebrand(
        monkeypatch,tmp_path):
    from app import main
    monkeypatch.setenv("PROMO_DATA_DIR",str(tmp_path))
    monkeypatch.setattr(main,"STORAGE",tmp_path)
    chosen=_png()
    monkeypatch.setattr(main,"cached_rebrand_photo",lambda folder: chosen)
    expected=connection_report(
        _fake_error("APIConnectionError","ReadTimeout"),
        format_name="4x3",started_at=0)
    def render(*args,**kwargs):
        folder=kwargs["output_dir"]
        (folder/"openai_connection_diagnostic.json").write_text(
            json.dumps(expected,ensure_ascii=False))
        raise OpenAIImageConnectionFailure(expected)
    monkeypatch.setattr(main,"generate_exact_typography_posters",render)
    brief={
        "brand":"TEST","model":"Demo product","specs":[],
        "dimensions":[],"price":"1234","currency":"BYN",
    }
    with pytest.raises(main.PartialPosterFailure) as caught:
        main._exact_typography_posters_sync(
            brief,chosen,None,None,None,"gpt-image-2.5-flare","medium",
        )
    err=caught.value
    assert err.cause_type=="OpenAIImageConnectionFailure"
    assert "ожидание ответа" in err.public_reason
    jobid=err.recovery_zip.split("/")[2]
    with zipfile.ZipFile(tmp_path/jobid/"ai_failed_generation.zip") as z:
        assert "rebranded_product.png" in z.namelist()
        assert "openai_connection_diagnostic.json" in z.namelist()
        assert json.loads(z.read("brief.json"))==brief
        report=json.loads(z.read("openai_connection_diagnostic.json"))
        assert report["reason_code"]=="read_timeout"
        readme=z.read("READ_ME_FIRST.txt").decode("utf-8")
        assert "Безопасная диагностика" in readme
        assert "списание" in readme
        assert "PRIVATE-SDK-MESSAGE" not in readme


def test_staging_preflight_rejects_no_outbound_https_without_using_key():
    root=Path(__file__).resolve().parents[1]
    stage=root/"deploy/time4vps/stage_exact_copy_review.sh"
    check=root/"deploy/time4vps/diagnose_openai_network.sh"
    for path in (stage,check):
        subprocess.run(["bash","-n",str(path)],check=True)
    script=stage.read_text(encoding="utf-8")
    assert "api.openai.com/v1/models" in script
    assert "No paid requests made" in script
    assert '[[ "$api_status" == "401" ]]' in script
    assert script.index("did not return expected HTTP 401")<script.index(
        'install -d -o promoeditor -g promoeditor -m 0700 "$STAGE"'
    )
    free=check.read_text(encoding="utf-8")
    assert "api.openai.com/v1/models" in free
    assert "OPENAI_API_KEY" not in free
    assert "systemctl stop" not in free
    assert "systemctl restart" not in free



def test_native_paid_portrait_network_failure_has_recovery_zip_and_reuses_landscape(
        monkeypatch, tmp_path):
    import base64
    from app import ai_poster_service, main, product_rebrand_service
    from app.render import default_brief
    monkeypatch.setenv("PROMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    calls = []
    failed = [True]
    png = _png()
    def edit(**kwargs):
        calls.append(kwargs["size"])
        assert kwargs["timeout"] >= 180
        if kwargs["size"] == "1152x2048" and failed[0]:
            raise _fake_error("APIConnectionError", "ReadTimeout")
        return SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(_png(tuple(map(int,kwargs["size"].split("x"))))).decode("ascii"))])
    api = SimpleNamespace(images=SimpleNamespace(edit=edit))
    monkeypatch.setattr(ai_poster_service, "client", lambda: api)
    monkeypatch.setattr(product_rebrand_service, "client", lambda: api)
    args = (default_brief(), png, None, None, None, "gpt-image-2.5-flare", "medium")
    with pytest.raises(main.PartialPosterFailure) as error:
        main._full_posters_sync(*args)
    assert len(calls) == 3
    job = error.value.recovery_zip.split("/")[2]
    with zipfile.ZipFile(tmp_path/job/"ai_failed_generation.zip") as archive:
        assert "rebranded_product.png" in archive.namelist()
        assert "native_ai_artwork_4x3.png" in archive.namelist()
        assert "native_ai_artwork_9x16.png" not in archive.namelist()
        diagnostic = json.loads(archive.read("openai_connection_diagnostic.json"))
        assert diagnostic["reason_code"] == "read_timeout"
        assert diagnostic["format"] == "9x16"
        assert b"PRIVATE-SDK-MESSAGE" not in archive.read("READ_ME_FIRST.txt")
    failed[0] = False
    assert main._full_posters_sync(*args)["raster_only"]
    assert len(calls) == 4, "Only the failed portrait is retried on explicit user action"
    assert calls[-1] == "1152x2048"
