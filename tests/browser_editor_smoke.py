"""Browser E2E smoke of the editor against running FastAPI. No OpenAI calls."""
import io
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image
from playwright.sync_api import sync_playwright

BASE=os.environ.get("PROMO_BROWSER_BASE","http://127.0.0.1:18200")


def assert_image(path:Path, dimensions):
    with Image.open(path) as im:
        assert im.size==dimensions, (im.size,dimensions)
        assert im.format=="PNG"


def main():
    png=io.BytesIO()
    Image.new("RGB",(640,480),(240,243,248)).save(png,format="PNG")
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(accept_downloads=True,viewport={"width":1360,"height":900})
        errors=[]
        page.on("pageerror",lambda error: errors.append(str(error)))
        page.goto(BASE,wait_until="domcontentloaded")
        # Dark mode is a real choice, persists after reload and never touches PNG.
        toggle=page.locator("[data-theme-toggle]")
        assert toggle.count()==1
        toggle.click()
        assert page.locator("html").get_attribute("data-theme")=="dark"
        page.wait_for_function(
            "getComputedStyle(document.body).backgroundColor==='rgb(13, 20, 32)'",
            timeout=2000)
        background=page.locator("body").evaluate("(el)=>getComputedStyle(el).backgroundColor")
        assert background=="rgb(13, 20, 32)",background
        transition=page.locator(".topbar").evaluate("(el)=>getComputedStyle(el).transitionDuration")
        assert "0.32s" in transition,transition
        page.reload(wait_until="domcontentloaded")
        assert page.locator("html").get_attribute("data-theme")=="dark"
        page.locator("[data-theme-toggle]").click()
        assert page.locator("html").get_attribute("data-theme")=="light"
        page.locator("[data-theme-toggle]").click()
        assert page.locator("html").get_attribute("data-theme")=="dark"
        # Accessibility setting: no animated transition.
        page.emulate_media(reduced_motion="reduce")
        assert page.locator(".topbar").evaluate("(el)=>getComputedStyle(el).transitionDuration")=="0s"
        page.locator("[data-theme-toggle]").click()
        assert page.locator("html").get_attribute("data-theme")=="light"
        page.locator("[data-theme-toggle]").click()
        assert page.locator("html").get_attribute("data-theme")=="dark"
        page.emulate_media(reduced_motion="no-preference")
        assert page.locator("#edit-body").is_hidden()
        assert page.locator("#edit-workspace").is_hidden()
        page.locator("#edit-toggle").click()
        assert page.locator("#edit-body").is_visible()
        page.locator("#edit-open-file").set_input_files(
            {"name":"starting.png","mimeType":"image/png","buffer":png.getvalue()})
        page.wait_for_function("!document.getElementById('edit-workspace').hidden")
        assert page.locator("#edit-canvas").evaluate("(canvas) => [canvas.width,canvas.height]")==[640,480]
        # Interface colors change; the content of the poster pixel stays exact.
        before=page.locator("#edit-canvas").evaluate(
            "(canvas)=>Array.from(canvas.getContext('2d').getImageData(0,0,1,1).data)")
        page.locator("[data-theme-toggle]").click()
        after=page.locator("#edit-canvas").evaluate(
            "(canvas)=>Array.from(canvas.getContext('2d').getImageData(0,0,1,1).data)")
        assert before==after,(before,after)
        page.locator("[data-theme-toggle]").click()
        page.locator("#edit-text-input").fill("Новая надпись")
        page.locator("#edit-add-text").click()
        assert "Текстовый слой" in page.locator("#edit-selected-name").inner_text()
        with page.expect_download() as evt:
            page.locator("#edit-download").click()
        assert_image(Path(evt.value.path()),(640,480))
        page.locator('[data-edit-tool="cover"]').click()
        box=page.locator("#edit-canvas").bounding_box()
        assert box
        page.mouse.move(box["x"]+70,box["y"]+70)
        page.mouse.down()
        page.mouse.move(box["x"]+160,box["y"]+155,steps=4)
        page.mouse.up()
        assert "Закрытая область" in page.locator("#edit-selected-name").inner_text()
        with page.expect_download() as project_evt:
            page.locator("#edit-save-project").click()
        project_file=Path(project_evt.value.path())
        data=json.loads(project_file.read_text())
        assert data["type"]=="PromoEditor-editable-v1"
        assert len(data["layers"])>=2
        page.reload(wait_until="domcontentloaded")
        page.locator("#edit-toggle").click()
        page.locator("#edit-project-file").set_input_files(
            {"name":"saved.promo.json","mimeType":"application/json","buffer":project_file.read_bytes()})
        page.wait_for_function("!document.getElementById('edit-workspace').hidden")
        assert "Проект открыт" in page.locator("#edit-status").inner_text()
        # Open a freshly generated portrait in the same editor.
        with urlopen(BASE+"/api/demo",timeout=10) as response:
            demo=json.load(response)["brief"]
        form=urlencode({"payload":json.dumps(demo,ensure_ascii=False),
                        "use_openai":"false","use_demo":"true"}).encode()
        req=Request(BASE+"/api/generate",data=form,method="POST")
        with urlopen(req,timeout=50) as response:
            generated=json.load(response)
        page.evaluate(
            """(result) => window.dispatchEvent(
              new CustomEvent('promoeditor:generated',{detail:result}))""",generated)
        assert page.locator("#edit-open-portrait").is_enabled()
        page.locator("#edit-open-portrait").click()
        page.wait_for_function("document.querySelector('#edit-canvas').width===1080")
        assert page.locator("#edit-canvas").evaluate("(canvas) => [canvas.width,canvas.height]")==[1080,1920]
        assert not errors,errors
        browser.close()
    print("Browser editor smoke: upload, add text, cover, PNG, project roundtrip, generated portrait — PASS")


if __name__=="__main__":
    main()
