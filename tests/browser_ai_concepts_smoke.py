"""Production UI smoke: only primary AI generation, no paid network calls.

Legacy experiments remain in source for compatibility but are NOT visible
to users. This test verifies the main button accepts the paid confirmation,
starts a private long AI job, polls through one 502, and shows AI raster.
"""
from __future__ import annotations

import io
import json
import os

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = os.getenv("PROMO_BROWSER_BASE", "http://127.0.0.1:18200")


def _product_png():
    stream = io.BytesIO()
    Image.new("RGB", (400, 250), "yellow").save(stream, "PNG")
    return stream.getvalue()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 1320, "height": 850})
        errors = []
        posts = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.route("**/api/config", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"openai_ready": True, "auth_enabled": False}),
        ))

        completed = {
            "generation_mode": "openai_full_poster",
            "ai_used": True,
            "raster_only": True,
            "images": {"4x3": "/static/demo_4x3.svg",
                       "9x16": "/static/demo_9x16.svg"},
            "jpeg": {"4x3": "/static/demo_4x3.svg",
                     "9x16": "/static/demo_9x16.svg"},
            "zip": "/files/" + "a" * 32 + "/ai_posters.zip",
            "warnings": [],
        }
        status_requests = []
        def begin_reply(route):
            posts.append(route.request.url)
            route.fulfill(status=202, content_type="application/json",
                          body=json.dumps({
                "task_id": "b" * 32, "status": "running",
                "status_url": "/api/generate/status/" + "b" * 32,
            }))
        def polling_reply(route):
            status_requests.append(route.request.url)
            # A one-off gateway failure must NOT cause a second paid POST.
            if len(status_requests) == 1:
                route.fulfill(status=502, body="Bad Gateway",
                              content_type="text/plain")
            else:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({
                    "status": "complete", "result": completed,
                }))
        page.route("**/api/generate/start", begin_reply)
        page.route("**/api/generate/status/**", polling_reply)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.querySelector('#mode-hybrid').checked"
        )

        # No demo, sample preset, manual layout switcher, template designer,
        # duplicate paid poster entry or experimental concept creator visible.
        for selector in (
            "#topbar-menu", "#generation-mode",
            "#design-options", "#expert-prompt", "#ai-creative-settings",
            "#ai-concepts-workflow", "#openai-posters-workflow", "#use-demo",
        ):
            assert page.locator(selector).is_hidden(), selector
        assert page.locator(".preset-shortcut").is_visible()
        assert page.locator("#approved-preset-btn").is_visible()
        assert page.locator("#generate-btn").is_visible()
        assert page.locator("#quick-ai-toggle").is_checked()
        assert page.locator("#use-openai").is_checked()
        assert "3 платных Images" in page.locator("#quick-ai-description").inner_text()
        assert "PNG/JPEG" in page.locator("#quick-ai-description").inner_text()
        assert "SVG" not in page.locator("#quick-ai-description").inner_text()

        # The single public switch may still explicitly choose free creation.
        page.locator("#quick-ai-toggle").uncheck()
        assert page.locator("#mode-template").is_checked()
        page.locator("#quick-ai-toggle").check()
        assert page.locator("#mode-hybrid").is_checked()
        assert page.locator("#openai-posters-workflow").is_hidden()

        photo = _product_png()
        page.locator("#model").fill("TEST INDUSTRIAL TRAILER 500")
        page.locator("#hero").set_input_files({
            "name": "customer-product.png",
            "mimeType": "image/png", "buffer": photo,
        })
        # Browser-only model: back-end selection and exact source handling
        # are already covered separately in API tests.
        page.evaluate("""() => {
            window.PromoAssets.isReady = () => true;
            window.PromoAssets.getReport = () =>
                ({selected_assets:{primary_photo:'photo_1'}});
        }""")

        confirmations = []
        def decline(dialog):
            confirmations.append(dialog.message)
            dialog.dismiss()
        page.once("dialog", decline)
        page.locator("#generate-btn").click()
        assert confirmations and "3 платных вызова" in confirmations[0]
        assert not posts, "Rejecting a paid call must make ZERO requests"
        assert page.locator("#loading").is_hidden()

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#generate-btn").click()
        page.wait_for_function(
            "() => !document.getElementById('download-panel').hidden",
            timeout=30000,
        )
        assert len(posts) == 1, posts
        assert len(status_requests) == 2, status_requests
        assert page.locator("#generated-previews").is_visible()
        assert page.locator("#generated-preview-4x3").get_attribute("src") == "/static/demo_4x3.svg"
        assert page.locator("#generated-preview-9x16").get_attribute("src") == "/static/demo_9x16.svg"
        assert page.locator("#download-all").is_enabled()
        assert page.locator("#download-svg-4x3").evaluate("(b)=>b.parentElement.hidden")
        assert page.locator("#download-svg-9x16").evaluate("(b)=>b.parentElement.hidden")
        assert page.locator("#download-svg-4x3").is_disabled()
        assert page.locator("#download-svg-9x16").is_disabled()
        assert "растр" in page.locator(".result-disclaimer").inner_text().lower()
        assert "approved_copy.json" in page.locator(".prompt-download-note").inner_text()
        for selector in ("#generation-mode",
                         "#ai-concepts-workflow", "#openai-posters-workflow"):
            assert page.locator(selector).is_hidden(), selector

        # Production interface remains usable on a phone.
        page.set_viewport_size({"width": 390, "height": 820})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 2"
        ), "Mobile viewport overflow"
        assert not errors, errors
        browser.close()
    print("Production AI poster UI: paid confirmation, full AI raster, honest fact review — PASS")


if __name__ == "__main__":
    main()
