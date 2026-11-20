"""Trusted exact-copy SVG renderer for AI-authored textless promo artwork.

AI supplies art, empty-slot coordinates and typographic styling ONLY. Every
letter/price/phone/technical fact comes from the normalized server-side brief.
Overflow fails visibly; no invented text, ellipses, cropping or bitmap AI
repainting of the final lettering. The final SVG remains CorelDRAW editable.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageFont

from .ai_layout import _intersection
from .campaign_layout import _format_price
from .editable_export import NS, Scene, _font
from .render import compute_roi

ROLES = (
    "brand", "model", "category", "slogan", "specs", "dimensions",
    "benefits", "claims", "proofs", "price", "phones", "roi",
)
VISUAL = ("product", "logo", "drawing")
ALL_SLOTS = ROLES + VISUAL
FORMATS = {"4x3": (1440, 1080), "9x16": (1080, 1920)}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONTS = {
    "DejaVu Sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "DejaVu Sans Condensed": (
        "DejaVuSansCondensed.ttf", "DejaVuSansCondensed-Bold.ttf"),
}
DEFAULT_STYLE = {
    "font_family": "DejaVu Sans Condensed",
    "ink": "#18212C", "accent": "#C51629", "muted": "#3B4656",
    "scale_percent": 100,
}
BASE_PX = {
    "brand": 34, "model": 66, "category": 24, "slogan": 31,
    "specs": 23, "dimensions": 22, "benefits": 24,
    "claims": 23, "proofs": 20, "price": 48, "phones": 29, "roi": 21,
}
GROUPS = {
    "brand": "heading", "model": "heading", "category": "heading",
    "slogan": "claims", "specs": "specs", "dimensions": "dimensions",
    "benefits": "benefits", "claims": "claims", "proofs": "benefits",
    "price": "price", "phones": "contacts", "roi": "roi",
}


def verified_copy(brief: dict) -> dict[str, list[str]]:
    """All displayed copy is assembled from approved form fields only."""
    def plain(key):
        value = str(brief.get(key) or "").strip()
        return [value] if value else []
    def entries(key):
        return [str(value).strip() for value in (brief.get(key) or [])
                if str(value).strip()]
    def pairs(key):
        return [
            str(label).strip() + ": " + str(value).strip()
            for label, value in (brief.get(key) or [])
            if str(label).strip() and str(value).strip()
        ]
    price = plain("price")
    if price:
        price = [
            (_format_price(price[0]) + " "
             + str(brief.get("currency") or "").strip()).strip()
            + (" с НДС" if brief.get("vat", True) else "")
        ]
    roi = []
    if brief.get("show_roi"):
        values = compute_roi(brief)
        if values and values.get("annual") is not None:
            roi = [
                "Дополнительная выручка за год: "
                + _format_price(str(values["annual"]))
                + " " + str(brief.get("currency") or "").strip(),
            ]
    return {
        "brand": plain("brand"),
        "model": plain("model"),
        "category": plain("category"),
        "slogan": plain("slogan"),
        "specs": pairs("specs"),
        "dimensions": pairs("dimensions"),
        "benefits": entries("benefits"),
        "claims": entries("hero_claims"),
        "proofs": entries("proof_points"),
        "price": price,
        "phones": entries("phones"),
        "roi": roi,
    }


def validate_slots(geometry: dict, copy: dict, *,
                   has_logo=False, has_drawing=False) -> dict:
    """Reject hallucinated, overlapping, unreadable or off-canvas zones.

    Do NOT fall back to a rigid server template: those are the bad layouts
    which the customer explicitly rejected.
    """
    if not isinstance(geometry, dict) or set(geometry) != set(FORMATS):
        raise ValueError("AI не вернул зоны обоих форматов.")
    result = {}
    for fmt, value in geometry.items():
        if not isinstance(value, dict) or set(value) != set(ALL_SLOTS):
            raise ValueError(f"AI не подготовил все зоны макета {fmt}.")
        validated = {}
        for role, box in value.items():
            if not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}:
                raise ValueError(f"Неправильная текстовая зона: {role}.")
            x, y, w, h = (box[key] for key in ("x", "y", "w", "h"))
            if any(type(v) is not int for v in (x, y, w, h)):
                raise ValueError("AI вернул нецелые координаты текста.")
            if not (0 <= x <= 1000 and 0 <= y <= 1000
                    and 30 <= w <= 1000 and 20 <= h <= 1000
                    and x + w <= 1000 and y + h <= 1000):
                raise ValueError(f"AI вывел зону {role} за границы {fmt}.")
            validated[role] = box
        active = [role for role in ROLES if copy.get(role)]
        if has_logo:
            active.append("logo")
        if has_drawing:
            active.append("drawing")
        for i, role in enumerate(active):
            first = validated[role]
            if (first["x"] < 12 or first["y"] < 12 or
                    first["x"] + first["w"] > 988 or
                    first["y"] + first["h"] > 988):
                raise ValueError(f"Недостаточный отступ у текста {role} ({fmt}).")
            for other in active[i+1:]:
                second = validated[other]
                smaller = min(first["w"]*first["h"], second["w"]*second["h"])
                if _intersection(first, second) > smaller * .02:
                    raise ValueError(
                        f"AI пересёк области {role} и {other} ({fmt}).")
            # The product itself is painted by AI; keep text clear of it.
            product = validated["product"]
            if _intersection(first, product) > first["w"]*first["h"]*.04:
                raise ValueError(f"AI поместил {role} поверх техники ({fmt}).")
        result[fmt] = validated
    return result


def validate_style(style: dict) -> dict:
    if not isinstance(style, dict) or set(style) != set(FORMATS):
        raise ValueError("AI не вернул стили двух форматов.")
    for fmt, options in style.items():
        if not isinstance(options, dict) or set(options) != set(DEFAULT_STYLE):
            raise ValueError(f"Неполная AI-типографика {fmt}.")
        if options["font_family"] not in FONTS:
            raise ValueError("Неподдерживаемый шрифт AI.")
        if any(not isinstance(options[k], str)
               or not HEX.fullmatch(options[k])
               for k in ("ink", "accent", "muted")):
            raise ValueError("AI предложил неверный цвет текста.")
        if (type(options["scale_percent"]) is not int
                or not 78 <= options["scale_percent"] <= 120):
            raise ValueError("AI предложил опасный масштаб шрифта.")
    return style


def _font_for(family: str, size: int, bold: bool):
    name = FONTS[family][int(bold)]
    path = "/usr/share/fonts/truetype/dejavu/" + name
    try:
        return ImageFont.truetype(path, int(size))
    except OSError:
        return _font(size, bold)


def _wrap_exact(text: str, font, width: float) -> list[str] | None:
    result = []
    for paragraph in text.replace("\r", "").split("\n"):
        if not paragraph.strip():
            result.append("")
            continue
        line = ""
        for word in paragraph.split():
            if font.getlength(word) > width:
                return None
            joined = (line + " " + word).strip()
            if line and font.getlength(joined) > width:
                result.append(line)
                line = word
            else:
                line = joined
        result.append(line)
    return result


def _size_and_lines(values: list[str], width: float, height: float,
                    family: str, bold: bool, ideal: int, minimum: int):
    text = "\n".join(values)
    for size in range(ideal, minimum-1, -1):
        font = _font_for(family, size, bold)
        rows = _wrap_exact(text, font, width)
        if rows is not None and len(rows)*size*1.24 <= height:
            return size, rows
    raise ValueError(
        "Точный текст не помещается в подготовленную AI-зону. "
        "Данные не обрезаны. Уменьшите объём текста или измените композицию."
    )


def _color_near(colors: dict, role: str, art: Image.Image, pixel_box: tuple):
    value = colors["accent"] if role in ("model", "price") else (
        colors["muted"] if role in ("category", "proofs") else colors["ink"])
    x, y, w, h = pixel_box
    sample = art.convert("RGB").resize((48, 48))
    # Contrast verification at the actual text-surface center (scaled down).
    px = min(47, max(0, int((x + w*.5)*48/art.width)))
    py = min(47, max(0, int((y + h*.5)*48/art.height)))
    red, green, blue = sample.getpixel((px, py))
    def lum(color):
        channel = [(v/255/12.92 if v/255 <= .04045
                    else ((v/255+.055)/1.055)**2.4) for v in color]
        return channel[0]*.2126+channel[1]*.7152+channel[2]*.0722
    source = tuple(int(value[i:i+2],16) for i in (1,3,5))
    a, b = lum(source), lum((red, green, blue))
    if (max(a,b)+.05)/(min(a,b)+.05) < 4.5:
        black, white = (0,0,0), (255,255,255)
        candidate = black if (b+.05)/.05 >= (1.05)/(b+.05) else white
        return "#%02X%02X%02X" % candidate
    return value.upper()


def render_exact_svg(brief: dict, fmt: str, artwork: Image.Image,
                     slots: dict, styling: dict,
                     *, logo: bytes | None = None,
                     drawing: bytes | None = None) -> bytes:
    """A full AI bitmap PLUS only exact customer-supplied SVG copy layers."""
    if fmt not in FORMATS or artwork.size != FORMATS[fmt]:
        raise ValueError("Размер художественного AI-макета не соответствует формату.")
    copy = verified_copy(brief)
    scene = Scene(fmt, brief.get("accent"), brief.get("style"))
    scene.groups["background"].clear()
    scene.groups["decor"].clear()
    scene.bitmap("background", artwork, 0, 0, scene.w, scene.h,
                 "ai-authored-empty-template")
    fonts = styling["font_family"]
    for role in ROLES:
        values = copy.get(role) or []
        if not values:
            continue
        rect = slots[role]
        x = rect["x"] * scene.w / 1000
        y = rect["y"] * scene.h / 1000
        w = rect["w"] * scene.w / 1000
        h = rect["h"] * scene.h / 1000
        margin = max(4, min(w,h)*.025)
        x += margin; y += margin
        w -= 2*margin; h -= 2*margin
        bold = role in ("brand", "model", "slogan", "price", "claims")
        ideal = min(int(BASE_PX[role]*styling["scale_percent"]/100),
                    int(h*.72))
        minimum = 12 if role not in ("model", "price") else 19
        if ideal < minimum:
            raise ValueError(f"Недостаточно места для {role} в AI-макете.")
        try:
            size, rows = _size_and_lines(values,w,h,fonts,bold,ideal,minimum)
        except ValueError as exc:
            raise ValueError(f"{fmt}, {role}: {exc}") from exc
        color = _color_near(styling,role,artwork,(x,y,w,h))
        el = scene.el(GROUPS[role],"text","verified-"+role,{
            "x":x,"y":y+size,"fill":color,
            "font-family":fonts,
            "font-size":size,"font-weight":"700" if bold else "400",
            "xml:space":"preserve","data-verified-role":role,
            "data-exact-copy":"\n".join(values),
        })
        for index, line in enumerate(rows):
            span = ET.SubElement(el, f"{{{NS}}}tspan", {
                "x":str(round(x,2)),
                "dy":"0" if index==0 else str(round(size*1.24,2)),
            })
            span.text = line
    for role, raw, group in (
        ("logo",logo,"logo"),("drawing",drawing,"dimensions")
    ):
        if raw:
            box = slots[role]
            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                scene.bitmap(group, source, box["x"]*scene.w/1000,
                             box["y"]*scene.h/1000,
                             box["w"]*scene.w/1000,
                             box["h"]*scene.h/1000,
                             "exact-uploaded-"+role)
    return scene.export()
