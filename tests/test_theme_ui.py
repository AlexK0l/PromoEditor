"""Dark theme contract: protected app and public login share visual preferences."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import hash_password
from app.main import app

ROOT=Path(__file__).resolve().parents[1]/'app'/'static'
PASSWORD="TestStrongPass2026"

def test_theme_switcher_and_early_stylesheet_in_compact_editor():
    with TestClient(app) as client:
        r=client.get("/")
        assert r.status_code==200
        html=r.text
        assert '<script src="/static/theme.js?v=' in html
        assert '<link rel="stylesheet" href="/static/theme.css?v=' in html
        assert 'data-theme-toggle' in html
        assert 'data-theme-icon' in html and 'data-theme-label' in html
        assert html.index('<script src="/static/theme.js')<html.index('<link rel="stylesheet" href="/static/app.css')
        for path in ('/static/theme.js','/static/theme.css'):
            assert client.get(path).status_code==200

def test_login_can_get_theme_script_without_opening_other_private_assets(monkeypatch):
    monkeypatch.setenv("PROMO_AUTH_ENABLED","1")
    monkeypatch.setenv("PROMO_PASSWORD_HASH",hash_password(PASSWORD,iterations=300_000))
    monkeypatch.setenv("PROMO_SESSION_SECRET","test-theme-session-secret-2026-private-over-forty-chars")
    with TestClient(app,base_url="https://promo.test") as client:
        r=client.get("/login")
        assert r.status_code==200
        assert '<script src="/theme.js"></script>' in r.text
        assert 'data-theme-toggle' in r.text
        assert "script-src 'self'" in r.headers['content-security-policy']
        public=client.get("/theme.js")
        assert public.status_code==200
        assert public.headers['content-type'].startswith('text/javascript')
        assert "promoeditor.theme.v1" in public.text
        for url in ("/static/theme.js","/static/theme.css","/static/app.css","/api/config"):
            assert client.get(url).status_code==401,url

def test_dark_mode_applies_to_nested_forms_and_editor_but_not_poster_pixels():
    css=(ROOT/'theme.css').read_text(encoding='utf-8')
    js=(ROOT/'theme.js').read_text(encoding='utf-8')
    for fragment in ('data-theme="dark"', '.composer', '.dropzone',
         '.field textarea','.download-panel','.advanced','.edit-section',
         '.edit-option-group','.edit-ai-option','.edit-status','.edit-stage'):
        assert fragment in css
    assert "filter:invert" not in css.replace(" ","").lower()
    assert re.search(r'#edit-canvas\s*\{[^}]*filter\s*:',css) is None
    for key in ('localStorage.getItem','localStorage.setItem',
                'matchMedia','prefers-color-scheme','aria-pressed',
                'DOMContentLoaded','theme-color'):
        assert key in js

def test_theme_is_pure_presentation_no_image_api_changes():
    js=(ROOT/'theme.js').read_text(encoding='utf-8')
    for forbidden in ('fetch(', 'canvas.getContext(', 'localStorage.clear(',
                      "window.location.assign(", 'window.location.replace(', 'innerHTML='):
        assert forbidden not in js
