#!/usr/bin/env python3
"""Create a root-only single-password auth configuration (never log the password)."""
import getpass
import hashlib
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path

KEYS=("PROMO_AUTH_ENABLED","PROMO_PASSWORD_HASH","PROMO_SESSION_SECRET")


def prepare_settings(source,password):
    if not 12<=len(password)<=256:
        raise ValueError("Пароль должен содержать 12–256 символов.")
    salt=secrets.token_bytes(24)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,600_000)
    new={
      "PROMO_AUTH_ENABLED":"1",
      "PROMO_PASSWORD_HASH":f"pbkdf2_sha256:600000:{salt.hex()}:{digest.hex()}",
      "PROMO_SESSION_SECRET":secrets.token_urlsafe(48)
    }
    kept=[]
    for line in source.splitlines():
        match=re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=",line)
        if not (match and match.group(1) in KEYS):
            kept.append(line)
    return "\n".join(kept).rstrip()+"\n"+"\n".join(k+"="+new[k] for k in KEYS)+"\n"


def provision(path):
    if os.geteuid()!=0:
        raise PermissionError("Run as root.")
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode)&0o077:
        raise PermissionError("Server env file must exist with mode 0600.")
    print("Новый пароль для PromoEditor: 12–256 символов. Вы можете использовать знакомый вам пароль.")
    one=getpass.getpass("Новый пароль (скрыт): ")
    two=getpass.getpass("Повторите пароль: ")
    if not secrets.compare_digest(one,two):
        raise ValueError("Пароли не совпадают.")
    updated=prepare_settings(path.read_text(encoding="utf-8"),one)
    one=two=""
    fd,tmp=tempfile.mkstemp(prefix=".promoeditor.env.",dir=str(path.parent),text=True)
    try:
        os.fchmod(fd,0o600)
        os.fchown(fd,0,0)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(updated)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print("Хеш пароля и секрет сессии сохранены только в защищённом файле VPS.")


if __name__=="__main__":
    try:
        provision(Path(sys.argv[1]) if len(sys.argv)>1 else Path("/etc/promoeditor/promoeditor.env"))
    except (OSError,PermissionError,ValueError) as exc:
        print("Ошибка настройки входа: "+str(exc),file=sys.stderr)
        sys.exit(1)
