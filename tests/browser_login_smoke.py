"""Browser regression: no-referrer HTML login sends Origin: null, still succeeds."""
import os
from playwright.sync_api import sync_playwright

BASE=os.environ.get("PROMO_LOGIN_SMOKE_BASE","http://127.0.0.1:18201")
PASSWORD="CiLoginPass1234!"

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1250,"height":900})
        errors=[]
        page.on("pageerror",lambda err:errors.append(str(err)))
        initial=page.goto(BASE+"/login",wait_until="domcontentloaded")
        assert initial.status==200
        assert initial.headers.get("referrer-policy")=="no-referrer"
        token=page.locator('input[name="csrf_token"]').get_attribute("value")
        assert token and token.startswith("login.")
        toggle=page.locator("[data-theme-toggle]")
        assert toggle.count()==1
        toggle.click()
        assert page.locator("html").get_attribute("data-theme")=="dark"
        page.reload(wait_until="domcontentloaded")
        assert page.locator("html").get_attribute("data-theme")=="dark"
        page.locator('input[name="password"]').fill(PASSWORD)
        with page.expect_response(lambda res:res.request.method=="POST" and res.url.endswith("/login")) as pending:
            page.get_by_role("button",name="Войти").click()
        response=pending.value
        origin=response.request.headers.get("origin","")
        assert origin=="null",f"Expected browser form Origin:null with no-referrer, got {origin!r}"
        assert response.status==303,f"Valid password was rejected (status {response.status})"
        assert "httponly" in response.all_headers().get("set-cookie","").lower()
        assert page.locator("html").get_attribute("data-theme")=="dark"
        assert page.locator("body").evaluate("(el)=>getComputedStyle(el).backgroundColor")!="rgb(246, 247, 251)"
        assert not errors,errors
        browser.close()
    print("Browser password-only login: Origin null accepted with valid signed CSRF token — PASS")

if __name__=="__main__":
    main()
