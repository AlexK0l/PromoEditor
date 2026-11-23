"""Trusted exact-copy SVG renderer for AI-authored textless promo artwork.

AI supplies art, empty-slot coordinates and typographic styling ONLY. Every
letter/price/phone/technical fact comes from the normalized server-side brief.
Overflow fails visibly; no invented text, ellipses, cropping or bitmap AI
repainting of the final lettering. The final SVG remains CorelDRAW editable.
"""
from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageFont, ImageStat

from .ai_layout import _intersection
from .campaign_layout import _format_price
from .editable_export import NS, XLINK, Scene, _font
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
    "brand": 39, "model": 68, "category": 25, "slogan": 36,
    "specs": 29, "dimensions": 25, "benefits": 26,
    "claims": 29, "proofs": 24, "price": 56, "phones": 34, "roi": 27,
}
MIN_PX = {
    "brand": 27, "model": 43, "category": 22, "slogan": 28,
    "specs": 25, "dimensions": 23, "benefits": 24,
    "claims": 26, "proofs": 23, "price": 43, "phones": 29, "roi": 25,
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
                + _format_money(values["annual"])
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


def _format_money(value) -> str:
    """Preserve the precise calculated value, without ugly '.0' endings."""
    from decimal import Decimal, InvalidOperation
    try:
        decimal=Decimal(str(value))
        if not decimal.is_finite():
            return str(value)
        rendered=format(decimal,"f")
        integer,_,fraction=rendered.partition(".")
        grouped=f"{int(integer):,}".replace(","," ")
        fraction=fraction.rstrip("0")
        return grouped+("."+fraction if fraction else "")
    except (ValueError,TypeError,InvalidOperation):
        return str(value)


def poster_copy(brief: dict) -> dict[str, list[str]]:
    """Select factual AD COPY; preserve the full source in verified_copy().

    Keep a readable selection of real technical facts IN each hero advert.
    The separate technical sheet displays the full specs/dimensions and
    original drawing. Never invent, truncate or silently lose key data.
    """
    full=verified_copy(brief)
    chosen={role:[] for role in ROLES}
    for role in ("brand","model","category","slogan","price","roi"):
        chosen[role]=list(full[role][:1])
    chosen["phones"]=list(full["phones"][:2])
    # Keep a concise, legible technical strip. Prefer commercially relevant
    # figures already approved by the customer, then fill remaining slots.
    priority=("грузоподъёмность","объём кузова","собственный вес",
              "полная масса","вместимость","полезная нагрузка")
    specs=list(full["specs"])
    ranked=sorted(enumerate(specs),key=lambda item:(
        next((index for index,word in enumerate(priority)
              if item[1].casefold().startswith(word)) ,len(priority)),
        item[0]))
    # Technical facts are essential, not optional decoration. Long verified
    # lines are wrapped by the exact-copy renderer, never discarded solely
    # because a label exceeds a historical 44-character shortcut.
    chosen["specs"]=[value for _,value in ranked][:3]
    # Include two actual measurements from the customer-provided drawing data.
    # This must be visible in BOTH hero posters, not just in brief.json.
    dims=list(full["dimensions"])
    dim_priority=("длина","ширина","высота","масса","колея")
    dim_ranked=sorted(enumerate(dims),key=lambda item:(
        next((n for n,keyword in enumerate(dim_priority)
              if item[1].casefold().startswith(keyword)),len(dim_priority)),
        item[0],
    ))
    chosen["dimensions"]=[value for _,value in dim_ranked][:2]
    # The form has two independent approved sources of selling points.
    # Previously an empty "short claims" field silently excluded every
    # value from "other benefits", leaving a blank ad despite user input.
    claims=[value for value in full["claims"] if len(value)<=56]
    benefits=[value for value in full["benefits"]
              if len(value)<=56 and value not in claims]
    chosen["claims"]=(claims+benefits)[:2]
    return chosen


_SAFE_UNUSED_SLOT = {"x": 20, "y": 20, "w": 40, "h": 30}


def _valid_slot_box(box: object) -> bool:
    """Only a real, contained coordinate rectangle counts as usable."""
    if not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}:
        return False
    if any(type(box[key]) is not int for key in ("x", "y", "w", "h")):
        return False
    x, y, w, h = (box[key] for key in ("x", "y", "w", "h"))
    return (0 <= x <= 1000 and 0 <= y <= 1000
            and 30 <= w <= 1000 and 20 <= h <= 1000
            and x + w <= 1000 and y + h <= 1000)


def normalize_inactive_slots(geometry: dict, copy: dict, *,
                             has_logo=False, has_drawing=False) -> dict:
    """Ignore bad geometry ONLY for roles which will not be rendered.

    The Images/Responses JSON schema must still request all slot names, but
    an unused dimensions/benefits/etc. rectangle has no printable meaning.
    Preserve every valid AI rectangle and copy all objects: the paid raw
    response must remain unchanged for cache reuse and debugging. Active
    text and the product remain subject to strict validation/repair.
    """
    if not isinstance(geometry, dict) or set(geometry) != set(FORMATS):
        raise ValueError("AI не вернул зоны обоих форматов.")
    required = {"product"} | {role for role in ROLES if copy.get(role)}
    if has_logo:
        required.add("logo")
    if has_drawing:
        required.add("drawing")
    normalized = {}
    for fmt, slots in geometry.items():
        if not isinstance(slots, dict) or set(slots) - set(ALL_SLOTS):
            raise ValueError(f"AI вернул неизвестные зоны макета {fmt}.")
        if not required.issubset(slots):
            missing = ", ".join(sorted(required - set(slots)))
            raise ValueError(f"AI не подготовил обязательные зоны {fmt}: {missing}.")
        cleaned = {}
        for role in ALL_SLOTS:
            box = slots.get(role)
            if role not in required:
                # Invalid or missing *unused* coordinates must never block
                # a paid generation. Keep valid inactive boxes unchanged.
                cleaned[role] = (dict(box) if _valid_slot_box(box)
                                 else dict(_SAFE_UNUSED_SLOT))
                continue
            if (not isinstance(box, dict)
                    or set(box) != {"x", "y", "w", "h"}
                    or any(type(box[key]) is not int
                           for key in ("x", "y", "w", "h"))):
                raise ValueError(f"AI вернул неверную обязательную зону {role} ({fmt}).")
            if role == "product" and not _valid_slot_box(box):
                raise ValueError(f"AI вывел область техники за границы {fmt}.")
            cleaned[role] = dict(box)
        normalized[fmt] = cleaned
    return normalized


def validate_slots(geometry: dict, copy: dict, *,
                   has_logo=False, has_drawing=False) -> dict:
    """Reject hallucinated, overlapping, unreadable or off-canvas zones.

    Do NOT fall back to a rigid server template: those are the bad layouts
    which the customer explicitly rejected.
    """
    # Treat unused slot coordinates as optional metadata. In particular,
    # the model may return dimensions={x:980,y:980,w:100,h:100} even though
    # poster_copy intentionally contains no dimensions.
    geometry = normalize_inactive_slots(
        geometry, copy, has_logo=has_logo, has_drawing=has_drawing)
    result = {}
    for fmt, value in geometry.items():
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
                or not 94 <= options["scale_percent"] <= 112):
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


def _needs_readability_backdrop(art: Image.Image, box: tuple) -> bool:
    """Busy photographs cannot be used as direct type surfaces.

    Inspect local image texture, not a single background pixel. Real product
    photos, shiny aluminium, sand and diagonal artwork need a consistent
    translucent type panel, even when the center sample looks dark.
    """
    x,y,w,h=box
    left=max(0,int(x)); top=max(0,int(y))
    right=min(art.width,int(x+w)); bottom=min(art.height,int(y+h))
    if left>=right or top>=bottom:
        return True
    crop=art.crop((left,top,right,bottom))
    crop.thumbnail((70,45),Image.Resampling.BILINEAR)
    lum=ImageStat.Stat(crop.convert("L"))
    lo,hi=crop.convert("L").getextrema()
    return bool(lum.stddev[0]>22 or hi-lo>100)


def render_exact_svg(brief: dict, fmt: str, artwork: Image.Image,
                     slots: dict, styling: dict,
                     *, logo: bytes | None = None,
                     drawing: bytes | None = None,
                     copy_override: dict | None = None) -> bytes:
    """A full AI bitmap PLUS only exact customer-supplied SVG copy layers."""
    if fmt not in FORMATS or artwork.size != FORMATS[fmt]:
        raise ValueError("Размер художественного AI-макета не соответствует формату.")
    copy = copy_override if copy_override is not None else verified_copy(brief)
    scene = Scene(fmt, brief.get("accent"), brief.get("style"))
    scene.groups["background"].clear()
    scene.groups["decor"].clear()
    # The full photo illustration is already rasterized. Embedding it as a
    # print-quality JPEG instead of PNG+RGBA drastically reduces transient
    # CairoSVG allocations and SVG size on the 800 MiB production worker.
    # All genuine customer text remains vector SVG ABOVE this image.
    encoded = io.BytesIO()
    artwork.save(encoded, format="JPEG", quality=88, subsampling=0)
    scene.el("background", "image", "ai-authored-empty-template", {
        "x":0, "y":0, "width":scene.w, "height":scene.h,
        "preserveAspectRatio":"xMidYMid meet",
        f"{{{XLINK}}}href":"data:image/jpeg;base64,"
        +base64.b64encode(encoded.getvalue()).decode("ascii"),
    })
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
        minimum = MIN_PX[role]
        if ideal < minimum:
            raise ValueError(f"Недостаточно места для {role} в AI-макете.")
        try:
            size, rows = _size_and_lines(values,w,h,fonts,bold,ideal,minimum)
        except ValueError as exc:
            raise ValueError(f"{fmt}, {role}: {exc}") from exc
        protect = role in ("price","phones") or _needs_readability_backdrop(
            artwork,(x,y,w,h))
        if protect:
            scene.rect(GROUPS[role],x-7,y-5,w+14,h+10,
                       "#08111B",rad=10,opacity=0.85,
                       ident="readability-underlay-"+role)
            if role=="price":
                scene.rect(GROUPS[role],x-7,y-5,5,h+10,
                           "#E31B26",rad=2,ident="price-accent-rule")
        color = "#FFFFFF" if protect else _color_near(
            styling,role,artwork,(x,y,w,h))
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
            target_w = box["w"]*scene.w/1000
            target_h = box["h"]*scene.h/1000
            # Only the actual display-size preview belongs in the SVG.
            # A logo can be a 20 MiB, 100-megapixel source; converting it
            # to RGBA BEFORE resizing could OOM the 800 MiB worker.
            # Keep the untouched original bytes separately in the ZIP.
            embed_w = min(2200,max(64,int(target_w*3)))
            embed_h = min(2200,max(64,int(target_h*3)))
            with Image.open(io.BytesIO(raw)) as source:
                source.draft("RGB",(embed_w,embed_h))
                source.thumbnail(
                    (embed_w,embed_h),Image.Resampling.LANCZOS)
                source.load()
                scene.bitmap(group,source,
                             box["x"]*scene.w/1000,
                             box["y"]*scene.h/1000,
                             target_w,target_h,
                             "exact-uploaded-"+role)
    return scene.export()
