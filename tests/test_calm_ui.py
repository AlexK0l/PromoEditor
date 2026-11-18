"""Calm user workflow: only essential controls on initial display.

These tests catch accidental re-introduction of expert-only controls to the
landing screen, while keeping every existing technical field and input ID.
"""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "static"


class DetailsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []
        self.parents = {}
        self.all_ids = []
        self.closed_by_default = set()

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        ident = data.get("id")
        if tag == "details":
            self.details.append(ident)
            if "open" not in data:
                self.closed_by_default.add(ident)
        if ident:
            self.parents[ident] = tuple(self.details)
            self.all_ids.append(ident)

    def handle_endtag(self, tag):
        if tag == "details":
            assert self.details, "Unexpected closing </details>"
            self.details.pop()


def parse_page():
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = DetailsParser()
    parser.feed(page)
    assert not parser.details, "Unclosed expert/advanced <details> tag"
    return page, parser


def test_essential_first_view_is_only_three_steps_and_two_modes():
    html, parser = parse_page()
    assert len(parser.all_ids) == len(set(parser.all_ids)), "Duplicate DOM IDs"
    for ident in (
        "approved-preset-btn", "hero", "model", "slogan",
        "mode-hybrid", "mode-template", "generate-btn",
    ):
        assert ident in parser.parents
        assert not parser.parents[ident], (ident, parser.parents[ident])
    assert "ШАГ 1 ИЗ 3" in html
    assert "ШАГ 2 ИЗ 3" in html
    assert "ШАГ 3 ИЗ 3" in html
    assert "Создать два макета" in html
    assert "Без AI · бесплатно" in html
    assert "С AI-фоном" in html
    assert "Два платных запроса" in html


def test_all_advanced_controls_remain_available_but_closed_at_launch():
    _, parser = parse_page()
    mapping = {
        "mode-ai-pro": "expert-modes",
        "asset-files-list": "asset-files-details",
        "reference_example": "optional-materials",
        "documents": "optional-materials",
        "background": "optional-materials",
        "brand": "creative-notes",
        "design-actions": "creative-notes",
        "promo-prompt": "expert-prompt",
        "asset-approve": "asset-review-details",
        "price": "advanced-settings",
        "specs": "advanced-settings",
        "dimensions": "advanced-settings",
        "phones": "advanced-settings",
        "show-roi": "advanced-settings",
    }
    for ident, detail in mapping.items():
        assert detail in parser.parents.get(ident, ()), (ident, parser.parents.get(ident))
        assert detail in parser.closed_by_default, detail
    assert "logo" in parser.parents and "drawing" in parser.parents
    assert not parser.parents["logo"] and not parser.parents["drawing"]
    # The brief must still precede the prominent creation button.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.index('id="advanced-settings"') < html.index('id="generate-btn"')


def test_one_click_free_asset_selection_precedes_any_potentially_paid_generation():
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    begin = script.index("  async function generate(){")
    body = script[begin:script.index("  async function inspect(){", begin)]
    assert "window.PromoAssets.analyze(formBrief(),{freeOnly:true})" in body
    assert "window.PromoAssets.isReady()" in body
    assert body.index("window.PromoAssets.analyze(") < body.index("fetch('/api/generate'")
    assert "isHybrid()" in body
    assert "const selected=window.PromoAssets?.getReport?.()" in body
    assert "if(isBusy)return;" in body


def test_design_css_supports_keyboard_focus_small_screen_and_dark_theme():
    css = (ROOT / "app.css").read_text(encoding="utf-8")
    for fragment in (
        ".quiet-details>summary", ".preset-shortcut", ".topbar-menu",
        ".mode-choice label:has(input:checked)", ".individual-downloads",
        "@media (max-width:460px)", ':root[data-theme="dark"] .quiet-details',
    ):
        assert fragment in css, fragment
    assert ":focus-visible" in css
    assert "prefers-reduced-motion:reduce" in css
