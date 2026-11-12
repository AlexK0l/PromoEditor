"""UI contract: one-page composer, optional advanced settings, no poster preview."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
JS = (ROOT / 'app/static/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')


def test_one_page_composer_without_forced_wizard():
    assert 'id="hero-drop"' in HTML
    assert 'id="advanced-settings"' in HTML
    assert 'id="generate-btn"' in HTML
    assert 'id="error-box"' in HTML
    assert 'id="loading"' in HTML
    assert 'id="modebanner"' in HTML
    assert 'data-go-step' not in HTML
    assert 'id="step-1"' not in HTML
    assert 'next-btn' not in JS
    assert 'setStep(' not in JS


def test_required_api_contract_ids_preserved():
    controls = [
        'hero','detail','logo','drawing','references','documents','parse-ai',
        'inspect-btn','extract-result','apply-extracted','brand','model','category',
        'slogan','claims','specs','benefits','dimensions','price','currency','vat','phones',
        'show-roi','extra-payload','distance','rate','trips','years','baseline-price',
        'style','accent','design-notes','use-openai','image-model','image-quality','use-demo'
    ]
    for field in controls:
        assert f'id="{field}"' in HTML, f'Missing field {field}'
    assert "fetch('/api/generate'" in JS
    assert "fetch('/api/inspect'" in JS
    assert 'formBrief()' in JS


def test_optional_settings_and_file_access():
    assert '<details id="advanced-settings"' in HTML
    assert 'data-style="industrial"' in HTML
    assert 'data-style="graphite"' in HTML
    assert 'data-style="minimal"' in HTML
    assert "addEventListener('drop'" in JS
    assert 'new DataTransfer()' in JS
    assert 'validateFiles()' in JS
    assert 'max-width:600px' in CSS.replace(' ','')
    assert 'prefers-reduced-motion:reduce' in CSS
    assert '[hidden]{display:none!important}' in CSS


def test_no_layout_previews_download_after_generation():
    assert 'id="preview-4x3"' not in HTML
    assert 'id="preview-9x16"' not in HTML
    assert '<img ' not in HTML
    for element in ('download-panel','download-all','download-4x3','download-9x16'):
        assert f'id="{element}"' in HTML
    assert 'id="download-panel" class="download-panel" hidden' in HTML
    assert "$('download-panel').hidden=false;" in JS
    assert "$('download-panel').hidden=true;" in JS
    assert "latest=null;" in JS
    assert 'preview-4x3' not in JS


def test_api_and_demo_are_explicit_opt_in():
    assert 'async function resetDemo()' in JS
    assert 'resetDemo();' not in JS.split('async function init()',1)[1]
    assert 'if(checked(\'use-openai\')&&!apiReady)' in JS
    assert '2 платных запроса' in HTML
