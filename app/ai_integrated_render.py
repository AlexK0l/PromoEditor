"""AI-art-backed, format-specific advertising composition with REAL drawing.

The original paid artwork remains untouched under editable SVG layers.
The two ad formats get deliberately DIFFERENT layouts, not a cropped photo
with identical text cards. Approved technical facts and the exact uploaded
engineering drawing are printed on BOTH finished advertisements, not only
on an extra sheet. Image, price and specs are separate CorelDRAW SVG layers.

This is a local render-only stage: no paid OpenAI calls, no new source facts.
"""
from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET

from PIL import Image

from .ai_exact_copy_render import (
    DEFAULT_STYLE, FONTS, FORMATS, HEX, _size_and_lines, poster_copy,
)
from .editable_export import NS, XLINK, Scene

_DARK = "#10151E"
_LIGHT = "#F7F8FA"
_WHITE = "#F7F9FC"
_INK = "#1B2634"
_MUTED = "#586474"
_DIVIDER = "#CCD4DF"
_LABELS = {
    "facts": "КЛЮЧЕВЫЕ ТТХ",
    "dims": "ГАБАРИТЫ",
    "drawing": "ИНЖЕНЕРНАЯ СХЕМА",
    "contacts": "КОНТАКТЫ",
}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i+2], 16)/255 for i in (1,3,5)]
    values = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4
              for c in channels]
    return values[0]*.2126 + values[1]*.7152 + values[2]*.0722


def _contrast(a: str, b: str) -> float:
    lo, hi = sorted((_luminance(a), _luminance(b)))
    return (hi+.05)/(lo+.05)


def _palette(brief: dict, styling: dict) -> dict:
    """Honor the actual customer's red/black/white brand, not random AI yellow.

    The legacy vision stage might suggest white ink because the old renderer
    forced ALL text onto black rounded boxes. But the integrated facts panel
    is deliberately LIGHT, so the actual contrast must be checked there.
    """
    accent = str(brief.get("accent") or "#C51629").upper()
    if not HEX.fullmatch(accent):
        accent = "#C51629"
    # Keep the EXACT customer color for graphic lines. If it is too bright
    # to serve as small text on ivory, darken ONLY the caption text tint.
    caption_accent = accent
    for _ in range(16):
        if _contrast(caption_accent, _LIGHT) >= 4.5:
            break
        channels = [int(caption_accent[i:i+2],16)
                    for i in (1,3,5)]
        caption_accent = "#" + "".join(
            f"{round(v*.92):02X}" for v in channels)
    proposed_ink = str(styling.get("ink") or "")
    proposed_muted = str(styling.get("muted") or "")
    ink = (proposed_ink.upper()
           if HEX.fullmatch(proposed_ink)
           and _contrast(proposed_ink, _LIGHT) >= 7
           else _INK)
    muted = (proposed_muted.upper()
             if HEX.fullmatch(proposed_muted)
             and _contrast(proposed_muted, _LIGHT) >= 4.5
             else _MUTED)
    return {"accent":accent, "accent_text":caption_accent,
            "ink":ink, "muted":muted, "white":_WHITE}


def _line(scene: Scene, x1: float, y1: float, x2: float, y2: float,
          color: str = _DIVIDER, width: float = 2) -> None:
    scene.el("decor", "line", "editorial-rule", {
        "x1":x1, "y1":y1, "x2":x2, "y2":y2,
        "stroke":color, "stroke-width":width,
    })


def _type(scene: Scene, *, value: str, role: str | None, group: str,
          x: float, y: float, w: float, h: float, size: int,
          minimum: int, family: str, color: str, bold: bool = False,
          letter_spacing: float = 0) -> None:
    """No abbreviation, bitmap text, ellipsis or silent overflow."""
    if not value:
        return
    if w <= 0 or h <= 0:
        raise ValueError("Нет места для полного текста рекламной композиции.")
    # The trusted _size_and_lines uses the exact Cyrillic-capable font files.
    # Reserve enough width for tracking on short editorial headings.
    tracking = letter_spacing * max(0, len(value)-1)
    safe_w = w - tracking if letter_spacing else w
    if safe_w <= 0:
        raise ValueError("Не хватает ширины для заголовка.")
    actual_size, rows = _size_and_lines(
        [value], safe_w, h, family, bold, min(int(size),int(h*.76)),minimum)
    attrs = {
        "x":x, "y":y+actual_size, "fill":color,
        "font-family":family, "font-size":actual_size,
        "font-weight":"700" if bold else "400",
        "xml:space":"preserve",
        "data-exact-copy":value if role else None,
        "data-verified-role":role,
        "letter-spacing":letter_spacing if letter_spacing else None,
    }
    text = scene.el(group,"text","exact-"+(role or "editorial-label"),attrs)
    for i, row in enumerate(rows):
        span=ET.SubElement(text,f"{{{NS}}}tspan",{
            "x":str(round(x,2)),
            "dy":"0" if i == 0 else str(round(actual_size*1.24,2)),
        })
        span.text=row


def _label(scene: Scene, value: str, x: float, y: float, w: float,
           color: str, font: str, *, size: int = 20, h: int = 32) -> None:
    _type(scene,value=value,role=None,group="heading",
          x=x,y=y,w=w,h=h,size=size,minimum=15,family=font,
          color=color,bold=True)


def _drawing(scene: Scene, drawing: bytes, x: float, y: float,
             w: float, h: float) -> None:
    """Preserve the actual source drawing as a printable, separable SVG image.

    Downsample BEFORE RGBA conversion to prevent memory surges on the 1.9-GB
    VPS. The exact original image is independently preserved in the ZIP.
    """
    with Image.open(io.BytesIO(drawing)) as source:
        source.draft("RGB",(1000,750))
        source.thumbnail((1200,900),Image.Resampling.LANCZOS)
        buffer=io.BytesIO()
        source.convert("RGB").save(buffer,format="JPEG",quality=88)
    encoded=base64.b64encode(buffer.getvalue()).decode("ascii")
    scene.el("photos","image","customer-technical-drawing",{
        "x":x, "y":y, "width":w, "height":h,
        "preserveAspectRatio":"xMidYMid meet",
        "data-source":"original-customer-drawing",
        f"{{{XLINK}}}href":"data:image/jpeg;base64,"+encoded,
    })


def _art(scene: Scene, art: Image.Image) -> None:
    buffer=io.BytesIO()
    art.convert("RGB").save(buffer,format="JPEG",quality=88,subsampling=0)
    scene.el("background","image","paid-ai-illustration",{
        "x":0,"y":0,"width":scene.w,"height":scene.h,
        "preserveAspectRatio":"xMidYMid meet",
        f"{{{XLINK}}}href":"data:image/jpeg;base64,"
        +base64.b64encode(buffer.getvalue()).decode("ascii"),
    })


def _product_edges(fmt: str, slot: dict) -> tuple[int,int]:
    if not isinstance(slot,dict) or any(
            type(slot.get(k)) is not int for k in ("x","y","w","h")):
        raise ValueError("AI не определил реальные границы техники.")
    x,y,w,h=(slot[k] for k in ("x","y","w","h"))
    if not (0 <= x < 1000 and 0 <= y < 1000 and
            100 <= w <= 1000 and 100 <= h <= 1000 and
            x+w <= 1000 and y+h <= 1000):
        raise ValueError("AI вывел прицеп за пределы плаката.")
    height=FORMATS[fmt][1]
    return round(y*height/1000),round((y+h)*height/1000)


def _safe_overlay_zones(fmt: str, product: dict) -> tuple[int,int]:
    """Never cover wheels/chassis to make room for infographic or drawing."""
    top,bottom=_product_edges(fmt,product)
    if fmt=="4x3":
        if top < 206:
            raise ValueError(
                "Прицеп перекрывает шапку 4:3. Нужна другая AI-композиция.")
        panel=max(808,bottom+18)
        if panel > 872:
            raise ValueError(
                "Прицеп перекрывает техзону 4:3. Нужна новая композиция, "
                "платные изображения сохранены.")
        return 207,panel
    if top < 326:
        raise ValueError(
            "Прицеп перекрывает шапку 9:16. Нужна другая AI-композиция.")
    panel=max(1305,bottom+30)
    if panel > 1460:
        raise ValueError(
            "Прицеп перекрывает техзону 9:16. Нужна настоящая вертикальная "
            "композиция, платные изображения сохранены.")
    return 325,panel


def _paint_landscape(scene: Scene, data: dict, drawing: bytes | None,
                     family: str, palette: dict, panel_y: int) -> None:
    accent=palette["accent"]; ink=palette["ink"]
    scene.rect("decor",0,0,1440,207,_DARK,opacity=.90,
               ident="wide-editorial-masthead")
    scene.rect("decor",0,207,1440,4,accent,ident="masthead-accent")
    scene.rect("decor",52,30,7,60,accent,ident="brand-rule")

    for role, x,y,w,h,size,minimum,color,bold,group in (
        ("brand",75,23,600,44,30,24,_WHITE,True,"heading"),
        ("model",74,78,700,90,67,48,_WHITE,True,"heading"),
        ("category",75,158,510,34,19,16,"#CDD4DC",False,"heading"),
        ("claims",770,159,590,38,26,20,_WHITE,True,"claims"),
        ("price",895,36,515,111,47,35,_WHITE,True,"price"),
    ):
        values=data.get(role) or []
        if values:
            _type(scene,value=values[0],role=role,group=group,
                  x=x,y=y,w=w,h=h,size=size,minimum=minimum,
                  color=color,family=family,bold=bold)
    panel_h=1080-panel_y-28
    scene.rect("decor",31,panel_y,1378,panel_h,_LIGHT,
               rad=17,ident="integrated-tech-panel-wide")
    scene.rect("decor",31,panel_y,1378,6,accent,
               ident="integrated-tech-accent-wide")
    for x in (363,758,1041):
        _line(scene,x,panel_y+30,x,panel_y+panel_h-26)
    _label(scene,"ЧЕРТЁЖ · ОРИГИНАЛ",60,panel_y+9,270,palette["accent_text"],family,
           size=16,h=25)
    if drawing:
        scene.rect("decor",56,panel_y+39,275,panel_h-62,"#FFFFFF",
                   rad=8,ident="original-drawing-surface-wide")
        _drawing(scene,drawing,64,panel_y+41,262,panel_h-68)
    elif data.get("slogan"):
        _type(scene,value=data["slogan"][0],role="slogan",group="claims",
              x=63,y=panel_y+52,w=270,h=panel_h-82,
              size=25,minimum=18,family=family,color=ink,bold=True)
    _label(scene,"КЛЮЧЕВЫЕ ТТХ",387,panel_y+9,346,palette["accent_text"],family,
           size=21,h=31)
    specs=(data.get("specs") or [])[:3]
    spec_step=min(52,int((panel_h-65)/max(3,len(specs) or 1)))
    for i,value in enumerate(specs):
        _type(scene,value=value,role="specs",group="specs",
              x=390,y=panel_y+53+i*spec_step,
              w=341,h=spec_step-2,
              size=22,minimum=17,family=family,color=ink)
    _label(scene,"ГАБАРИТЫ",783,panel_y+9,233,palette["accent_text"],family,
           size=21,h=31)
    dims=(data.get("dimensions") or [])[:2]
    dim_step=min(67,int((panel_h-65)/max(2,len(dims) or 1)))
    for i,value in enumerate(dims):
        _type(scene,value=value,role="dimensions",group="dimensions",
              x=787,y=panel_y+53+i*dim_step,w=235,h=dim_step-3,
              size=21,minimum=16,family=family,color=ink)
    _label(scene,"КОНТАКТЫ",1065,panel_y+9,305,palette["accent_text"],family,
           size=21,h=31)
    phones=(data.get("phones") or [])[:2]
    phone_step=min(66,int((panel_h-65)/max(2,len(phones) or 1)))
    for i,value in enumerate(phones):
        _type(scene,value=value,role="phones",group="contacts",
              x=1065,y=panel_y+53+i*phone_step,w=312,h=phone_step-3,
              size=23,minimum=18,family=family,color=ink)


def _paint_portrait(scene: Scene, data: dict, drawing: bytes | None,
                    family: str, palette: dict, panel_y: int,
                    product_bottom: int) -> None:
    """Independent portrait hierarchy; never reframe the 4:3 composition."""
    accent=palette["accent"];ink=palette["ink"]
    scene.rect("decor",0,0,1080,325,_DARK,opacity=.93,
               ident="portrait-editorial-masthead")
    scene.rect("decor",0,324,1080,5,accent,ident="portrait-header-rule")
    scene.rect("decor",320,56,7,68,accent,ident="portrait-brand-rule")
    for role,x,y,w,h,size,minimum,color,bold,group in (
        ("brand",347,44,700,46,34,26,_WHITE,True,"heading"),
        ("model",343,125,696,93,62,45,_WHITE,True,"heading"),
        ("category",344,228,688,38,22,17,"#CBD3DE",False,"heading"),
        ("claims",344,272,680,41,25,19,_WHITE,True,"claims"),
    ):
        values=data.get(role) or []
        if values:
            _type(scene,value=values[0],role=role,group=group,
                  x=x,y=y,w=w,h=h,size=size,minimum=minimum,
                  color=color,family=family,bold=bold)
    # Hide any AI-generated placeholder icon strip without covering wheels.
    # Do not paint the technical backdrop over low wheel/chassis pixels.
    # The old first draft used panel_y-60, which can move ABOVE the actual
    # product bottom when a trailer sits lower than the example photo.
    slate_y=max(1218,product_bottom+14)
    scene.rect("decor",0,slate_y,1080,1920-slate_y,_DARK,
               ident="portrait-technical-stage")
    scene.rect("decor",0,slate_y,1080,5,accent,
               ident="portrait-technical-rule")
    card_h=1735-panel_y
    scene.rect("decor",42,panel_y,996,card_h,_LIGHT,
               rad=17,ident="integrated-tech-panel-portrait")
    scene.rect("decor",42,panel_y,996,7,accent,
               ident="integrated-tech-accent-portrait")
    _line(scene,499,panel_y+44,499,panel_y+card_h-22)
    _label(scene,"ИНЖЕНЕРНАЯ СХЕМА",74,panel_y+15,390,palette["accent_text"],family,
           size=19,h=28)
    if drawing:
        scene.rect("decor",66,panel_y+54,410,card_h-93,"#FFFFFF",
                   rad=8,ident="original-drawing-surface-portrait")
        _drawing(scene,drawing,72,panel_y+57,394,card_h-100)
    elif data.get("slogan"):
        _type(scene,value=data["slogan"][0],role="slogan",group="claims",
              x=75,y=panel_y+79,w=390,h=card_h-124,
              size=26,minimum=19,family=family,color=ink,bold=True)
    _label(scene,"ТЕХНИКА В ЦИФРАХ",532,panel_y+15,461,palette["accent_text"],family,
           size=23,h=35)
    specs=(data.get("specs") or [])[:3]
    # Adaptive row rhythm: the AI may extend the vehicle lower in the
    # frame, leaving a smaller safe panel. Reserve space for BOTH the specs
    # and dimensions; never let one fact bleed into the footer.
    row_step=min(57,max(36,int((card_h-142)/3)))
    for i,value in enumerate(specs):
        _type(scene,value=value,role="specs",group="specs",
              x=534,y=panel_y+58+i*row_step,w=468,h=row_step-3,
              size=24,minimum=17,family=family,color=ink)
    divider=panel_y+58+3*row_step+5
    _line(scene,532,divider,990,divider)
    dims=(data.get("dimensions") or [])[:2]
    dim_y=divider+10
    dim_step=min(53,int((panel_y+card_h-14-dim_y)/2))
    if dims and dim_step < 26:
        raise ValueError(
            "AI-фон не оставил достаточно места для габаритов в 9:16. "
            "Чертёж и ТТХ нельзя перекрывать.")
    for i,value in enumerate(dims):
        _type(scene,value=value,role="dimensions",group="dimensions",
              x=534,y=dim_y+i*dim_step,w=468,h=dim_step-1,
              size=23,minimum=17,family=family,color=ink)
    scene.rect("decor",42,1763,996,114,"#202833",
               rad=16,ident="portrait-sale-cta")
    scene.rect("decor",42,1763,8,114,accent,
               ident="portrait-price-rule")
    if data.get("price"):
        _type(scene,value=data["price"][0],role="price",group="price",
              x=75,y=1773,w=490,h=92,size=43,minimum=30,
              family=family,color=_WHITE,bold=True)
    for i,value in enumerate((data.get("phones") or [])[:2]):
        _type(scene,value=value,role="phones",group="contacts",
              x=587,y=1777+i*48,w=425,h=43,
              size=26,minimum=20,family=family,color=_WHITE,bold=True)


def render_integrated_svg(
    brief: dict, fmt: str, artwork: Image.Image, slots: dict,
    styling: dict, *, drawing: bytes | None = None,
    copy_override: dict | None = None,
) -> bytes:
    """Both social ads, with drawing + key specs INSIDE the poster artwork.

    The original external technical sheet is still exported with all 17
    facts, but it is no longer the ONLY place the actual drawing appears.
    """
    if fmt not in FORMATS or artwork.size != FORMATS[fmt]:
        raise ValueError("Размер оплаченного художественного фона неверный.")
    if not isinstance(slots,dict):
        raise ValueError("Отсутствуют координаты техники для плаката.")
    family=str(styling.get("font_family") or "")
    if family not in FONTS:
        family=DEFAULT_STYLE["font_family"]
    copy=copy_override if copy_override is not None else poster_copy(brief)
    if not isinstance(copy,dict):
        raise ValueError("Некорректные подтверждённые рекламные данные.")
    _,panel_y=_safe_overlay_zones(fmt,slots.get("product"))
    palette=_palette(brief,styling)
    scene=Scene(fmt,brief.get("accent"),brief.get("style"))
    scene.groups["background"].clear()
    scene.groups["decor"].clear()
    _art(scene,artwork)
    if fmt=="4x3":
        _paint_landscape(scene,copy,drawing,family,palette,panel_y)
    else:
        _,product_bottom=_product_edges(fmt,slots["product"])
        _paint_portrait(
            scene,copy,drawing,family,palette,panel_y,product_bottom)
    return scene.export()
