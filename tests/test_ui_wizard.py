"""Regression tests for the human-friendly 3-step editor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
JS = (ROOT / 'app/static/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')


def test_three_steps_have_accessible_navigation_and_feedback():
    for n in range(1, 4):
        assert f'id="step-{n}"' in HTML
        assert f'data-go-step="{n}"' in HTML
    for element_id in ('next-btn', 'back-btn', 'generate-btn', 'step-counter',
                       'progress-fill', 'error-box', 'loading', 'modebanner'):
        assert f'id="{element_id}"' in HTML
    assert 'aria-current="step"' in HTML
    assert 'function setStep(' in JS
    assert 'No automatic test brief' in JS


def test_input_ids_match_form_and_backend_contract():
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


def test_no_preview_and_downloads_only_on_success():
    assert 'id="preview-4x3"' not in HTML
    assert 'id="preview-9x16"' not in HTML
    assert '<img ' not in HTML
    for element_id in ('download-panel','download-4x3','download-9x16','download-all'):
        assert f'id="{element_id}"' in HTML
    assert '<section id="download-panel" class="result-card" hidden' in HTML
    assert "$('download-panel').hidden=false;" in JS
    assert "$('download-panel').hidden=true;" in JS


def test_mobile_responsive_and_hidden_states():
    assert '@media (max-width:600px)' in CSS
    assert '.workspace{grid-template-columns:1fr;' in CSS
    assert '[hidden]{display:none!important}' in CSS
    assert 'prefers-reduced-motion:reduce' in CSS
