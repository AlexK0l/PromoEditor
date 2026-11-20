"""Browser-only UI regression: selectable AI concepts without a live paid API.

The /api/concepts and /api/config responses are mocked in Chromium. The
actual back-end contract, source preservation and validation are tested
separately by tests/test_ai_concepts.py.
"""
from __future__ import annotations
import json
import os
import io
from PIL import Image
from playwright.sync_api import sync_playwright

BASE=os.getenv("PROMO_BROWSER_BASE","http://127.0.0.1:18200")


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1320,"height":850})
        errors=[]
        requests=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        page.route("**/api/config",lambda route:route.fulfill(
            status=200,content_type="application/json",
            body=json.dumps({"openai_ready":True,"auth_enabled":False})))
        def three_previews(route):
            requests.append(route.request.post_data or "")
            cards=[{
                "index":i,
                "name":f"Вариант {chr(65+i)}",
                "rationale":f"Самостоятельная композиция {i+1}",
                "previews":{"4x3":"/static/demo_4x3.svg",
                            "9x16":"/static/demo_9x16.svg"},
                "layout_repair":({"4x3":"fallback","9x16":"repaired"}
                                 if i==0 else {"4x3":"original","9x16":"original"}),
                "layout_spec":{"4x3":{"hero":{"w":610}},
                               "9x16":{"hero":{"w":900}}},
            } for i in range(3)]
            route.fulfill(status=200,content_type="application/json",
                body=json.dumps({
                    "concept_set_id":"a"*32,
                    "concepts":cards,
                    "reference_used":False,
                    "style":"premium","goal":"sales",
                },ensure_ascii=False))
        page.route("**/api/concepts",three_previews)
        poster_requests=[]
        def poster_reply(route):
            poster_requests.append(route.request.post_data or "")
            route.fulfill(status=200,content_type="application/json",
                body=json.dumps({
                    "images":{"4x3":"/static/demo_4x3.svg",
                              "9x16":"/static/demo_9x16.svg"},
                    "zip":"/files/"+"a"*32+"/ai_posters.zip",
                    "raster_only":True,"reference_used":False}))
        page.route("**/api/ai-posters",poster_reply)
        page.goto(BASE,wait_until="domcontentloaded")
        # AI credentials make the exact editable hybrid workflow primary.
        assert page.locator("#mode-hybrid").is_checked()
        assert page.locator("#use-openai").is_checked()
        assert page.locator("#use-openai").is_disabled()
        assert page.locator("#openai-posters-workflow").is_hidden()
        # The previous AI-concept and raster-experiment workflow is still available.
        page.locator("#pro-workspace > summary").click()
        page.locator("#expert-modes > summary").click()
        page.locator("#mode-ai-pro").check()
        assert page.locator("#mode-ai-pro").is_checked()
        assert not page.locator("#ai-concepts-workflow").is_hidden()
        assert page.locator("#reference_example").count()==1
        page.locator("#optional-materials > summary").click()
        assert "необязатель" in page.locator("label[for=reference_example]").inner_text().lower()
        assert page.locator("#generate-btn").is_disabled()
        page.locator("#model").fill("TEST INDUSTRIAL MODEL")
        assert "без эталона" in page.locator("#openai-posters-title").inner_text().lower()
        page.locator("#generate-ai-posters-btn").click()
        assert len(poster_requests)==0  # No photo, no paid call
        photo=io.BytesIO()
        Image.new("RGB",(320,180),"red").save(photo,"PNG")
        page.locator("#hero").set_input_files({
            "name":"vehicle.png","mimeType":"image/png","buffer":photo.getvalue()})
        page.evaluate("window.PromoAssets.isReady=()=>true")
        page.locator("#generate-ai-posters-btn").click()
        page.wait_for_function(
            "document.querySelector('#openai-poster-results').hidden===false")
        assert len(poster_requests)==1
        assert "не требовался" in page.locator("#openai-posters-status").inner_text().lower()
        assert page.locator("#openai-poster-results img").count()==2
        assert page.locator("#openai-posters-download").get_attribute("href").endswith("ai_posters.zip")
        page.locator("#generate-concepts-btn").click()
        page.wait_for_function("document.querySelectorAll('.ai-concept-card').length===3")
        assert len(requests)==1
        assert "reference_example" not in requests[0]
        assert page.locator("#generate-btn").is_disabled()
        assert page.locator(".ai-concept-preview").count()==6
        for i in range(3):
            card=page.locator(".ai-concept-card").nth(i)
            assert card.locator(".ai-concept-preview--landscape img").get_attribute("src")=="/static/demo_4x3.svg"
            assert card.locator(".ai-concept-preview--portrait img").get_attribute("src")=="/static/demo_9x16.svg"
            assert "4:3" in card.inner_text() and "9:16" in card.inner_text()
        assert "резервную сетку" in page.locator("#ai-concepts-status").inner_text().lower()
        assert "не передавался" in page.locator("#ai-concepts-status").inner_text().lower()
        first=page.locator(".ai-concept-card").nth(0)
        assert "Резервная сетка" in first.inner_text()
        assert "исправлена" in first.inner_text()
        # Force a thumbnail error, without an extra paid request or a misleading
        # broken-img icon and its full English alt string in the card.
        page.locator(".ai-concept-card").nth(2).locator(
            ".ai-concept-preview--portrait img").evaluate(
            "(img) => img.dispatchEvent(new Event('error'))")
        assert page.locator(".ai-preview-error").count()==1
        assert "открыть файл" in page.locator(".ai-preview-error").inner_text()
        assert len(requests)==1
        page.locator(".ai-concept-card").nth(1).locator("button").click()
        assert page.locator(".ai-concept-card").nth(1).get_attribute("class").endswith("is-selected")
        assert not page.locator("#generate-btn").is_disabled()
        assert "Вариант B" in page.locator(".ai-concept-card").nth(1).inner_text()
        page.locator("#model").fill("TEST INDUSTRIAL MODEL UPDATED")
        assert page.locator("#generate-btn").is_disabled()
        assert page.locator(".ai-concept-card").count()==0
        page.locator("#mode-template").check()
        assert not page.locator("#quick-ai-toggle").is_checked()
        assert not page.locator("#use-openai").is_checked()
        page.locator("#quick-ai-toggle").check()
        assert page.locator("#mode-hybrid").is_checked()
        assert page.locator("#use-openai").is_checked()
        page.locator("#quick-ai-toggle").uncheck()
        assert page.locator("#mode-template").is_checked()
        assert not page.locator("#use-openai").is_checked()
        assert page.locator("#ai-concepts-workflow").is_hidden()
        assert not page.locator("#generate-btn").is_disabled()
        # A paid background in the legacy template must never look "free"
        # in the new primary switch.
        page.locator("#design-options > summary").click()
        page.locator("#use-openai").check()
        assert page.locator("#quick-ai-toggle").is_checked()
        assert "2 платных запроса" in page.locator("#quick-ai-description").inner_text()
        page.locator("#use-openai").uncheck()
        assert not page.locator("#quick-ai-toggle").is_checked()

        # Old Br ROI figures are not silently reused for a new project.
        page.locator("#advanced-settings > summary").click()
        page.locator("#data-roi > summary").click()
        assert page.locator("#rate").input_value() == ""
        assert page.locator("#baseline-price").input_value() == ""
        page.locator("#show-roi").check()
        page.locator("#generate-btn").click()
        assert "Экономика включена" in page.locator("#error-box").inner_text()
        assert page.locator("#download-panel").is_hidden()
        page.locator("#show-roi").uncheck()
        page.set_viewport_size({"width":390,"height":820})
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth+2")
        assert not errors,errors

        # The normal hybrid requires a conscious confirmation before ANY
        # free analysis, planning or chargeable image calls. Dismissal must
        # leave the page ready and perform no /api/generate request.
        paid=browser.new_page(viewport={"width":1100,"height":770})
        paid_errors=[]
        paid.on("pageerror",lambda error: paid_errors.append(str(error)))
        paid.route("**/api/config",lambda route:route.fulfill(
            status=200,content_type="application/json",
            body=json.dumps({"openai_ready":True,"auth_enabled":False})))
        request_count=[]
        paid.on("request",lambda request: request_count.append(request.url)
                if "/api/generate" in request.url else None)
        paid.goto(BASE,wait_until="domcontentloaded")
        paid.wait_for_function("document.querySelector('#mode-hybrid').checked")
        paid.locator("#model").fill("TEST CONFIRMATION 500")
        paid.locator("#hero").set_input_files({
            "name":"vehicle.png","mimeType":"image/png","buffer":photo.getvalue()})
        dialogs=[]
        def decline_charge(dialog):
            dialogs.append(dialog.message)
            dialog.dismiss()
        paid.once("dialog",decline_charge)
        paid.locator("#generate-btn").click()
        assert dialogs and "3 платных вызова" in dialogs[0]
        assert not request_count,request_count
        assert paid.locator("#loading").is_hidden()
        assert paid.locator("#generate-btn").is_enabled()
        assert not paid_errors,paid_errors
        paid.close()
        browser.close()
    print("AI concepts browser: optional reference, A/B/C, stale invalidation and fallback — PASS")


if __name__=="__main__":
    main()
