"""User-oriented browser UI contract: a compact composer, not a wizard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
JS = (ROOT / 'app/static/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')


def test_compact_composer_is_default():
    assert 'class="composer"' in HTML
    assert 'id="hero-drop"' in HTML
    for element_id in ('model','slogan','design-notes','generate-btn','error-box','modebanner','loading'):
        assert f'id="{element_id}"' in HTML
    assert '<details id="advanced-settings" class="advanced">' in HTML
    assert 'data-go-step=' not in HTML
    assert 'id="step-1"' not in HTML
    assert 'setStep(' not in JS


def test_backend_contract_fields_still_exist():
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


def test_accessibility_and_responsive_uploads():
    assert 'aria-label="Основное фото товара"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'data-style="industrial"' in HTML
    assert 'data-style="graphite"' in HTML
    assert 'data-style="minimal"' in HTML
    assert "addEventListener('drop'" in JS
    assert 'new DataTransfer()' in JS
    assert 'validateFiles()' in JS
    assert '@media (max-width:700px)' in CSS
    assert '@media (max-width:460px)' in CSS
    assert 'prefers-reduced-motion:reduce' in CSS
    assert '[hidden]{display:none!important}' in CSS


def test_downloads_only_after_generation_and_never_preview():
    assert '<img ' not in HTML
    for field in ('preview-4x3','preview-9x16'):
        assert f'id="{field}"' not in HTML
        assert field not in JS
    for element in ('download-panel','download-all','download-4x3','download-9x16'):
        assert f'id="{element}"' in HTML
    assert 'id="download-panel" class="download-panel" hidden' in HTML
    assert "$('download-panel').hidden=false;" in JS
    assert "$('download-panel').hidden=true;" in JS
    assert 'latest=null;' in JS


def test_demo_and_billable_api_must_be_opted_into():
    assert 'async function resetDemo()' in JS
    assert 'resetDemo();' not in JS.split('async function init()',1)[1]
    assert "$('use-openai').disabled=!apiReady" in JS
    assert "if(checked('use-openai')&&!apiReady)" in JS
    assert 'Два платных запроса' in HTML
    assert 'if(!get(\'model\').trim())' in JS
    assert 'if(!checked(\'use-openai\')&&!$(\'hero\').files.length&&!checked(\'use-demo\'))' in JS
