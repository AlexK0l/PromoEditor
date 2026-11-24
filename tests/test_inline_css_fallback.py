"""Real HTML response stays styled without any browser CSS subrequests."""

from fastapi.testclient import TestClient

from app import main


def test_home_embeds_all_canonical_styles_into_one_html_response():
    with TestClient(main.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    html = response.text
    assert html.count('<style id="promoeditor-embedded-styles">') == 1
    assert "<!-- PROMOEDITOR_EMBEDDED_STYLES -->" not in html
    css = html.split('<style id="promoeditor-embedded-styles">', 1)[1].split(
        "</style>", 1
    )[0]
    for asset in ("app.css", "editor.css", "theme.css", "assets.css"):
        contents = (main.STATIC / asset).read_text(encoding="utf-8")
        assert contents in css, asset
    assert ".composer-grid{display:grid;" in css
    assert ".drop-icon svg{height:25px;width:25px}" in css
    assert "body{margin:0;" in css
    assert "data-theme" in css
    assert '#stylesheet-error{display:none!important}' in css
