"""Contract tests for the isolated editable finished-promo workspace."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)
ROOT=Path(__file__).resolve().parents[1]/'app'/'static'

def test_edit_workspace_is_collapsed_and_does_not_show_generated_previews():
    html=client.get('/').text
    assert 'id="edit-section"' in html
    assert 'id="edit-body" hidden' in html
    assert 'id="edit-workspace" class="edit-workspace" hidden' in html
    assert 'id="edit-canvas"' in html
    assert 'src="/static/editor.js?v=' in html
    assert 'href="/static/editor.css?v=' in html
    assert 'id="preview-4x3"' not in html
    assert 'id="preview-9x16"' not in html

def test_edit_all_tools_are_present():
    html=client.get('/').text
    controls=['edit-open-landscape','edit-open-portrait','edit-open-file',
      'edit-project-file','edit-add-text','edit-text-input','edit-text-size',
      'edit-text-color','edit-overlay-file','edit-cover-color','edit-canvas',
      'edit-selected-text','edit-layer-width','edit-layer-height','edit-delete-layer',
      'edit-bring-forward','edit-undo','edit-redo','edit-download',
      'edit-save-project','edit-ai-prompt','edit-ai-quality','edit-run-ai',
      'edit-clear-region']
    for cid in controls:
        assert f'id="{cid}"' in html,cid
    for tool in ('select','cover','region'):
        assert f'data-edit-tool="{tool}"' in html

def test_editor_runs_locally_unless_user_explicitly_confirms_ai_edit():
    script=(ROOT/'editor.js').read_text(encoding='utf-8')
    generator=(ROOT/'app.js').read_text(encoding='utf-8')
    assert "window.dispatchEvent(new CustomEvent('promoeditor:generated'" in generator
    assert "window.addEventListener('promoeditor:generated'" in script
    assert "window.confirm(" in script
    assert "fetch('/api/edit'" in script
    assert "form.append('mask',blob,'region.png')" in script
    assert "mask.toBlob" in script
    assert "canvas.toBlob" in script
    assert "function saveProject()" in script
    assert "function openProject(file)" in script
    assert "STATE.layers" in script
    assert "history" in script and "future" in script
    assert "api_key" not in script.lower()
    assert 'window.PromoEditorVariant' not in script

def test_editor_api_only_permits_expected_saved_filename():
    assert client.get('/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/edit.png').status_code==404
    assert client.get('/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/secret.txt').status_code==404
    assert client.get('/api/config').status_code==200
    assert '/api/edit' in {route.path for route in app.routes}
