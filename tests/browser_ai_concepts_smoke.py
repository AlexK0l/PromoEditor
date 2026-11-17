"""Browser-only UI regression: selectable AI concepts without a live paid API.

The /api/concepts and /api/config responses are mocked in Chromium. The
actual back-end contract, source preservation and validation are tested
separately by tests/test_ai_concepts.py.
"""
from __future__ import annotations
import json
import os
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
        page.goto(BASE,wait_until="domcontentloaded")
        assert page.locator("#mode-ai-pro").is_checked()
        assert not page.locator("#ai-concepts-workflow").is_hidden()
        assert page.locator("#reference_example").count()==1
        assert "необязатель" in page.locator("label[for=reference_example]").inner_text().lower()
        assert page.locator("#generate-btn").is_disabled()
        page.locator("#model").fill("TEST INDUSTRIAL MODEL")
        page.locator("#generate-concepts-btn").click()
        page.wait_for_function("document.querySelectorAll('.ai-concept-card').length===3")
        assert len(requests)==1
        assert "reference_example" not in requests[0]
        assert page.locator("#generate-btn").is_disabled()
        page.locator(".ai-concept-card").nth(1).locator("button").click()
        assert page.locator(".ai-concept-card").nth(1).get_attribute("class").endswith("is-selected")
        assert not page.locator("#generate-btn").is_disabled()
        assert "Вариант B" in page.locator(".ai-concept-card").nth(1).inner_text()
        page.locator("#model").fill("TEST INDUSTRIAL MODEL UPDATED")
        assert page.locator("#generate-btn").is_disabled()
        assert page.locator(".ai-concept-card").count()==0
        page.locator("#mode-template").check()
        assert page.locator("#ai-concepts-workflow").is_hidden()
        assert not page.locator("#generate-btn").is_disabled()
        page.set_viewport_size({"width":390,"height":820})
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth+2")
        assert not errors,errors
        browser.close()
    print("AI concepts browser: optional reference, A/B/C, stale invalidation and fallback — PASS")


if __name__=="__main__":
    main()
