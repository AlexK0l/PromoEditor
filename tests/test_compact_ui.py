"""The application uses only the compact PromoEditor form."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

ROOT=Path(__file__).resolve().parents[1]/'app'/'static'
client=TestClient(app)
CONTROLS=(
    'hero','detail','logo','drawing','references','documents','parse-ai',
    'inspect-btn','extract-result','apply-extracted','brand','model','category',
    'slogan','claims','specs','benefits','dimensions','price','currency','vat',
    'phones','show-roi','extra-payload','distance','rate','trips','years',
    'baseline-price','style','accent','design-notes','design-actions','use-openai','image-model',
    'image-quality','use-demo',
)

def test_compact_editor_is_the_only_home_page():
    html=client.get('/').text
    assert 'class="composer"' in html
    assert 'id="hero-drop"' in html
    assert '<details id="advanced-settings" class="advanced">' in html
    assert 'window.location.replace' not in html
    assert 'design-switcher' not in html
    assert 'role="tablist"' not in html
    assert '<iframe' not in html
    assert 'id="generate-btn"' in html
    assert 'id="modebanner"' in html

def test_file_and_brief_fields_are_preserved():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    script=(ROOT/'app.js').read_text(encoding='utf-8')
    for cid in CONTROLS:
        assert f'id="{cid}"' in html,cid
    assert "fetch('/api/generate'" in script
    assert "fetch('/api/inspect'" in script
    assert 'formBrief()' in script
    assert 'validateFiles()' in script
    assert 'new DataTransfer()' in script
    assert 'design-switcher' not in script
    assert 'window.PromoEditorVariant' not in script

def test_single_page_has_styles_accessibility_and_downloads():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'app.css').read_text(encoding='utf-8')
    js=(ROOT/'app.js').read_text(encoding='utf-8')
    assert 'aria-label="Фотографии товара, можно выбрать несколько"' in html
    assert 'aria-live="polite"' in html
    for style in ('industrial','graphite','minimal'):
        assert f'data-style="{style}"' in html
    for cid in ('download-panel','download-4x3','download-9x16','download-all'):
        assert f'id="{cid}"' in html
        assert cid in js
    assert 'id="download-panel" class="download-panel" hidden' in html
    assert "$('download-panel').hidden=false;" in js
    assert "$('download-panel').hidden=true;" in js
    assert '@media (max-width:700px)' in css
    assert '@media (max-width:460px)' in css
    assert 'prefers-reduced-motion:reduce' in css
    assert 'id="preview-4x3"' not in html
    assert 'id="preview-9x16"' not in html

def test_example_and_paid_api_are_opt_in_only():
    js=(ROOT/'app.js').read_text(encoding='utf-8')
    assert 'async function resetDemo()' in js
    assert 'resetDemo();' not in js.split('async function init()',1)[1]
    assert "$('use-openai').disabled=!apiReady" in js
    assert "if(checked('use-openai')&&!apiReady)" in js
    assert "if(!get('model').trim())" in js
    assert 'id="use-openai"' in client.get('/').text
    assert 'id="design-actions"' in client.get('/').text
    assert "design_actions:get('design-actions').trim()" in js

def test_old_design_files_not_shipped():
    assert not (ROOT/'designs').exists()
    assert not (ROOT/'design-switcher.js').exists()
    assert not (ROOT/'design-switcher.css').exists()
    assert client.get('/api/config').status_code==200
