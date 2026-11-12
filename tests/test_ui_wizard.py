"""User-facing switcher for the three preserved historical layouts (PR4, PR5, PR6)."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

ROOT=Path(__file__).resolve().parents[1]/"app"/"static"
VARIANTS=("wizard","studio","compact")
CONTROLS=('hero','detail','logo','drawing','references','documents','parse-ai',
          'inspect-btn','extract-result','apply-extracted','brand','model','category',
          'slogan','claims','specs','benefits','dimensions','price','currency','vat',
          'phones','show-roi','extra-payload','distance','rate','trips','years',
          'baseline-price','style','accent','design-notes','use-openai','image-model',
          'image-quality','use-demo')
client=TestClient(app)

def test_all_design_versions_are_routed_and_loaded():
    shell=client.get('/').text
    assert 'role="tablist"' in shell
    assert 'design-switcher.js' in shell
    assert 'id="frame-compact"' in shell
    for name in VARIANTS:
        assert f'data-variant="{name}"' in shell
        assert f'data-layout="{name}"' in shell
        assert f'src="/static/designs/{name}/index.html"' not in shell
        for asset in ('index.html','app.js','app.css'):
            assert client.get(f'/static/designs/{name}/{asset}').status_code==200

def test_archived_layouts_keep_original_controls_and_api_routes():
    for name in VARIANTS:
        html=(ROOT/'designs'/name/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'designs'/name/'app.js').read_text(encoding='utf-8')
        for cid in CONTROLS:
            assert f'id="{cid}"' in html,(name,cid)
        assert "fetch('/api/generate'" in js
        assert "fetch('/api/inspect'" in js
        assert 'window.PromoEditorVariant' in js
        assert 'restoreResult:' in js
        assert f'/static/designs/{name}/app.js' in html
        assert f'/static/designs/{name}/app.css' in html
        assert 'href="/" target="_top"' in html
        assert 'id="preview-4x3"' not in html
        assert 'id="preview-9x16"' not in html
        assert 'id="download-panel"' in html
        assert 'id="download-all"' in html

def test_shared_files_and_results_are_transferred_without_persisting_brief_to_storage():
    js=(ROOT/'design-switcher.js').read_text(encoding='utf-8')
    for fragment in ('new DataTransfer()','el.files=transfer.files',
                     'el.checked=field.checked','el.value=field.value',
                     'getResult()','restoreResult(result)','result=event.data.result',
                     'localStorage.setItem(STORE_KEY,next)'):
        assert fragment in js
    assert 'localStorage.setItem(STORE_KEY,JSON' not in js
    assert "snapshot=readState(previous)" in js
    assert "PromoEditorVariant.busy()" in js
    assert 'frame.srcdoc=markup' in js
    assert "credentials:'same-origin'" in js
    assert 'src="/static/designs/' not in (ROOT/'index.html').read_text(encoding='utf-8')
    assert "promoeditor:cleared" in js

def test_backend_and_downloads_stay_original():
    assert client.get('/api/config').status_code==200
    assert client.get('/api/demo').status_code==200
    for name in VARIANTS:
        js=(ROOT/'designs'/name/'app.js').read_text(encoding='utf-8')
        for cid in ('download-all','download-4x3','download-9x16'):
            assert cid in js
        assert 'promoeditor:result' in js
        assert 'promoeditor:cleared' in js
