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
    """Sharper brand hierarchy; artwork remains a replaceable original bitmap."""
    w = scene.w
    h = 266 if portrait else 187
    scene.rect("decor", 0, 0, w, h, "url(#pro-red-gradient)",
               ident="pro-header")
    # Three strong diagonal motifs rather than a flat stripe.
    for i, off in enumerate((0, 64, 128)):
        scene.polygon("decor", [
            (w-294+off, 0), (w-244+off, 0),
            (w-391+off, h), (w-441+off, h)
        ], "#FFFFFF", ident=f"pro-head-stripe-{i}",
            opacity=".19" if i < 2 else ".98")
    scene.polygon("decor", [(0, h-6), (w, h-6), (w, h), (0, h)],
                  PAPER, ident="pro-header-edge")

    plate_x, plate_y = 23, 20
    plate_w = 245 if portrait else 276
    plate_h = 128 if portrait else 132
    if logo is not None:
        scene.polygon("logo", [
            (plate_x, plate_y), (plate_x+plate_w, plate_y),
            (plate_x+plate_w-34, plate_y+plate_h),
            (plate_x, plate_y+plate_h)
        ], "#FFFFFF", ident="pro-logo-plate")
        _photo(scene, logo, plate_x+12, plate_y+9,
               plate_w-53, plate_h-21, "original-logo",
               layer="logo", trim=True)
    elif str(brief.get("brand") or "").strip():
        scene.polygon("logo", [
            (plate_x, plate_y), (plate_x+plate_w, plate_y),
            (plate_x+plate_w-34, plate_y+plate_h),
            (plate_x, plate_y+plate_h)
        ], "#A90016", ident="pro-brand-plate")
        _copy(scene, "logo", str(brief["brand"]).upper(),
              plate_x+9, plate_y+22, plate_w-64, 93,
              37, 18, "#FFFFFF", True, "pro-brand", 2)

    sx = 270 if portrait else 317
    _rule(scene, "heading", sx-14, 22,
          sx-50, 143 if portrait else 135,
          "#FFFFFF", 6, "pro-brand-divider")
    cat = str(brief.get("category") or "").strip().upper()
    model = str(brief.get("model") or "").strip()
    if cat:
        _copy(scene, "heading", cat, sx+3, 13, w-sx-68, 46,
              38, 21, "#FFFFFF", True, "pro-category", 1, italic=True)
    _copy(scene, "heading", model, sx-2, 56, w-sx-61, 94 if portrait else 87,
          93 if portrait else 91, 30,
          "#FFFFFF", True, "pro-model", 1, italic=True)

    slogan = str(brief.get("slogan") or "").strip()
    if slogan:
        sy = 209 if portrait else 140
        left = 240 if portrait else 262
        scene.polygon("heading", [
            (left+8, sy), (w-25, sy), (w-58, sy+48),
            (left-17, sy+48)
        ], "#FFFFFF", ident="pro-slogan-ribbon")
        _copy(scene, "heading", slogan, left+23, sy+5,
              w-left-99, 39, 31 if portrait else 30,
              16, accent, True, "pro-slogan", 1, italic=True)


def _hero(scene, hero, detail, backdrop, ai_product, brief,
          accent, x, y, w, h):
    """Make the original equipment dominant without inventing surroundings."""
    scene.rect("photos", x, y, w, h, "#E7ECF1", ident="pro-hero-stage")
    # Graphic industrial depth is deliberately schematic, NOT a fake quarry.
    scene.polygon("photos", [
        (x, y+h*.63), (x+w, y+h*.43),
        (x+w, y+h), (x, y+h)
    ], "#D0D9E1", ident="pro-hero-ground")
    scene.polygon("photos", [
        (x+w*.80, y), (x+w, y),
        (x+w*.58, y+h), (x+w*.38, y+h)
    ], "#FFFFFF", opacity=".54", ident="pro-hero-light")
    for i in range(4):
        line_y = y+h*(.66+.075*i)
        _rule(scene, "photos", x+20, line_y,
              x+w-20, line_y-h*.16,
              "#FFFFFF", 2, f"pro-hero-depth-{i}")
    if backdrop is not None and not ai_product:
        _photo(scene, backdrop, x+2, y+2, w-4, h-4,
               "pro-ai-background", cover=True)
        scene.rect("photos", x+2, y+2, w-4, h-4,
                   "#FFFFFF", opacity=".07",
                   ident="pro-photo-atmosphere")

    source = backdrop if ai_product else hero
    if source is not None:
        _photo(scene, source, x+4, y+3, w-8, h-23,
               "ai-product-bitmap" if ai_product else "original-product-photo",
               trim=not ai_product)
    scene.rect("photos", x+7, y+h-10, w-14, 6,
               accent, ident="pro-hero-bottom-rule")
    scene.polygon("photos", [
        (x+w-87, y+h-33), (x+w-21, y+h-33),
        (x+w-39, y+h-11), (x+w-105, y+h-11)
    ], accent, ident="pro-hero-red-notch", opacity=".9")

    if detail is not None:
        dw = min(295, w*.35)
        dh = min(159, h*.36)
        ix, iy = x+20, y+h-dh-24
        scene.rect("photos", ix-8, iy-8, dw+16, dh+16,
                   "#FFFFFF", rad=10, ident="pro-detail-frame")
        _photo(scene, detail, ix, iy, dw, dh, "detail-photo", trim=True)
        scene.rect("claims", ix-8, iy+dh+2, dw+16, 6,
                   accent, ident="pro-detail-underline")

    if ai_product:
        ly = y+h-51
        scene.rect("claims", x+w-249, ly, 233, 31, "#272B33",
                   rad=3, ident="pro-ai-tag-bg")
        _copy(scene, "claims", "AI-ВИЗУАЛИЗАЦИЯ", x+w-240,
              ly+3, 219, 25, 16, 12, "#FFFFFF", True,
              "pro-ai-tag", 1)
    if detail is None:
        # Never borrow claims or copy from the visual reference.
        claims = [str(v).strip() for v in (brief.get("hero_claims") or [])
                  if str(v).strip()][:2]
        for i, claim in enumerate(claims):
            py = y+h-66-i*52
            if py < y+18:
                break
            cw = min(w*.55, 420)
            scene.polygon("claims", [
                (x+17, py), (x+cw+15, py),
                (x+cw-14, py+43), (x+17, py+43)
            ], "#FFFFFF", opacity=".95", ident=f"pro-claim-plate-{i}")
            scene.rect("claims", x+17, py, 7, 43, accent,
                       ident=f"pro-claim-bar-{i}")
            _copy(scene, "claims", claim, x+34, py+5,
                  cw-61, 32, 22, 13, INK, True,
                  f"pro-claim-{i}", 1)


def _specs(scene, facts, x, y, w, h, accent, portrait):
    """Prioritise key numeric facts; keep every user-provided row visible."""
    if not facts:
        return
    columns = 2 if portrait and len(facts) > 1 else 1
    rows = math.ceil(len(facts)/columns)
    gap = 7 if portrait else 5
    col_w = (w-(columns-1)*gap)/columns
    weights = [1.22 if row == 0 else 1.0 for row in range(rows)]
    unit = (h-gap*(rows-1))/sum(weights)
    heights = [unit*t for t in weights]
    starts = []
    position = y
    for rh in heights:
        starts.append(position)
        position += rh+gap

    for i, (name, value) in enumerate(facts):
        col, row = (i%columns, i//columns)
        bx = x+col*(col_w+gap)
        by, rh = starts[row], heights[row]
        scene.polygon("specs", [
            (bx+16, by), (bx+col_w-7, by),
            (bx+col_w, by+rh*.5),
            (bx+col_w-7, by+rh), (bx, by+rh),
            (bx+13, by+4)
        ], "#FFFFFF", ident=f"pro-spec-card-{i}")
        scene.el("specs", "polygon", f"pro-spec-outline-{i}", {
            "points": " ".join(f"{px:.1f},{py:.1f}" for px,py in [
                (bx+16,by),(bx+col_w-7,by),(bx+col_w,by+rh*.5),
                (bx+col_w-7,by+rh),(bx,by+rh),(bx+13,by+4)
            ]),
            "fill":"none", "stroke":accent, "stroke-width":1.8
        })
        # Diagonal left plate is a deliberate visual echo of the reference.
        scene.polygon("specs", [
            (bx, by+rh-1), (bx+65, by+rh-1),
            (bx+91, by+1), (bx+21, by+1)
        ], accent, ident=f"pro-spec-icon-plate-{i}")

        icon_x = bx+15
        icon_y = by+(rh-60)/2
        first = len(scene.groups["specs"])
        _spec_symbol(scene, icon_x, icon_y, i, accent)
        scale = min(.88, max(.38, (rh-11)/60))
        for part in list(scene.groups["specs"])[first:]:
            part.set("transform",
                     f"translate({icon_x*(1-scale):.2f} "
                     f"{icon_y*(1-scale):.2f}) scale({scale:.3f})")

        # Values have their own visual zone and must never sit on labels.
        value_length = len(str(value).strip())
        ratio = .59 if value_length >= 16 else (.63 if value_length >= 12 else .68)
        sep = bx+col_w*ratio
        _rule(scene, "specs", sep-9, by+9, sep-9,
              by+rh-9, "#E1E5EA", 2, "pro-spec-divider")
        title_size = 23 if rh>=60 else 20
        val_size = 33 if row == 0 and rh>=57 else 28
        _copy(scene, "specs", name, bx+92, by+6,
              max(20, sep-bx-102), rh-11,
              title_size, 12, INK, True,
              f"pro-spec-name-{i}", 2)
        _copy(scene, "specs", value, sep+2, by+5,
              max(20, bx+col_w-sep-12), rh-10,
              val_size, 13, accent, True,
              f"pro-spec-value-{i}", 2)

def _ribbon(scene, layer, text, x, y, width, height, accent, ident):
    scene.polygon(layer, [(x, y), (x+width, y),
                          (x+width-25, y+height), (x-8, y+height)],
                  accent, ident=ident)
    _copy(scene, layer, text, x+13, y+3, width-45,
          height-6, 25, 15, "#FFFFFF", True,
          ident+"-text", 1, italic=True)



def _dimensions(scene, facts, drawing, x, y, w, h, accent, portrait):
    """A technical display, not a narrow spreadsheet; never invent a diagram."""
    if not facts and drawing is None:
        return
    scene.rect("dimensions", x, y, w, h, "#FFFFFF",
               rad=8, ident="pro-dimensions-panel")
    title = "ГАБАРИТЫ И ЧЕРТЁЖ" if drawing is not None else "ГАБАРИТНЫЕ РАЗМЕРЫ"
    ribbon_h = 42 if portrait else 39
    _ribbon(scene, "dimensions", title, x+8, y+4,
            min(w*.53, 535), ribbon_h, accent, "pro-dimensions-title")
    top = y+ribbon_h+12
    body_h = h-ribbon_h-20
    if drawing is not None:
        # Imported original drawing stays an independent raster layer.
        dw = w*.58 if portrait else w*.62
        scene.rect("dimensions", x+14, top+2, dw-18,
                   body_h-5, "#F3F6F8", rad=5,
                   ident="pro-technical-drawing-stage")
        _photo(scene, drawing, x+19, top+6, dw-30, body_h-15,
               "original-drawing", layer="dimensions")
        left = x+dw+8
        available = w-dw-24
        columns = 1
    else:
        left = x+16
        available = w-32
        if portrait:
            columns = 2 if len(facts)>=4 else max(1,len(facts))
        else:
            columns = min(4,len(facts))
    if not facts:
        return

    rows = math.ceil(len(facts)/columns)
    gap = 7
    cw = (available-gap*(columns-1))/columns
    ch = (body_h-gap*(rows-1))/rows
    for i,(label,value) in enumerate(facts):
        bx=left+(i%columns)*(cw+gap)
        by=top+(i//columns)*(ch+gap)
        scene.rect("dimensions", bx, by, cw, ch,
                   "#F1F4F7" if i%2==0 else "#F9FAFC",
                   rad=5, ident=f"pro-dimension-cell-{i}")
        scene.rect("dimensions", bx, by, cw, 4,
                   accent, ident=f"pro-dimension-stripe-{i}")
        if drawing is not None or ch < 73:
            _copy(scene, "dimensions", label, bx+10, by+7,
                  cw*.43, ch-13, 19, 12, "#303846", True,
                  f"pro-dimension-name-{i}", 2)
            _copy(scene, "dimensions", value,
                  bx+cw*.48, by+6, cw*.49-10, ch-12,
                  27, 13, accent, True,
                  f"pro-dimension-value-{i}", 2)
        else:
            _copy(scene, "dimensions", label, bx+15, by+10,
                  cw-28, 30, 22, 14, "#333C49",
                  True, f"pro-dimension-name-{i}", 1)
            _copy(scene, "dimensions", value, bx+15,
                  by+ch*.38, cw-28, ch*.45,
                  35 if not portrait else 37,
                  18, accent, True,
                  f"pro-dimension-value-{i}", 1)
            # A decorative vector measuring rule, not a synthesized drawing.
            ly=by+ch-12
            _rule(scene, "dimensions", bx+17, ly,
                  bx+cw-17, ly, accent, 1.8,
                  f"pro-dimension-measure-{i}")
            _rule(scene, "dimensions", bx+17, ly-6,
                  bx+17, ly+4, accent, 1.8,
                  f"pro-dimension-measure-left-{i}")
            _rule(scene, "dimensions", bx+cw-17, ly-6,
                  bx+cw-17, ly+4, accent, 1.8,
                  f"pro-dimension-measure-right-{i}")


def _benefit_icon(scene, x, y, index, accent):
    """Simple semantic-neutral original vector marks, not certifications."""
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
    return scene.el("benefits", "path", f"pro-benefit-icon-{index}", {
        "d": shapes[index%len(shapes)], "stroke": accent,
        "stroke-width": 3.8, "stroke-linecap": "round",
        "stroke-linejoin": "round", "fill": "none"
    })

def _benefits(scene, benefits, x, y, w, h, accent, portrait):
    """Large pictograms and readable claims for either orientation."""
    if not benefits:
        return
    scene.rect("benefits", x, y, w, h, "#FFFFFF",
               rad=8, ident="pro-benefits-panel")
    caption_h = 42 if portrait else 38
    _ribbon(scene, "benefits", "ПРЕИМУЩЕСТВА", x+8, y+3,
            min(600, w*.56), caption_h, accent,
            "pro-benefits-title")
    cols = (2 if len(benefits) in (2,4) else min(3,len(benefits))) if portrait else min(4,len(benefits))
    rows = math.ceil(len(benefits)/cols)
    usable=h-caption_h-17
    col_w=(w-24)/cols
    row_h=usable/rows
    for i,claim in enumerate(benefits):
        bx=x+12+(i%cols)*col_w
        by=y+caption_h+10+(i//cols)*row_h
        if i%cols:
            _rule(scene, "benefits", bx, by+6,
                  bx, by+row_h-6, accent, 1.8,
                  f"pro-benefit-divider-{i}")
        # Horizontal cards at low heights prevent icon/text collisions.
        horizontal = (not portrait) or row_h < 106
        if horizontal:
            cx=bx+45
            cy=by+row_h*.50
            radius=min(27,max(15,row_h*.36))
            scene.el("benefits", "circle", f"pro-benefit-halo-{i}", {
                "cx":cx, "cy":cy, "r":radius,
                "fill":"#FFF0F1", "stroke":accent, "stroke-width":1.5
            })
            pictogram=_benefit_icon(scene,cx,cy,i,accent)
            # Scale only the pictogram, not its editable containing group.
            if pictogram is not None and radius<26:
                scale=radius/26
                pictogram.set("transform",
                    f"translate({cx*(1-scale):.2f} {cy*(1-scale):.2f}) "
                    f"scale({scale:.3f})")
            _copy(scene, "benefits", claim, bx+86,
                  by+8, col_w-97, row_h-15,
                  23, 12, INK, True,
                  f"pro-benefit-{i}", 2)
        else:
            cx=bx+col_w*.5
            cy=by+30
            scene.el("benefits", "circle", f"pro-benefit-halo-{i}", {
                "cx":cx, "cy":cy, "r":28,
                "fill":"#FFF0F1", "stroke":accent, "stroke-width":1.5
            })
            _benefit_icon(scene,cx,cy,i,accent)
            _copy(scene, "benefits", claim, bx+12,
                  by+65, col_w-24, row_h-71,
                  22, 12, INK, True,
                  f"pro-benefit-{i}", 2)

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
    """Label computed values with units; never imply independent guarantees."""
    if not brief.get("show_roi"):
        return
    data=compute_roi(brief)
    if not data:
        return
    currency=str(brief.get("currency") or "Br").strip()[:12] or "Br"
    metrics=[
        (f"ЗА РЕЙС, {currency}",data["per_trip"]),
        ("РЕЙСОВ В ГОД",data["trips"]),
        (f"ЗА ГОД, {currency}",data["annual"]),
        (f"БАЛАНС, {currency}",data["net"]),
    ]
    scene.rect("roi", x, y, w, h, "#FFF0F1",
               rad=6, ident="pro-roi-panel")
    cw=w/4
    for i,(label,value) in enumerate(metrics):
        bx=x+i*cw
        if i:
            _rule(scene, "roi", bx, y+7,
                  bx, y+h-7, "#ECAEB5", 2,
                  f"pro-roi-divider-{i}")
        _copy(scene, "roi", label, bx+13,
              y+5, cw-24, h*.31,
              19, 12, "#652A35", True,
              f"pro-roi-label-{i}", 1)
        formatted=f"{value:,.0f}".replace(","," ")
        _copy(scene, "roi", formatted, bx+13,
              y+h*.35, cw-24, h*.58,
              34, 16, accent, True,
              f"pro-roi-value-{i}", 1)


def _footer(scene, brief, accent, portrait):
    """Large price / prominent phones, with editable independent SVG groups."""
    w,h=scene.w,scene.h
    y=1720 if portrait else 950
    scene.rect("cta_bg", 0, y, w, h-y,
               "url(#pro-red-gradient)", ident="pro-cta")
    for i in range(3):
        xx=w-268+i*68
        scene.polygon("cta_bg", [
            (xx,y), (xx+45,y), (xx-118,h), (xx-163,h)
        ], "#FFFFFF", opacity=".16",
        ident=f"pro-cta-stripe-{i}")
    amount=_format_price(brief.get("price"))
    currency=str(brief.get("currency") or "").strip()
    vat=bool(brief.get("vat",True))
    price_copy=(amount+" "+currency+(" с НДС" if vat else "")
                if amount else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    phones=[str(v).strip() for v in (brief.get("phones") or [])[:2]
            if str(v).strip()]

    if portrait:
        scene.polygon("cta_bg", [
            (0,y), (w-40,y), (w-120,y+91), (0,y+91)
        ], accent, ident="pro-price-plate")
        _copy(scene, "price", price_copy, 38, y+13,
              w-95, 73, 69 if amount else 43, 24,
              "#FFFFFF", True, "pro-price", 1,
              italic=True)
        if phones:
            _rule(scene, "contacts", 36, y+103,
                  w-39, y+103, "#FFFFFF", 2.5,
                  "pro-contact-topline")
            _copy(scene, "contacts", "СВЯЖИТЕСЬ С НАМИ",
                  39, y+112, w*.46, 35, 27, 16,
                  "#FFFFFF", True, "pro-contact-label", 1,
                  italic=True)
            for i,phone in enumerate(phones):
                _copy(scene, "contacts", phone,
                      w*.52, y+111+i*37,
                      w*.44, 33, 27, 15,
                      "#FFFFFF", True,
                      f"pro-phone-{i}", 1)
        return

    side=w*.595
    scene.polygon("cta_bg", [
        (0,y),(side-17,y),(side-122,h),(0,h)
    ], accent, ident="pro-price-plate")
    _copy(scene, "price", price_copy, 41, y+24,
          side-131, h-y-31, 68 if amount else 38,
          21, "#FFFFFF", True, "pro-price", 1,
          italic=True)
    if phones:
        _rule(scene, "contacts", side-22, y+18,
              side-22, h-16, "#FFFFFF", 2.5,
              "pro-contact-divider")
        _copy(scene, "contacts", "СВЯЖИТЕСЬ С НАМИ",
              side+13, y+17, w-side-45, 34,
              27, 17, "#FFFFFF", True,
              "pro-contact-label", 1, italic=True)
        for i,phone in enumerate(phones):
            _copy(scene, "contacts", phone, side+13,
                  y+53+i*31, w-side-43, 31,
                  28, 17, "#FFFFFF", True,
                  f"pro-phone-{i}", 1)


def create_pro_campaign_svg(brief, key, hero=None, detail=None,
                            logo=None, drawing=None, backdrop=None,
                            ai_product=False):
    """Render a dense but legible reference-style campaign in both SVG sizes.

    Every numeric value and claim comes from the supplied form, never the
    reference. Missing sections are omitted, giving the hero more space.
    """
    if key not in ("4x3", "9x16"):
        raise ValueError("Неизвестное соотношение сторон.")
    portrait = key == "9x16"
    scene = Scene(key, brief.get("accent"), "industrial")
    accent = scene.accent
    _tint(scene, accent)
    scene.rect("decor", 0, 0, scene.w, scene.h,
               PAPER, ident="pro-paper")

    facts = _lines(brief, "specs", 8)
    dimensions = _lines(brief, "dimensions", 4)
    benefits = [str(v).strip()[:150]
                for v in (brief.get("benefits") or [])
                if str(v).strip()][:6]
    proof = [str(v).strip()[:180]
             for v in (brief.get("proof_points") or [])
             if str(v).strip()][:4]
    has_roi = bool(brief.get("show_roi") and compute_roi(brief))
    _header(scene, brief, logo, accent, portrait)

    top = 277 if portrait else 195
    bottom = 1711 if portrait else 941
    gap = 9 if portrait else 8
    segments = []

    if portrait and facts:
        # Match the height to the number of two-column rows: no empty 350px
        # strip when the customer provides only one or two specifications.
        rows = math.ceil(len(facts)/2)
        segments.append(("specs", 92*rows + 7*(rows-1) + 12))
    if dimensions or drawing is not None:
        if portrait:
            dim_h = 222 if drawing is not None else (
                197 if len(dimensions)>3 else 165)
        else:
            dim_h = 184 if drawing is not None else (
                164 if len(dimensions)>3 else 135)
        segments.append(("dimensions", dim_h))
    if benefits:
        if portrait:
            benefits_h = 228 if len(benefits)>3 else 162
        else:
            benefits_h = 179 if len(benefits)>4 else 133
        segments.append(("benefits", benefits_h))
    if proof:
        segments.append(("proof", 120 if portrait else 73))
    if has_roi:
        segments.append(("roi", 96 if portrait else 72))

    # Dense campaigns can otherwise shrink the landscape photograph to a
    # postage stamp. Shrink optional strip heights without hiding any claims.
    reserved = sum(size for _,size in segments)+len(segments)*gap
    minimum_hero = 395 if portrait else 305
    overflow = max(0, minimum_hero-(bottom-top-reserved))
    if overflow and not portrait:
        floors = {"benefits":126,"dimensions":134 if drawing else 112,
                  "proof":64,"roi":64}
        adapted=[]
        for kind,height in segments:
            reduction=min(overflow,max(0,height-floors.get(kind,height)))
            adapted.append((kind,height-reduction))
            overflow-=reduction
        segments=adapted
    reserved=sum(size for _,size in segments)+len(segments)*gap
    hero_height=bottom-top-reserved
    if hero_height < 185:
        # Narrow unexpected content must not emit inverted SVG viewports.
        raise ValueError("Слишком много элементов для рекламного макета.")

    if portrait:
        _hero(scene,hero,detail,backdrop,ai_product,brief,accent,
              18,top,scene.w-36,hero_height)
    else:
        if facts:
            _hero(scene,hero,detail,backdrop,ai_product,brief,accent,
                  15,top,909,hero_height)
            _specs(scene,facts,939,top,
                   scene.w-955,hero_height,accent,False)
        else:
            _hero(scene,hero,detail,backdrop,ai_product,brief,accent,
                  15,top,scene.w-30,hero_height)

    cursor=top+hero_height+gap
    for kind,height in segments:
        x=18 if portrait else 15
        w=scene.w-2*x
        if kind=="specs":
            _specs(scene,facts,x,cursor,w,height,accent,True)
        elif kind=="dimensions":
            _dimensions(scene,dimensions,drawing,x,cursor,w,height,
                        accent,portrait)
        elif kind=="benefits":
            _benefits(scene,benefits,x,cursor,w,height,accent,portrait)
        elif kind=="proof":
            _proof(scene,proof,x,cursor,w,height,accent,portrait)
        elif kind=="roi":
            _roi(scene,brief,x,cursor,w,height,accent)
        cursor += height+gap

    _footer(scene,brief,accent,portrait)
    return scene.export()