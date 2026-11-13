"""Password-only login with no username; complete API/file protection."""
import time
import re

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    COOKIE_NAME, FAILED_LIMIT, SESSION_SECONDS, _FAILURES,
    hash_password, issue_cookie, valid_cookie, verify_password, issue_form_token, valid_form_token
)
from app.main import app
from deploy.time4vps.provision_auth import prepare_settings

PASSWORD="Strong Example Password 12345!"


@pytest.fixture
def protected(monkeypatch):
    from app.auth import _FAILURES
    _FAILURES.clear()
    monkeypatch.setenv("PROMO_AUTH_ENABLED","1")
    monkeypatch.setenv("PROMO_PASSWORD_HASH",hash_password(PASSWORD,iterations=300_000))
    monkeypatch.setenv("PROMO_SESSION_SECRET","test-only-session-secret-that-is-at-least-forty-characters-long")
    yield
    _FAILURES.clear()


def browser():
    return TestClient(app,base_url="https://promo.test")


def submit_login(client,password,**kwargs):
    page=client.get("/login")
    assert page.status_code==200
    token=re.search(r'name="csrf_token" value="([^"]+)"',page.text)
    assert token and valid_form_token("login",token.group(1))
    return client.post("/login",data={"password":password,"csrf_token":token.group(1)},**kwargs)


def test_login_has_exactly_one_password_field_and_no_username(protected):
    with browser() as client:
        r=client.get("/login")
        assert r.status_code==200
        assert 'name="password"' in r.text
        assert 'name="csrf_token"' in r.text
        assert r.headers['referrer-policy']=='no-referrer'
        assert 'name="username"' not in r.text
        assert "Вход в PromoEditor" in r.text
        assert "Cache-Control" in r.headers
        assert "no-store" in r.headers["Cache-Control"]
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_all_private_paths_require_login(protected):
    with browser() as client:
        assert client.get("/",follow_redirects=False).status_code==303
        assert client.get("/",follow_redirects=False).headers["location"]=="/login"
        for endpoint in (
            "/api/config","/api/demo","/static/app.js",
            "/static/editor.js","/files/"+("a"*32)+"/poster_4x3.png"
        ):
            assert client.get(endpoint).status_code==401,endpoint
        assert client.post("/api/generate",data={"payload":"{}"}).status_code==401
        assert client.post("/api/edit").status_code==401
        assert client.post("/api/inspect").status_code==401


def test_signin_cookie_logout_and_rejection_of_bad_password(protected):
    with browser() as client:
        wrong=submit_login(client,"wrong",follow_redirects=False)
        assert wrong.status_code==401
        assert "Неверный пароль" in wrong.text
        ok=submit_login(client,PASSWORD,follow_redirects=False)
        assert ok.status_code==303 and ok.headers["location"]=="/"
        header=ok.headers["set-cookie"].lower()
        assert "httponly" in header and "secure" in header and "samesite=lax" in header
        assert client.get("/").status_code==200
        assert client.get("/api/config").json()["auth_enabled"] is True
        assert client.get("/static/app.js").status_code==200
        assert "id=\"logout-form\"" in client.get("/").text
        csrf=client.get("/api/config").json()["logout_csrf_token"]
        bye=client.post("/logout",data={"csrf_token":csrf},
                        headers={"Origin":"null"},follow_redirects=False)
        assert bye.status_code==303 and bye.headers["location"]=="/login"
        assert client.get("/api/config").status_code==401


def test_expired_forged_cookies_fail_and_password_rotation_revokes(monkeypatch,protected):
    valid=issue_cookie()
    assert valid_cookie(valid)
    assert not valid_cookie(valid[:-1]+("0" if valid[-1]!="0" else "1"))
    assert not valid_cookie(issue_cookie(now=int(time.time())-SESSION_SECONDS-1))
    monkeypatch.setenv("PROMO_PASSWORD_HASH",hash_password("Even longer new password for admin",iterations=300_000))
    # Sessions must be bound to both signing secret AND current password hash.
    assert not valid_cookie(valid)


def test_fail_closed_when_auth_enabled_but_missing_secret(monkeypatch,protected):
    monkeypatch.delenv("PROMO_SESSION_SECRET")
    with browser() as client:
        for route in ("/","/login","/api/config","/static/app.js"):
            response=client.get(route,follow_redirects=False)
            assert response.status_code==503
            assert "traceback" not in response.text.lower()


def test_login_rate_limit_and_origin_restriction(protected):
    with browser() as client:
        alien=submit_login(client,PASSWORD,
                          headers={"Origin":"https://evil.example"},follow_redirects=False)
        assert alien.status_code==403
        alien=client.post("/login",data={"password":PASSWORD},
                          headers={"Origin":"null"},follow_redirects=False)
        assert alien.status_code==403
        for _ in range(FAILED_LIMIT):
            r=submit_login(client,"bad",follow_redirects=False)
            assert r.status_code==401
        assert submit_login(client,PASSWORD,follow_redirects=False).status_code==429


def test_logged_in_cross_site_api_post_denied(protected):
    with browser() as client:
        submit_login(client,PASSWORD)
        r=client.post("/api/generate",headers={"Origin":"https://other-site.test"},
                      data={"payload":"{}"})
        assert r.status_code==403
        r=client.post("/logout",headers={"Origin":"https://other-site.test"})
        assert r.status_code==403
        assert client.get("/api/config").status_code==200


def test_browser_null_origin_with_valid_csrf_can_login(protected):
    # Referrer-Policy: no-referrer converts native HTML form POST Origin to null.
    with browser() as client:
        good=submit_login(client,PASSWORD,headers={"Origin":"null"},follow_redirects=False)
        assert good.status_code==303
        assert "secure" in good.headers["set-cookie"].lower()
        assert client.get("/api/config").status_code==200


def test_signed_form_tokens_are_required_scoped_and_expire(protected):
    token=issue_form_token("login")
    assert valid_form_token("login",token)
    assert not valid_form_token("logout",token)
    assert not valid_form_token("login",token[:-1]+("0" if token[-1]!="0" else "1"))
    assert not valid_form_token("login",issue_form_token("login",now=int(time.time())-3601))
    assert not valid_form_token("login",None)
    with browser() as client:
        # A cross-site page cannot read the signed login token.
        missing=client.post("/login",data={"password":PASSWORD},
                            headers={"Origin":"null"},follow_redirects=False)
        assert missing.status_code==403
        wrong=client.post("/login",data={"password":PASSWORD,"csrf_token":"forged"},
                          follow_redirects=False)
        assert wrong.status_code==403
        # An explicitly cross-origin POST is rejected even if the token is valid.
        alien=client.post("/login",data={"password":PASSWORD,"csrf_token":token},
                          headers={"Origin":"https://evil.example"},follow_redirects=False)
        assert alien.status_code==403


def test_native_logout_requires_valid_token_and_accepts_null_origin(protected):
    with browser() as client:
        assert submit_login(client,PASSWORD,headers={"Origin":"null"},follow_redirects=False).status_code==303
        assert client.get("/api/config").status_code==200
        no_token=client.post("/logout",headers={"Origin":"null"},follow_redirects=False)
        assert no_token.status_code==403
        assert client.get("/api/config").status_code==200
        csrf=client.get("/api/config").json()["logout_csrf_token"]
        assert valid_form_token("logout",csrf)
        result=client.post("/logout",data={"csrf_token":csrf},
                           headers={"Origin":"null"},follow_redirects=False)
        assert result.status_code==303
        assert client.get("/api/config").status_code==401


def test_api_post_still_rejects_null_origin(protected):
    with browser() as client:
        submit_login(client,PASSWORD,headers={"Origin":"null"},follow_redirects=False)
        r=client.post("/api/generate",headers={"Origin":"null"},data={"payload":"{}"})
        assert r.status_code==403


def test_local_dev_no_auth_by_default(monkeypatch):
    monkeypatch.setenv("PROMO_AUTH_ENABLED","0")
    with browser() as client:
        assert client.get("/").status_code==200
        assert client.get("/api/config").status_code==200
        assert client.get("/api/config").json()["auth_enabled"] is False


def test_eight_characters_are_accepted_and_seven_rejected(protected):
    valid_eight="Ab3$xyZ9"
    assert len(valid_eight)==8
    hashed=hash_password(valid_eight,iterations=300_000)
    assert verify_password(valid_eight,hashed)
    assert verify_password(valid_eight,hash_password(valid_eight,iterations=600_000))
    with pytest.raises(ValueError):
        hash_password("a"*7,iterations=300_000)
    with pytest.raises(ValueError):
        hash_password("a"*257,iterations=300_000)

    env=prepare_settings("OPENAI_API_KEY=example\n",valid_eight)
    values=dict(line.split("=",1) for line in env.splitlines() if "=" in line)
    assert verify_password(valid_eight,values["PROMO_PASSWORD_HASH"])
    with pytest.raises(ValueError):
        prepare_settings("", "a"*7)

    from app.auth import login_html
    assert 'minlength="8"' in login_html().body.decode("utf-8")


def test_provision_preserves_other_env_and_rotates_secret():
    original="OPENAI_API_KEY=test-placeholder\nPROMO_REQUESTS_PER_HOUR=10\nPROMO_AUTH_ENABLED=0\n"
    out1=prepare_settings(original,PASSWORD)
    out2=prepare_settings(original,PASSWORD)
    assert "OPENAI_API_KEY=test-placeholder" in out1
    assert "PROMO_REQUESTS_PER_HOUR=10" in out1
    assert "PROMO_AUTH_ENABLED=1" in out1
    assert PASSWORD not in out1
    values=dict(line.split("=",1) for line in out1.splitlines() if "=" in line)
    assert verify_password(PASSWORD,values["PROMO_PASSWORD_HASH"])
    assert values["PROMO_SESSION_SECRET"] not in out2
    assert values["PROMO_PASSWORD_HASH"] not in out2
    with pytest.raises(ValueError):
        prepare_settings(original,"short")


def test_time4vps_migration_proves_protection_before_removing_basic_auth():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    script=(root/"deploy/time4vps/switch_to_password_login.sh").read_text()
    setup=(root/"deploy/time4vps/configure_caddy.sh").read_text()
    installer=(root/"deploy/time4vps/install.sh").read_text()
    updater=(root/"deploy/time4vps/update.sh").read_text()
    assert "backup_site" in script and "backup_env" in script
    assert "provision_auth.py" in script
    assert 'local_status \'/api/config\'' in script
    assert '"401"' in script
    assert "python3 - \"$SITE\"" in script
    assert script.index("provision_auth.py")<script.index("python3 - \"$SITE\"")
    assert script.index('local_status \'/api/config\'')<script.index("python3 - \"$SITE\"")
    assert "caddy validate" in script and "systemctl reload caddy" in script
    assert "systemctl restart regionalresearch" not in script.lower()
    assert "systemctl stop regionalresearch" not in script.lower()
    assert "rm -rf /opt/regionalresearch" not in script.lower()
    assert "basic_auth" not in setup
    assert "provision_auth.py" in installer
    assert 'code=$(curl' in updater
