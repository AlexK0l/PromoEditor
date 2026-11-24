"""Save real Chromium screenshots of the draft user interface for PR review.

GitHub Actions runs this against localhost in an isolated CI runner.
No paid OpenAI calls, user photos, login passwords or VPS changes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE = os.environ.get("PROMO_BROWSER_BASE", "http://127.0.0.1:18200")
OUTPUT = Path(os.environ.get("PROMO_UI_PREVIEW_DIR", "/tmp/promo-ui-preview"))


def settled(page):
    page.wait_for_function(
        "() => document.querySelector('#api-state').textContent !== 'Проверяем сервер…'"
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        errors = []

        desktop = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=1,
            color_scheme="light",
            locale="ru-RU",
            reduced_motion="reduce",
        )
        page = desktop.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        response = page.goto(BASE, wait_until="networkidle")
        assert response and response.status == 200, "Preview URL did not load"
        settled(page)
        assert page.locator("#mode-template").is_checked()
        assert page.locator("#mode-hybrid").is_disabled()
        page.screenshot(path=OUTPUT / "01-desktop-overview.png", full_page=True,
                        animations="disabled")
        page.locator("section.composer").screenshot(
            path=OUTPUT / "02-desktop-create-form.png", animations="disabled")

        # Demo preset is retired from customer UI; seed its approved facts
        # internally for the existing screenshot regression only.
        assert page.locator(".preset-shortcut").is_visible()
        page.locator("#approved-preset-btn").click()
        page.wait_for_function(
            "() => document.querySelector('#model').value === 'ZubrTrail 500'"
        )
        assert "6 527 000" in page.locator("#brief-data-hint").inner_text()
        page.locator("#pro-workspace > summary").click()
        page.locator("#advanced-settings > summary").click()
        page.locator("#data-contacts > summary").click()
        assert page.locator("#data-facts").evaluate("(el)=>el.open")
        assert page.locator("#specs").is_visible()
        assert page.locator("#dimensions").is_visible()
        assert page.locator("#price").input_value() == "6527000"
        page.locator("#data-facts").screenshot(
            path=OUTPUT / "03-zubrtrail-data-fields.png", animations="disabled")

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
            color_scheme="light",
            locale="ru-RU",
            reduced_motion="reduce",
        )
        phone = mobile.new_page()
        phone.on("pageerror", lambda exc: errors.append(str(exc)))
        phone.goto(BASE, wait_until="networkidle")
        settled(phone)
        assert phone.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth + 2"
        ), "Mobile UI overflows viewport"
        phone.screenshot(path=OUTPUT / "04-mobile-390px.png", full_page=True,
                         animations="disabled")

        # Preview the unlocked hybrid choice WITHOUT sending Images API calls.
        ai = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            color_scheme="light",
            locale="ru-RU",
            reduced_motion="reduce",
        )
        ai_page = ai.new_page()
        ai_page.on("pageerror", lambda exc: errors.append(str(exc)))
        ai_page.route("**/api/config", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"openai_ready": True, "auth_enabled": False}),
        ))
        ai_page.goto(BASE, wait_until="networkidle")
        settled(ai_page)
        assert ai_page.locator("#mode-hybrid").is_checked()
        assert ai_page.locator("#mode-hybrid").is_enabled()
        ai_page.locator("section.composer").screenshot(
            path=OUTPUT / "05-ai-art-director-choice-demo.png",
            animations="disabled",
        )

        assert not errors, f"Browser JavaScript errors during preview: {errors}"
        browser.close()

    (OUTPUT / "README.txt").write_text(
        "PromoEditor - снимки тестирования интерфейса main\n"
        "01 - полная стартовая страница, desktop\n"
        "02 - основная форма, desktop\n"
        "03 - подтверждённые характеристики ZubrTrail 500\n"
        "04 - мобильный вид 390px\n"
        "05 - основной AI-постер: ТОЛЬКО визуальная имитация ключа, "
        "без API-генерации и платежей\n"
        "Снимки автоматически получены Chromium при проверках main.\n"
        "Это не публичный работающий сервер и не гарантия платного AI-рендера.\n",
        encoding="utf-8",
    )
    print("Five production-UI screenshots saved to", OUTPUT)


if __name__ == "__main__":
    main()
