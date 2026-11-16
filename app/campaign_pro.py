"""Reference-inspired high-impact industrial advertising layout.

PRO is an opt-in SVG scene. It borrows visual hierarchy (dynamic red ribbons,
large product, icon-led fact cards and a strong CTA), never another product's
photographs, logos, dimensions, claims or contact details. All editorial
elements remain independent SVG objects for CorelDRAW.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from .campaign_layout import (
    _check, _format_price, _lines, _photo, _rule, _spec_symbol,
)
from .editable_export import Scene
from .render import compute_roi

RED_DARK = "#AE0013"
INK = "#191D29"
PAPER = "#F7F8FA"
SVG_NS = "http://www.w3.org/2000/svg"


def _copy(scene, group, value, x, y, w, h, size=24, minimum=13,
          color=INK, bold=True, ident="copy", lines=2, italic=False):
    node = scene.text(group, str(value), x, y, max(12, w), max(15, h),
                      size, minimum, color, bold, ident, lines)
    if node is not None and italic:
        node.set("font-style", "italic")
    return node


def _tint(scene, accent):
    defs = scene.root.find(f"{{{SVG_NS}}}defs")
    gradient = ET.SubElement(defs, f"{{{SVG_NS}}}linearGradient", {
        "id": "pro-red-gradient", "x1": "0", "y1": "0", "x2": "1", "y2": "1"
    })
    ET.SubElement(gradient, f"{{{SVG_NS}}}stop",
                  {"offset": "0%", "stop-color": RED_DARK})
    ET.SubElement(gradient, f"{{{SVG_NS}}}stop",
                  {"offset": "65%", "stop-color": accent})
    ET.SubElement(gradient, f"{{{SVG_NS}}}stop",
                  {"offset": "100%", "stop-color": "#D10A1B"})


def _header(scene, brief, logo, accent, portrait):
    w = scene.w
    h = 257 if portrait else 181
    scene.rect("decor", 0, 0, w, h, "url(#pro-red-gradient)",
               ident="pro-header")
    for idx, offset in enumerate((0, 56, 112)):
        scene.polygon("decor", [
            (w-240+offset, 0), (w-198+offset, 0),
            (w-340+offset, h), (w-382+offset, h)
        ], "#FFFFFF", ident=f"pro-head-stripe-{idx}",
            opacity=".92" if idx == 2 else ".23")
    scene.polygon("decor", [(0, h-12), (w, h-12), (w, h), (0, h)],
                  "#F9FAFD", ident="pro-header-edge")
    brand_w = 240 if portrait else 257
    if logo is not None:
        # Keep user artwork independent; a white base gives dark logos contrast.
        scene.polygon("logo", [(24, 22), (brand_w-9, 22),
                               (brand_w-40, 133), (24, 133)],
                      "#FFFFFF", ident="pro-logo-plate")
        _photo(scene, logo, 32, 30, brand_w-84, 94, "original-logo",
               layer="logo", trim=True)
    elif str(brief.get("brand") or "").strip():
        _copy(scene, "logo", brief["brand"].upper(), 29, 29,
              brand_w-50, 104, 40, 18, "#FFFFFF", True,
              "pro-brand", 2)
    sx = 269 if portrait else 282
    _rule(scene, "heading", sx-13, 26, sx-49, 145 if portrait else 128,
          "#FFFFFF", 5, "pro-brand-divider")
    cat = str(brief.get("category") or "").strip().upper()
    model = str(brief.get("model") or "").strip()
    if cat:
        _copy(scene, "heading", cat, sx+4, 17, w-sx-65, 49,
              39 if portrait else 42, 20, "#FFFFFF", True,
              "pro-category", 1, italic=True)
    _copy(scene, "heading", model, sx, 61, w-sx-68,
          122 if portrait else 88, 89 if portrait else 92,
          34, "#FFFFFF", True, "pro-model", 1, italic=True)
    slogan = str(brief.get("slogan") or "").strip()
    if slogan:
        sy = 200 if portrait else 143
        left = 230 if portrait else 246
        scene.polygon("heading", [
            (left+11, sy), (w-27, sy), (w-55, sy+43),
            (left-16, sy+43)
        ], "#FFFFFF", ident="pro-slogan-ribbon")
        _copy(scene, "heading", slogan, left+26, sy+3,
              w-left-109, 37, 29 if portrait else 27,
              15, accent, True, "pro-slogan", 1, italic=True)


def _hero(scene, hero, detail, backdrop, ai_product, brief,
          accent, x, y, w, h):
    scene.rect("photos", x, y, w, h, "#E7EBF1", ident="pro-hero-stage")
    scene.polygon("photos", [(x, y+h*.58), (x+w, y+h*.38),
                              (x+w, y+h), (x, y+h)],
                  "#D2D8DF", ident="pro-hero-ground")
    scene.polygon("photos", [(x+w*.82, y), (x+w, y),
                              (x+w*.67, y+h)], "#FFFFFF",
                  opacity=".45", ident="pro-hero-light")
    if backdrop is not None and not ai_product:
        _photo(scene, backdrop, x, y, w, h, "pro-ai-background", cover=True)
        scene.rect("photos", x, y, w, h, "#FFFFFF", opacity=".1",
                   ident="pro-photo-atmosphere")
    source = backdrop if ai_product else hero
    if source is not None:
        # The original product is never regenerated or rewritten by the model.
        _photo(scene, source, x+9, y+8, w-18, h-16,
               "ai-product-bitmap" if ai_product else "original-product-photo",
               trim=not ai_product)
    if detail is not None:
        dw = min(260, w*.34)
        dh = min(135, h*.36)
        ix, iy = x+18, y+h-dh-21
        scene.rect("photos", ix-6, iy-6, dw+12, dh+12,
                   "#FFFFFF", rad=11, ident="pro-detail-frame")
        _photo(scene, detail, ix, iy, dw, dh, "detail-photo", trim=True)
        scene.rect("claims", ix-6, iy+dh+4, dw+12, 5,
                   accent, ident="pro-detail-underline")
    if ai_product:
        ly = y+h-41
        scene.rect("claims", x+15, ly, 240, 30, "#272B33",
                   rad=4, ident="pro-ai-tag-bg")
        _copy(scene, "claims", "AI-ВИЗУАЛИЗАЦИЯ", x+26,
              ly+2, 225, 24, 16, 12, "#FFFFFF", True,
              "pro-ai-tag", 1)
    # Short verified claims, only if not already used as a photo inset.
    if detail is None:
        claims = [str(v).strip() for v in (brief.get("hero_claims") or [])
                  if str(v).strip()][:2]
        for i, claim in enumerate(claims):
            py = y+h-57-i*49
            if py < y+17:
                break
            cw = min(w*.57, 400)
            scene.polygon("claims", [(x+15, py), (x+cw+15, py),
                                      (x+cw-4, py+42), (x+15, py+42)],
                          "#FFFFFF", opacity=".93",
                          ident=f"pro-claim-plate-{i}")
            scene.rect("claims", x+15, py, 6, 42, accent,
                       ident=f"pro-claim-bar-{i}")
            _copy(scene, "claims", claim, x+29, py+5,
                  cw-49, 32, 21, 12, INK, True, f"pro-claim-{i}", 1)


def _specs(scene, facts, x, y, w, h, accent, portrait):
    if not facts:
        return
    columns = 2 if portrait else 1
    rows = math.ceil(len(facts)/columns)
    gap = 7 if portrait else 5
    col_w = (w-(columns-1)*gap)/columns
    row_h = (h-(rows-1)*gap)/rows
    for i, (name, value) in enumerate(facts):
        bx = x+(i%columns)*(col_w+gap)
        by = y+(i//columns)*(row_h+gap)
        scene.polygon("specs", [
            (bx+14, by), (bx+col_w-4, by),
            (bx+col_w, by+row_h*.5),
            (bx+col_w-4, by+row_h), (bx, by+row_h),
            (bx+12, by+4)
        ], "#FFFFFF", ident=f"pro-spec-card-{i}")
        scene.el("specs", "polygon", f"pro-spec-outline-{i}", {
            "points": " ".join(f"{a:.1f},{b:.1f}" for a,b in [
                (bx+14, by), (bx+col_w-4, by),
                (bx+col_w, by+row_h*.5), (bx+col_w-4, by+row_h),
                (bx, by+row_h), (bx+12, by+4)
            ]),
            "fill": "none", "stroke": accent, "stroke-width": 1.6
        })
        scene.polygon("specs", [
            (bx, by+row_h), (bx+72, by+row_h),
            (bx+94, by), (bx+20, by)
        ], accent, ident=f"pro-spec-icon-plate-{i}")
        # Existing editor-safe icons are genuine SVG paths rather than emoji.
        icon_x = bx+18
        icon_y = by+(row_h-60)/2
        start = len(scene.groups["specs"])
        _spec_symbol(scene, icon_x, icon_y, i, accent)
        scale = min(.73, max(.43, (row_h-10)/60))
        for part in list(scene.groups["specs"])[start:]:
            part.set("transform", f"translate({icon_x*(1-scale):.2f} "
                                  f"{icon_y*(1-scale):.2f}) scale({scale:.3f})")
        # Column widths adapt independently; values stay visible in narrow 9:16.
        sep_x = bx+col_w*.66
        _rule(scene, "specs", sep_x-9, by+8, sep_x-9,
              by+row_h-8, "#EBEDEF", 1.5, "pro-spec-divider")
        _copy(scene, "specs", name, bx+95, by+5,
              sep_x-bx-107, row_h-8, 22 if not portrait else 19,
              12, INK, True, f"pro-spec-name-{i}", 2, italic=True)
        _copy(scene, "specs", value, sep_x+1, by+5,
              bx+col_w-sep_x-7, row_h-9,
              28 if not portrait else 22, 12,
              accent, True, f"pro-spec-value-{i}", 2)


def _ribbon(scene, layer, text, x, y, width, height, accent, ident):
    scene.polygon(layer, [(x, y), (x+width, y),
                          (x+width-25, y+height), (x-8, y+height)],
                  accent, ident=ident)
    _copy(scene, layer, text, x+13, y+3, width-45,
          height-6, 25, 15, "#FFFFFF", True,
          ident+"-text", 1, italic=True)


def _dimensions(scene, facts, drawing, x, y, w, h, accent, portrait):
    if not facts and drawing is None:
        return
    scene.rect("dimensions", x, y, w, h, "#FFFFFF",
               rad=9, ident="pro-dimensions-panel")
    _ribbon(scene, "dimensions",
            "ГАБАРИТЫ И ЧЕРТЁЖ" if drawing is not None else "ГАБАРИТНЫЕ РАЗМЕРЫ",
            x+7, y+4, min(510, w*.59),
            37 if portrait else 34, accent, "pro-dimensions-title")
    top = y+(46 if portrait else 42)
    body_h = h-(53 if portrait else 47)
    if drawing is not None:
        dw = w*.56 if portrait else w*.62
        _photo(scene, drawing, x+17, top+2, dw-24,
               body_h-7, "original-drawing", layer="dimensions")
        left = x+dw+5
        available = w-dw-19
        columns = 1
    else:
        left = x+18
        available = w-36
        columns = 2 if portrait and len(facts)>2 else min(4, len(facts))
    if not facts:
        return
    rows = math.ceil(len(facts)/columns)
    gap = 5
    cw = (available-(columns-1)*gap)/columns
    ch = (body_h-(rows-1)*gap)/rows
    for i, (label, value) in enumerate(facts):
        bx = left+(i%columns)*(cw+gap)
        by = top+(i//columns)*(ch+gap)
        if i%2 == 0:
            scene.rect("dimensions", bx, by, cw, ch, "#F2F4F7",
                       rad=4, ident=f"pro-dimension-cell-{i}")
        _copy(scene, "dimensions", label, bx+9, by+4,
              cw*.45, ch-6, 18, 12, "#3C4550", False,
              f"pro-dimension-name-{i}", 2)
        _copy(scene, "dimensions", value, bx+cw*.48, by+4,
              cw*.49-6, ch-7, 24, 13, accent, True,
              f"pro-dimension-value-{i}", 2)


def _benefit_icon(scene, x, y, index, accent):
    # Neutral, illustrative pictograms (no invented safety certification).
    shapes = (
        f"M {x-20} {y-8} L {x} {y-21} L {x+20} {y-8} L {x} {y+4} Z "
        f"M {x-20} {y+2} L {x} {y+15} L {x+20} {y+2}",
        f"M {x} {y-21} L {x+20} {y-12} L {x+15} {y+12} "
        f"L {x} {y+23} L {x-15} {y+12} L {x-20} {y-12} Z",
        f"M {x-21} {y+17} L {x-6} {y+2} L {x+5} {y+9} "
        f"L {x+21} {y-16}",
        f"M {x-19} {y+18} L {x-19} {y+3} L {x-6} {y+3} "
        f"L {x-6} {y-10} L {x+6} {y-10} L {x+6} {y-19} "
        f"L {x+19} {y-19} L {x+19} {y+18} Z",
        f"M {x-19} {y+18} L {x-19} {y-8} L {x-7} {y-8} "
        f"L {x-7} {y+18} M {x-2} {y+18} L {x-2} {y-16} "
        f"L {x+10} {y-16} L {x+10} {y+18} M {x+15} {y+18} "
        f"L {x+15} {y-22}",
        f"M {x} {y-22} A 22 22 0 1 1 {x-.01} {y-22} "
        f"M {x} {y-16} L {x} {y} L {x+12} {y+8}"
    )
    scene.el("benefits", "path", f"pro-benefit-icon-{index}", {
        "d": shapes[index%len(shapes)], "stroke": accent,
        "stroke-width": 3.5, "stroke-linecap": "round",
        "stroke-linejoin": "round", "fill": "none"
    })


def _benefits(scene, benefits, x, y, w, h, accent, portrait):
    if not benefits:
        return
    scene.rect("benefits", x, y, w, h, "#FFFFFF",
               rad=10, ident="pro-benefits-panel")
    caption_h = 37 if not portrait else 43
    _ribbon(scene, "benefits", "ПРЕИМУЩЕСТВА", x+8, y+4,
            min(570, w*.55), caption_h, accent, "pro-benefits-title")
    columns = min(3, len(benefits)) if portrait else len(benefits)
    rows = math.ceil(len(benefits)/columns)
    top = y+caption_h+10
    row_h = (h-caption_h-17)/rows
    col_w = (w-20)/columns
    for i, claim in enumerate(benefits):
        bx = x+10+(i%columns)*col_w
        by = top+(i//columns)*row_h
        if i%columns:
            _rule(scene, "benefits", bx, by+7, bx, by+row_h-8,
                  accent, 1.5, "pro-benefit-separator")
        icon_y = by+min(29, row_h*.36)
        _benefit_icon(scene, bx+col_w*.5, icon_y, i, accent)
        _copy(scene, "benefits", claim, bx+7, by+min(56, row_h*.64),
              col_w-14, max(28, row_h*.35), 20 if not portrait else 20,
              11, INK, True, f"pro-benefit-{i}", 2)


def _proof(scene, claims, x, y, w, h, accent, portrait):
    if not claims:
        return
    scene.rect("benefits", x, y, w, h, "#FFF9F9",
               ident="pro-proof-panel")
    if portrait:
        _ribbon(scene, "benefits", "ПОДТВЕРЖДЁННЫЕ ФАКТЫ",
                x+8, y+2, min(540, w*.75), 37,
                accent, "pro-proof-title")
        start_y = y+45
        columns = 2
    else:
        _ribbon(scene, "benefits", "ПОДТВЕРЖДЁННЫЕ ФАКТЫ",
                x+8, y+5, 305, h-10,
                accent, "pro-proof-title")
        start_y = y+5
        columns = min(4, len(claims))
    rows = math.ceil(len(claims)/columns)
    start_x = x+12 if portrait else x+329
    width = (w-24) if portrait else w-339
    cw = width/columns
    ch = (h-(47 if portrait else 10))/rows
    for i, claim in enumerate(claims):
        bx = start_x+(i%columns)*cw
        by = start_y+(i//columns)*ch
        scene.el("benefits", "circle", f"pro-proof-circle-{i}", {
            "cx":bx+15, "cy":by+ch*.5, "r":10,
            "fill":"none", "stroke":accent, "stroke-width":2
        })
        _check(scene, "benefits", bx+9, by+ch*.5-7,
               12, accent, f"pro-proof-check-{i}")
        _copy(scene, "benefits", claim, bx+32, by+3,
              cw-36, ch-5, 18, 11,
              INK, True, f"pro-proof-fact-{i}", 2)


def _roi(scene, brief, x, y, w, h, accent):
    if not brief.get("show_roi"):
        return
    data = compute_roi(brief)
    if data is None:
        return
    metrics = [
        ("ЗА РЕЙС", data["per_trip"]),
        ("РЕЙСОВ В ГОД", data["trips"]),
        ("ЗА ГОД", data["annual"]),
        ("БАЛАНС", data["net"]),
    ]
    scene.rect("roi", x, y, w, h, "#FFF0F1",
               ident="pro-roi-panel")
    cw = w/4
    for i, (label, value) in enumerate(metrics):
        bx=x+i*cw
        if i:
            _rule(scene, "roi", bx, y+6, bx, y+h-6,
                  "#EAAAB1", 1.6, "pro-roi-divider")
        _copy(scene, "roi", label, bx+10, y+4,
              cw-18, h*.32, 17, 12, "#532E32",
              True, f"pro-roi-label-{i}", 1)
        formatted=f"{value:,.0f}".replace(",", " ")
        _copy(scene, "roi", formatted, bx+10, y+h*.34,
              cw-18, h*.59, 29, 15, accent,
              True, f"pro-roi-value-{i}", 1)


def _footer(scene, brief, accent, portrait):
    w, h = scene.w, scene.h
    y = 1742 if portrait else 957
    scene.rect("cta_bg", 0, y, w, h-y,
               "url(#pro-red-gradient)", ident="pro-cta")
    for k in range(3):
        xx=w-255+k*65
        scene.polygon("cta_bg", [(xx, y), (xx+43, y),
                                  (xx-110, h), (xx-153, h)],
                      "#FFFFFF", opacity=".11",
                      ident=f"pro-cta-stripe-{k}")
    price = _format_price(brief.get("price"))
    currency = str(brief.get("currency") or "").strip()
    vat = bool(brief.get("vat", True))
    price_copy = (price+" "+currency+(" с НДС" if vat else "")
                  if price else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    contacts = [str(v).strip() for v in (brief.get("phones") or [])[:2]
                if str(v).strip()]
    if portrait:
        _copy(scene, "price", price_copy, 40, y+18,
              w-72, 78, 68 if price else 41,
              24, "#FFFFFF", True, "pro-price", 2, italic=True)
        if contacts:
            _rule(scene, "contacts", 37, y+99, w-38, y+99,
                  "#FFFFFF", 2, "pro-contact-topline")
            _copy(scene, "contacts", "СВЯЖИТЕСЬ С НАМИ", 39,
                  y+104, w*.45, 42, 27, 17,
                  "#FFFFFF", True, "pro-contact-label", 1)
            for i, phone in enumerate(contacts):
                _copy(scene, "contacts", phone, w*.51,
                      y+103+i*37, w*.45, 36, 26,
                      15, "#FFFFFF", True, f"pro-phone-{i}", 1)
    else:
        side=w*.57
        scene.polygon("cta_bg", [(0, y), (side-46, y),
                                  (side-113, h), (0, h)],
                      accent, ident="pro-price-plate")
        _copy(scene, "price", price_copy, 42, y+22,
              side-118, h-y-30, 61 if price else 38,
              22, "#FFFFFF", True, "pro-price", 2, italic=True)
        if contacts:
            _rule(scene, "contacts", side-13, y+20,
                  side-13, h-17, "#FFFFFF", 2.5,
                  "pro-contact-divider")
            _copy(scene, "contacts", "СВЯЖИТЕСЬ С НАМИ", side+14,
                  y+13, w-side-40, 31, 25, 15,
                  "#FFFFFF", True, "pro-contact-label", 1,
                  italic=True)
            for i, phone in enumerate(contacts):
                _copy(scene, "contacts", phone, side+14,
                      y+48+i*28, w-side-43, 29, 27, 15,
                      "#FFFFFF", True, f"pro-phone-{i}", 1)


def create_pro_campaign_svg(brief, key, hero=None, detail=None,
                            logo=None, drawing=None, backdrop=None,
                            ai_product=False):
    """Render both exact sizes with source-only claims and Corel-editable layers."""
    if key not in ("4x3", "9x16"):
        raise ValueError("Неизвестное соотношение сторон.")
    portrait=key=="9x16"
    scene=Scene(key, brief.get("accent"), "industrial")
    accent=scene.accent
    _tint(scene, accent)
    scene.rect("decor", 0, 0, scene.w, scene.h, PAPER,
               ident="pro-paper")
    facts=_lines(brief, "specs", 8)
    dims=_lines(brief, "dimensions", 4)
    benefits=[str(v).strip()[:150] for v in (brief.get("benefits") or [])
              if str(v).strip()][:6]
    # Only explicit approved text; a reference photo is never a fact source.
    proof=[str(v).strip()[:180] for v in (brief.get("proof_points") or [])
           if str(v).strip()][:4]
    has_roi=bool(brief.get("show_roi") and compute_roi(brief))
    _header(scene, brief, logo, accent, portrait)
    bottom=1733 if portrait else 949
    top=271 if portrait else 188
    gap=10 if portrait else 9
    segments=[]
    if portrait and facts:
        segments.append(("specs", 364))
    if dims or drawing is not None:
        segments.append(("dimensions", 183 if portrait else 132))
    if benefits:
        segments.append(("benefits", 211 if portrait else 142))
    if proof:
        segments.append(("proof", 117 if portrait else 77))
    if has_roi:
        segments.append(("roi", 110 if portrait else 75))
    reserved=sum(h for _,h in segments)+gap*len(segments)
    hero_h=bottom-top-reserved
    # No unsupported sections are rendered; the product receives their space.
    if portrait:
        _hero(scene, hero, detail, backdrop, ai_product, brief,
              accent, 20, top, scene.w-40, hero_h)
    else:
        photo_width=892 if facts else scene.w-40
        _hero(scene, hero, detail, backdrop, ai_product, brief,
              accent, 20, top, photo_width, hero_h)
        if facts:
            _specs(scene, facts, 923, top, scene.w-944,
                   hero_h, accent, False)
    cursor=top+hero_h+gap
    for kind, height in segments:
        x=20
        w=scene.w-40
        if kind=="specs":
            _specs(scene, facts, x, cursor, w, height, accent, True)
        elif kind=="dimensions":
            _dimensions(scene, dims, drawing, x, cursor, w, height,
                        accent, portrait)
        elif kind=="benefits":
            _benefits(scene, benefits, x, cursor, w, height, accent, portrait)
        elif kind=="proof":
            _proof(scene, proof, x, cursor, w, height, accent, portrait)
        else:
            _roi(scene, brief, x, cursor, w, height, accent)
        cursor+=height+gap
    _footer(scene, brief, accent, portrait)
    return scene.export()
