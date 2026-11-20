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


def test_essential_first_view_is_one_form_one_switch_one_button():
    html, parser = parse_page()
    assert len(parser.all_ids) == len(set(parser.all_ids)), "Duplicate DOM IDs"
    for ident in (
        "approved-preset-btn", "hero", "model", "slogan",
        "price", "currency", "phones", "quick-ai-toggle", "generate-btn",
    ):
        assert ident in parser.parents
        assert not parser.parents[ident], (ident, parser.parents[ident])
    assert "Создать рекламный макет" in html
    assert "Оформить с помощью OpenAI" in html
    assert "Создать промо" in html
    assert "1 запрос на арт-план + 2 на полный дизайн" in html
    assert "pro-workspace" in parser.closed_by_default
    assert "generated-previews" in parser.parents
    assert "editing-suite" in parser.closed_by_default
    app_js=(ROOT / "app.js").read_text(encoding="utf-8")
    assert "$('quick-ai-toggle').addEventListener('change'" in app_js
    assert "$('use-openai').checked=false; // free means ZERO paid AI calls." in app_js
    assert "mode-hybrid" in parser.parents
    assert "pro-workspace" in parser.parents["mode-hybrid"]
    assert "pro-workspace" in parser.parents["mode-template"]
    assert "pro-workspace" in parser.parents["mode-ai-pro"]


def test_technical_controls_remain_under_single_closed_workspace():
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
        "specs": "advanced-settings",
        "dimensions": "advanced-settings",
        "show-roi": "advanced-settings",
    }
    for ident, detail in mapping.items():
        assert detail in parser.parents.get(ident, ()), (ident, parser.parents.get(ident))
        assert detail in parser.closed_by_default, detail
        assert "pro-workspace" in parser.parents[ident]
    for ident, subgroup in {
        "specs": "data-facts", "dimensions": "data-facts",
        "show-roi": "data-roi", "image-quality": "data-design",
    }.items():
        assert subgroup in parser.parents[ident]
        assert subgroup in parser.closed_by_default
    for ident in ("hero", "logo", "drawing", "price", "phones", "generate-btn"):
        assert ident in parser.parents and not parser.parents[ident]
    assert "editing-suite" in parser.closed_by_default
    # Action is the primary experience; fine settings come afterwards.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.index('id="generate-btn"') < html.index('id="advanced-settings"')

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
        ".one-ai-choice", ".pro-workspace",
        ".mode-choice label:has(input:checked)", ".individual-downloads",
        "@media (max-width:460px)", ':root[data-theme="dark"] .quiet-details',
    ):
        assert fragment in css, fragment
    assert ":focus-visible" in css
    assert "prefers-reduced-motion:reduce" in css


def test_unverified_old_roi_never_seeds_a_new_campaign():
    html, _ = parse_page()
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'id="rate" value="0.19"' not in html
    assert 'id="baseline-price" value="149499"' not in html
    for ident in ("rate", "baseline-price", "extra-payload"):
        assert f'id="{ident}" placeholder=' in html
    assert "function missingRoiInputs()" in js
    assert "if(checked('show-roi')&&missingRoiInputs())" in js
    assert "set(id,'')" in js


def test_advanced_paid_background_switch_must_agree_with_primary_ai_switch():
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "const paidInTemplate=!hybrid&&!ai&&checked('use-openai')" in js
    assert "simple.checked=hybrid||paidInTemplate" in js
    assert "Бесплатная сборка затянулась" in js
    assert "window.clearTimeout(slowWarning)" in js
    assert "2 платных запроса, без AI-арт-директора" in js


def test_paid_progress_is_explicit_and_cancelling_confirmation_sends_nothing():
    html, parser = parse_page()
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "generate-elapsed" in parser.parents
    assert "if(isHybrid()&&!window.confirm(" in js
    assert "3 платных запроса" in js
    assert "window.setInterval(updateElapsed,1000)" in js
    assert "window.clearInterval(elapsedClock)" in js
    assert "elapsed.hidden=true" in js
    assert "OpenAI всё ещё выполняет запросы" in js
    assert "проверьте нагрузку тестовой службы" in js
    assert 'class="asset-intro"' not in html, "Keep initial screen uncluttered"
