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
            "job_id": "a"*32,
            "generation_mode": "openai_full_poster",
            "export_geometry": {
                "4x3":{"target_size":[1440,1080],"content_box":[0,0,1440,1080],"outpaint":{"status":"not_needed"}},
                "9x16":{"target_size":[1080,1920],"content_box":[0,0,1080,1920],"outpaint":{"status":"not_needed"}},
            },
            "ai_used": True,
            "raster_only": True,
            "images": {"4x3": "/static/demo_4x3.svg",
                       "9x16": "/static/demo_9x16.svg"},
            "jpeg": {"4x3": "/static/demo_4x3.svg",
                     "9x16": "/static/demo_9x16.svg"},
            "zip": "/files/" + "a" * 32 + "/ai_posters.zip",
            "warnings": [],
            "poster_review": {"status":"issues_found","issues_count":3,
                              "human_review_required":True,
                              "formats":{"4x3":{"vehicle_check":{"issues":["Оси: ожидается 4, обнаружено 5."]}},
                                         "9x16":{"fields":[{"label":"Модель","expected":"TEST",
                                                             "observed":"","status":"missing"}]}}},
        }
        status_requests = []
        def begin_reply(route):
            posts.append(route.request.url)
            body=route.request.post_data_buffer or b""
            assert b'name="verify_posters"' in body
            if b"refine_posters" in body:
                assert b'name="source_job"' in body
                assert b'name="refine_attempt"' in body
                assert b'name="refine_action"' in body
            else:
                assert b'name="expand_posters"' not in body
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
            elif len(status_requests)==2:
                ready={**completed,"review_pending":True,"poster_review":{
                    "status":"unavailable","human_review_required":True}}
                route.fulfill(status=200,content_type="application/json",body=json.dumps({
                    "status":"running","stage":"Плакаты доступны для скачивания; выполняется AI-сверка",
                    "stage_age_seconds":42,"result":ready,
                }))
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

        # PRO must permit a real product photo without any style exemplar.
        page.evaluate("document.querySelector('[data-style=reference_pro]').click()")
        assert page.locator("#style").input_value() == "reference_pro"
        assert page.locator("#reference_example").evaluate("(el)=>el.files.length") == 0
        assert page.locator("#references").evaluate("(el)=>el.files.length") == 0
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
        assert confirmations and "До 3 платных вызовов OpenAI Images" in confirmations[0], confirmations
        assert "PNG/JPEG, НЕ SVG" in confirmations[0]
        assert "кэш" in confirmations[0]
        assert "1 платный Responses-запрос" in confirmations[0]
        assert "до 2 платных Images-запросов" not in confirmations[0]
        assert "точных пропорциях 4:3 и 9:16" in confirmations[0]
        assert not posts, "Rejecting a paid call must make ZERO requests"
        assert page.locator("#loading").is_hidden()

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#generate-btn").click()
        page.wait_for_function(
            "() => !document.getElementById('download-panel').hidden",
            timeout=30000,
        )
        assert len(posts) == 1, posts
        assert page.locator("#download-all").is_enabled()
        assert page.locator("#generate-btn").is_disabled()
        assert "сверка" in page.locator("#loading strong").inner_text().lower()
        assert "42 с" in page.locator("#loading small").inner_text()
        assert "сверка выполняется отдельно" in page.locator("#poster-review-status").inner_text()
        page.wait_for_function("() => document.getElementById('loading').hidden",timeout=15000)
        assert len(status_requests) == 3, status_requests
        assert page.locator("#generated-previews").is_visible()
        assert page.locator("#generated-preview-4x3").get_attribute("src") == "/static/demo_4x3.svg"
        assert page.locator("#generated-preview-9x16").get_attribute("src") == "/static/demo_9x16.svg"
        assert page.locator("#download-all").is_enabled()
        assert page.locator("#new-variation-btn").is_visible()
        assert page.locator("#new-variation-btn").is_enabled()
        assert page.locator("#download-svg-4x3").evaluate("(b)=>b.parentElement.hidden")
        assert page.locator("#download-svg-9x16").evaluate("(b)=>b.parentElement.hidden")
        assert page.locator("#download-svg-4x3").is_disabled()
        assert page.locator("#download-svg-9x16").is_disabled()
        assert "растр" in page.locator(".result-disclaimer").inner_text().lower()
        assert "approved_copy.json" in page.locator(".prompt-download-note").inner_text()
        assert "AI-черновики" in page.locator("#download-title").inner_text()
        assert page.locator("#poster-review-status").is_visible()
        assert "расхождения" in page.locator("#poster-review-status").inner_text()
        assert "3" in page.locator("#poster-review-status").inner_text()
        assert "НЕ ДЛЯ ПУБЛИКАЦИИ" in page.locator("#poster-review-status").inner_text()
        assert "ожидается 4, обнаружено 5" in page.locator("#poster-review-details").inner_text()
        for selector in ("#generation-mode",
                         "#ai-concepts-workflow", "#openai-posters-workflow"):
            assert page.locator(selector).is_hidden(), selector

        assert page.locator("#refine-panel").is_visible()
        page.locator("#refine-panel summary").click()
        assert "точные пропорции, дорисовка не нужна" in page.locator("#outpaint-status").inner_text()
        assert page.locator("#refine-expand").is_hidden()
        assert page.locator("#refine-expand").is_disabled()
        assert page.locator("#refine-repair").is_visible()
        assert page.locator("#refine-import-panel").is_visible()
        assert len(posts)==1

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
