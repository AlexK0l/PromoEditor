"""Recompose an ALREADY-PAID exact-copy ZIP with no OpenAI/API calls.

Usage from repository root:
    python -m scripts.recompose_paid_zip OLD.zip NEW_REVIEW.zip

The customer's original art and source files are preserved; the two ad SVG,
PNG and JPEG outputs are replaced by the current art-directed vector renderer.
The exact approved drawing, specs and dimensions are never invented or
re-OCRed. This is a *new* review ZIP, never an in-place source mutation.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from app.ai_exact_copy_render import (
    DEFAULT_STYLE, FORMATS, validate_style,
)
from app.ai_integrated_render import integrated_copy, render_integrated_svg
from app.ai_exact_copy_template import _rasterize_in_worker

_REQUIRED = (
    "brief.json", "typography_layout.json",
    "ai_template_4x3.png", "ai_template_9x16.png",
)
_REPLACE = {
    "corel_4x3.svg","corel_9x16.svg",
    "ai_poster_4x3.png","ai_poster_9x16.png",
    "ai_poster_4x3.jpg","ai_poster_9x16.jpg",
    "poster_copy.json","REVIEW_BEFORE_PUBLICATION.txt",
}
_DRAWING = tuple("originals/drawing_preview"+ext
                 for ext in (".png",".jpg",".jpeg",".webp"))


def _safe_read(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    item=z.getinfo(name)
    if item.file_size > limit:
        raise ValueError("Файл ZIP превышает безопасный лимит: "+name)
    return z.read(name)


def _input_facts(z: zipfile.ZipFile):
    for name in _REQUIRED:
        if name not in z.namelist():
            raise ValueError("Оплаченный ZIP не содержит "+name)
    brief=json.loads(_safe_read(z,"brief.json",512_000))
    layouts=json.loads(_safe_read(z,"typography_layout.json",512_000))
    if not isinstance(brief,dict) or not isinstance(layouts,dict):
        raise ValueError("В ZIP отсутствует пригодный оплаченный бриф/макет.")
    try:
        styles=json.loads(_safe_read(z,"typography_style.json",512_000))
        styles=validate_style(styles)
    except (KeyError,TypeError,ValueError,json.JSONDecodeError):
        styles={fmt:dict(DEFAULT_STYLE) for fmt in FORMATS}
    drawing=next((name for name in _DRAWING if name in z.namelist()),None)
    raw=_safe_read(z,drawing,25_000_000) if drawing else None
    return brief,layouts,styles,raw


def recompose(paid_zip: Path, destination_zip: Path) -> None:
    paid_zip=Path(paid_zip).resolve()
    destination_zip=Path(destination_zip).resolve()
    if not paid_zip.is_file():
        raise FileNotFoundError("Не найден исходный оплаченный ZIP.")
    if paid_zip == destination_zip or destination_zip.exists():
        raise ValueError("Новый ZIP не должен перезаписывать существующий.")
    destination_zip.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(paid_zip,"r") as original:
        if len(original.infolist())>70 or sum(
                i.file_size for i in original.infolist()) > 180_000_000:
            raise ValueError("Входной ZIP слишком большой для безопасной обработки.")
        for item in original.infolist():
            name=item.filename
            if (name.startswith("/") or ".." in Path(name).parts
                    or "\\" in name):
                raise ValueError("Небезопасное имя файла в ZIP.")
        brief,layout,styles,drawing=_input_facts(original)
        copy=integrated_copy(brief,drawing=bool(drawing))
        # Use ONLY the source artwork the customer already paid for.
        # This script never imports or creates an OpenAI client.
        with tempfile.TemporaryDirectory(prefix="promo-recompose-") as temp:
            work=Path(temp)
            for fmt in FORMATS:
                art_raw=_safe_read(
                    original,"ai_template_"+fmt+".png",30_000_000)
                with Image.open(io.BytesIO(art_raw)) as art:
                    art.load()
                    svg=render_integrated_svg(
                        brief,fmt,art,layout[fmt],styles[fmt],
                        drawing=drawing,copy_override=copy)
                svg_path=work/("corel_"+fmt+".svg")
                svg_path.write_bytes(svg)
                _rasterize_in_worker(
                    svg_path,work/("ai_poster_"+fmt+".png"),
                    work/("ai_poster_"+fmt+".jpg"),
                )
            temp_out=destination_zip.with_name(
                destination_zip.name+".partial")
            if temp_out.exists():
                raise ValueError("Уже существует промежуточный архив.")
            try:
                with zipfile.ZipFile(temp_out,"w",compression=zipfile.ZIP_STORED) as out:
                    for item in original.infolist():
                        if item.is_dir() or item.filename in _REPLACE:
                            continue
                        # Copy in chunks to avoid retaining original 20-MB
                        # engineering drawings and product photos in RAM.
                        with original.open(item,"r") as src:
                            with out.open(item.filename,"w") as dst:
                                shutil.copyfileobj(src,dst,length=1<<20)
                    for fmt in FORMATS:
                        for name in (
                            "corel_"+fmt+".svg",
                            "ai_poster_"+fmt+".png",
                            "ai_poster_"+fmt+".jpg",
                        ):
                            out.write(work/name,arcname=name)
                    out.writestr(
                        "poster_copy.json",
                        json.dumps(copy,ensure_ascii=False,indent=2),
                    )
                    out.writestr(
                        "REVIEW_BEFORE_PUBLICATION.txt",
                        "БЕСПЛАТНАЯ ПЕРЕКОМПОНОВКА РАНЕЕ ОПЛАЧЕННОГО ФОНА.\n"
                        "Оба плаката 4:3 и 9:16 содержат исходный чертёж "
                        "(если загружен), ключевые технические характеристики, "
                        "размеры, цену и контакты. Полный технический лист "
                        "в ZIP сохранён дополнительно.\n"
                        "Новых запросов OpenAI или платежей не было. "
                        "Проверьте точность техники, внешний вид, контраст "
                        "и факты перед публикацией.\n",
                    )
                os.replace(temp_out,destination_zip)
            finally:
                temp_out.unlink(missing_ok=True)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paid_zip",type=Path)
    parser.add_argument("new_review_zip",type=Path)
    args=parser.parse_args()
    recompose(args.paid_zip,args.new_review_zip)
    print("Готово без OpenAI:",args.new_review_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
