"""Password-only FastAPI login, enabled explicitly on the private VPS.

Protected by PBKDF2-HMAC password hash, signed Secure HttpOnly cookie,
failed-attempt throttle, Origin checks, and fail-closed configuration.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

COOKIE_NAME="promoeditor_session"
SESSION_SECONDS=12*3600
FAILED_WINDOW=15*60
FAILED_LIMIT=8
_ITERATIONS=600_000
_FAILURES=defaultdict(list)
_FAIL_LOCK=threading.Lock()


def enabled():
    return os.getenv("PROMO_AUTH_ENABLED","").strip().lower() in ("1","true","on","yes")


def hash_password(password:str,*,salt:bytes|None=None,iterations:int=_ITERATIONS)->str:
    if not isinstance(password,str) or not 12<=len(password)<=256:
        raise ValueError("Пароль должен содержать 12–256 символов.")
    salt=salt or secrets.token_bytes(24)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,iterations)
    return f"pbkdf2_sha256:{iterations}:{salt.hex()}:{digest.hex()}"


def _password_parts(stored:str):
    try:
        algo,iterations,salt,digest=stored.split(":")
        n=int(iterations)
        s=bytes.fromhex(salt)
        d=bytes.fromhex(digest)
        if algo!="pbkdf2_sha256" or not 300_000<=n<=1_500_000 or not 16<=len(s)<=64 or len(d)!=32:
            return None
        return n,s,d
    except (ValueError,TypeError,AttributeError):
        return None


def verify_password(password:str,stored:str)->bool:
    if not isinstance(password,str) or len(password)>256:
        return False
    parts=_password_parts(stored)
    if not parts:
        return False
    n,salt,digest=parts
    actual=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,n)
    return hmac.compare_digest(actual,digest)


def configured():
    return bool(_password_parts(os.getenv("PROMO_PASSWORD_HASH",""))) and len(os.getenv("PROMO_SESSION_SECRET",""))>=40


def issue_cookie(*,now:int|None=None)->str:
    timestamp=int(time.time()) if now is None else now
    message=f"v1.{timestamp}.{secrets.token_hex(12)}"
    sig=hmac.new(os.environ["PROMO_SESSION_SECRET"].encode(),message.encode("ascii"),hashlib.sha256).hexdigest()
    return message+"."+sig


def valid_cookie(token:str|None,*,now:int|None=None)->bool:
    if not token or len(token)>200 or not configured():
        return False
    parts=token.split(".")
    if len(parts)!=4 or parts[0]!="v1":
        return False
    try:
        issued=int(parts[1])
        current=int(time.time()) if now is None else now
        if issued<0 or issued>current+60 or current-issued>SESSION_SECONDS:
            return False
        if len(parts[2])!=24 or len(parts[3])!=64:
            return False
        int(parts[2],16);int(parts[3],16)
        message=".".join(parts[:3])
        sig=hmac.new(os.environ["PROMO_SESSION_SECRET"].encode(),message.encode("ascii"),hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig,parts[3])
    except (ValueError,UnicodeEncodeError):
        return False


def _origin_ok(request:Request)->bool:
    host=request.headers.get("host","").lower().strip()
    for header in ("origin","referer"):
        supplied=request.headers.get(header)
        if supplied:
            parsed=urlsplit(supplied)
            if parsed.scheme not in ("http","https") or parsed.netloc.lower()!=host:
                return False
    return True


def _fail_count(ip:str):
    now=time.monotonic()
    with _FAIL_LOCK:
        values=[x for x in _FAILURES[ip] if now-x<FAILED_WINDOW]
        _FAILURES[ip]=values
        return len(values)


def _record_failure(ip:str):
    now=time.monotonic()
    with _FAIL_LOCK:
        _FAILURES[ip]=[x for x in _FAILURES[ip] if now-x<FAILED_WINDOW]+[now]


def _clear_failures(ip:str):
    with _FAIL_LOCK:
        _FAILURES.pop(ip,None)


LOGIN_PAGE="""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Вход — PromoEditor</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;
background:linear-gradient(140deg,#edf3ff,#f6f8fb 55%,#fff);color:#192438;
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;padding:20px}
.card{width:min(100%,420px);background:#fff;border:1px solid #e3e9f0;border-radius:22px;
padding:36px;box-shadow:0 22px 70px rgba(25,39,70,.09)}
.logo{display:grid;place-items:center;height:45px;width:45px;background:#e7eeff;
color:#315ddc;border-radius:13px;font-weight:900;font-size:24px;margin-bottom:18px}
h1{margin:0 0 10px;font-size:26px;letter-spacing:-.7px}
p{color:#6b778d;margin:0 0 25px;font-size:14px}
label{display:block;font-weight:700;font-size:13px;margin:0 0 8px}
input{width:100%;display:block;border:1px solid #bbc6d8;border-radius:11px;padding:13px 14px;font:inherit}
input:focus-visible{outline:3px solid #b8c9f6;outline-offset:2px}
button{width:100%;border:0;background:#315ddc;color:white;margin-top:15px;border-radius:11px;
padding:14px;font-size:15px;font-weight:750;cursor:pointer}
button:hover{background:#244fbb}
.note{margin-top:20px;color:#7b8798;font-size:12px}
.error{padding:11px 13px;background:#fff0f2;color:#a02a40;border-radius:9px;
border:1px solid #f5ced5;font-size:13px;margin-bottom:16px}
</style></head><body><main class="card">
<span class="logo" aria-hidden="true">P</span>
<h1>Вход в PromoEditor</h1><p>Введите пароль для доступа к генератору и редактору промоматериалов.</p>
{{ERROR}}
<form action="/login" method="post">
<label for="password">Пароль</label>
<input id="password" name="password" type="password" required autofocus
autocomplete="current-password" maxlength="256">
<button type="submit">Войти</button></form>
<div class="note">Без логина. Сессия в браузере действует до 12 часов.</div>
</main></body></html>"""


def login_html(error:str|None=None,code:int=200):
    html=LOGIN_PAGE.replace("{{ERROR}}",
        '<div class="error" role="alert">'+error+'</div>' if error else "")
    return HTMLResponse(html,status_code=code,headers={
        "Cache-Control":"no-store",
        "X-Frame-Options":"DENY",
        "X-Content-Type-Options":"nosniff",
        "Referrer-Policy":"no-referrer",
        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    })


async def guard(request:Request,call_next):
    if not enabled():
        return await call_next(request)
    if not configured():
        return PlainTextResponse("Вход PromoEditor не настроен. Обратитесь к администратору.",
                                 status_code=503,headers={"Cache-Control":"no-store"})
    path=request.url.path
    if path=="/login" and request.method in ("GET","HEAD","POST"):
        return await call_next(request)
    if request.method in ("POST","PUT","PATCH","DELETE") and not _origin_ok(request):
        return JSONResponse({"detail":"Недопустимый источник запроса."},status_code=403)
    if valid_cookie(request.cookies.get(COOKIE_NAME)):
        result=await call_next(request)
        if path=="/" or path.startswith("/files/"):
            result.headers["Cache-Control"]="private, no-store"
        return result
    if request.method in ("GET","HEAD") and not path.startswith(("/api/","/files/","/static/")):
        return RedirectResponse("/login",status_code=303,headers={"Cache-Control":"no-store"})
    return JSONResponse({"detail":"Требуется вход по паролю."},status_code=401,
                        headers={"Cache-Control":"no-store"})


async def login_get(request:Request):
    if not enabled() or valid_cookie(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/",status_code=303)
    return login_html()


async def login_post(request:Request):
    if not enabled():
        return RedirectResponse("/",status_code=303)
    if not _origin_ok(request):
        return login_html("Некорректный запрос.",403)
    if int(request.headers.get("content-length") or 0)>2048:
        return login_html("Слишком длинный пароль.",413)
    ip=request.client.host if request.client else "unknown"
    if _fail_count(ip)>=FAILED_LIMIT:
        return login_html("Слишком много попыток. Попробуйте через 15 минут.",429)
    try:
        form=await request.form()
        password=form.get("password","")
    except Exception:
        password=""
    if not isinstance(password,str) or not verify_password(password,os.getenv("PROMO_PASSWORD_HASH","")):
        _record_failure(ip)
        return login_html("Неверный пароль.",401)
    _clear_failures(ip)
    response=RedirectResponse("/",status_code=303,headers={"Cache-Control":"no-store"})
    response.set_cookie(COOKIE_NAME,issue_cookie(),max_age=SESSION_SECONDS,
                        path="/",secure=True,httponly=True,samesite="lax")
    return response


async def logout_post(request:Request):
    response=RedirectResponse("/login" if enabled() else "/",status_code=303,
                              headers={"Cache-Control":"no-store"})
    response.delete_cookie(COOKIE_NAME,path="/",secure=True,httponly=True,samesite="lax")
    return response
