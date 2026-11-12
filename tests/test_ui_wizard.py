"""Top-level design navigation: protected Caddy pages must never be embedded."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

ROOT=Path(__file__).resolve().parents[1]/'app'/'static'
VARIANTS=('wizard','studio','compact','dialog')
CONTROLS=('hero','detail','logo','drawing','references','documents','parse-ai',
          'inspect-btn','extract-result','apply-extracted','brand','model','category',
          'slogan','claims','specs','benefits','dimensions','price','currency','vat',
          'phones','show-roi','extra-payload','distance','rate','trips','years',
          'baseline-price','style','accent','design-notes','use-openai','image-model',
          'image-quality','use-demo')
client=TestClient(app)

def test_main_page_links_to_real_top_level_designs_not_iframes():
    shell=client.get('/').text
    assert 'window.location.replace' in shell
    assert '<iframe' not in shell.lower()
    for name in VARIANTS:
        assert f'/static/designs/{name}/index.html' in shell
        for asset in ('index.html','app.js','app.css'):
            assert client.get(f'/static/designs/{name}/{asset}').status_code==200

def test_four_preserved_layouts_run_in_top_level_document():
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
        assert '/static/design-switcher.js?v=' in html
        assert '/static/design-switcher.css?v=' in html
        assert 'id="preview-4x3"' not in html
        assert 'id="preview-9x16"' not in html
        assert 'id="download-panel"' in html

def test_state_transfer_keeps_files_only_in_temporary_indexeddb():
    js=(ROOT/'design-switcher.js').read_text(encoding='utf-8')
    for fragment in ('window.location.assign(', 'window.indexedDB.open',
                     'storeFiles(token,draft.uploads)', 'await takeFiles(data.token)',
                     'new DataTransfer()', 'el.files=transfer.files',
                     'window.sessionStorage.setItem(TRANSFER',
                     'window.sessionStorage.removeItem(TRANSFER)',
                     'window.PromoEditorVariant?.getResult?.()',
                     'window.PromoEditorVariant?.restoreResult?.(data.result)',
                     'window.PromoEditorVariant?.busy?.()'):
        assert fragment in js
    assert 'iframe' in js.lower() # comment explicitly explains iframe removal
    assert 'frame.srcdoc=' not in js
    assert 'localStorage.setItem(PREF,JSON' not in js
    assert '<iframe' not in (ROOT/'index.html').read_text(encoding='utf-8').lower()

def test_backend_unchanged_and_downloads_present():
    assert client.get('/api/config').status_code==200
    assert client.get('/api/demo').status_code==200
    for name in VARIANTS:
        js=(ROOT/'designs'/name/'app.js').read_text(encoding='utf-8')
        for cid in ('download-all','download-4x3','download-9x16'):
            assert cid in js
        assert 'promoeditor:result' in js

def test_dialog_remains_distinct():
    html=(ROOT/'designs'/'dialog'/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'designs'/'dialog'/'app.css').read_text(encoding='utf-8')
    for sec in ('conversation-product','conversation-files','conversation-idea','conversation-style'):
        assert f'id="{sec}"' in html
    assert 'class="conversation"' in html
    assert 'color-scheme:dark' in css
    assert '@media(max-width:620px)' in css
