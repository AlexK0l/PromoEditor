"""Repair AI-inferred EMPTY text regions without changing AI artwork.

This is local geometry reconciliation, NOT a fallback poster template.
Keep AI-proposed coordinates unchanged whenever they are valid. Only shift
conflicting exact-copy text regions into nearby unoccupied canvas space, and
verify that every character will fit before authoring editable SVG layers.

There are NO OpenAI requests in this module: a paid layout assessment can be
salvaged from its private cache after a collision, without another Images call.
"""
from __future__ import annotations

from itertools import product

from .ai_exact_copy_render import (
    BASE_PX, MIN_PX, DEFAULT_STYLE, FORMATS, ROLES, _size_and_lines,
    validate_slots,
)
from .ai_layout import _intersection

# Readable logo, headline, sale and spec regions take precedence. A short
# category line moves before a long benefits/specs block when AI overlaps
# these two zones (the reported 9:16 production failure).
PRIORITY = (
    "logo", "brand", "model", "price", "phones",
    "specs", "dimensions", "benefits", "claims", "slogan",
    "proofs", "category", "roi", "drawing",
)
GAP = 5
EDGE = 16


def _protected_product(box: dict, fmt: str) -> dict:
    """Conservative visual safety margin for truck wheels, ground shadows.

    AI frequently labels only the yellow trailer BODY. The real wheels and
    chassis extend BELOW its reported bbox. Marketing text must not be set
    directly over wheels, mudguards or the undercarriage.
    """
    left=max(0,box["x"]-24)
    top=max(0,box["y"]-20)
    right=min(1000,box["x"]+box["w"]+24)
    bottom=min(1000,box["y"]+box["h"]+
               (140 if fmt=="4x3" else 85))
    return {"x":left,"y":top,"w":right-left,"h":bottom-top}


def _fits_copy(role: str, box: dict, fmt: str, copy: dict) -> bool:
    if role not in ROLES or not copy.get(role):
        return True
    canvas_w, canvas_h = FORMATS[fmt]
    width = box["w"] * canvas_w / 1000
    height = box["h"] * canvas_h / 1000
    margin = max(4, min(width, height)*.025)
    width -= margin * 2
    height -= margin * 2
    if width <= 0 or height <= 0:
        return False
    bold = role in ("brand", "model", "slogan", "price", "claims")
    ideal = min(int(BASE_PX[role]*DEFAULT_STYLE["scale_percent"]/100),
                int(height*.72))
    minimum = MIN_PX[role]
    if ideal < minimum:
        return False
    try:
        _size_and_lines(
            copy[role], width, height, DEFAULT_STYLE["font_family"],
            bold, ideal, minimum,
        )
        return True
    except ValueError:
        return False


def _clear(box: dict, occupied: list[dict]) -> bool:
    if (box["x"] < EDGE or box["y"] < EDGE
            or box["x"]+box["w"] > 1000-EDGE
            or box["y"]+box["h"] > 1000-EDGE):
        return False
    # No overlap with the photographed trailer, protected logo, or other
    # exact text layers. 5 normalized units prevent nearly touching captions.
    expanded = {
        "x":box["x"]-GAP, "y":box["y"]-GAP,
        "w":box["w"]+2*GAP, "h":box["h"]+2*GAP,
    }
    return all(_intersection(expanded, fixed) == 0 for fixed in occupied)


def _sizes(original: dict):
    w, h = original["w"], original["h"]
    candidates = [
        (w, h),
        (min(960, round(w*1.12)), h),
        (w, min(960, round(h*1.20))),
        (min(960, round(w*1.18)), min(960, round(h*1.20))),
        (min(960, round(w*1.34)), min(960, round(h*1.35))),
        (max(35,round(w*.88)), min(960,round(h*1.35))),
        (min(960,round(w*1.18)), min(960,round(h*1.8))),
        (min(960,round(w*1.45)), min(960,round(h*2.4))),
        (max(w,280),max(h,90)),
        (max(w,430),max(h,160)),
        (max(w,590),max(h,220)),
    ]
    seen=set()
    for new_w, new_h in candidates:
        if new_w >= 30 and new_h >= 20 and (new_w,new_h) not in seen:
            seen.add((new_w,new_h))
            yield new_w,new_h


def _candidate_positions(original: dict, w: int, h: int,
                         occupied: list[dict]):
    x0, y0=original["x"],original["y"]
    max_x=1000-EDGE-w
    max_y=1000-EDGE-h
    if max_x < EDGE or max_y < EDGE:
        return
    # Search AI-proposed neighborhood first, then wider uncluttered areas.
    # Semantic positions are inherited from AI, not a standard card grid.
    xs = set(range(EDGE,max_x+1,18))
    ys = set(range(EDGE,max_y+1,18))
    xs.add(max(EDGE,min(max_x,x0)))
    ys.add(max(EDGE,min(max_y,y0)))
    for rectangle in occupied:
        for x in (
            rectangle["x"]-w-GAP*2,rectangle["x"]+rectangle["w"]+GAP*2,
        ):
            if EDGE <= x <= max_x: xs.add(x)
        for y in (
            rectangle["y"]-h-GAP*2,rectangle["y"]+rectangle["h"]+GAP*2,
        ):
            if EDGE <= y <= max_y: ys.add(y)
    # Make nearby candidates win. A distant relocation is a last resort;
    # never put text over the trailer just to avoid a validation error.
    positions = sorted(
        product(xs,ys),
        key=lambda p:(abs(p[0]-x0)+abs(p[1]-y0),
                      abs(p[1]-y0),abs(p[0]-x0)),
    )
    for x,y in positions:
        yield {"x":int(x),"y":int(y),"w":w,"h":h}


def _relocate(role: str, original: dict, fmt: str, copy: dict,
              occupied: list[dict]) -> dict:
    for width,height in _sizes(original):
        probe = dict(original,x=EDGE,y=EDGE,w=width,h=height)
        if not _fits_copy(role,probe,fmt,copy):
            continue
        for candidate in _candidate_positions(
                original,width,height,occupied):
            if _clear(candidate,occupied):
                return candidate
    raise ValueError(
        f"AI не оставил достаточно свободного места для «{role}» ({fmt}). "
        "Текст не обрезан, пересечения с прицепом нет. "
        "Уже созданные платные AI-макеты сохранены для следующей попытки."
    )


def repair_ai_slots(geometry: dict, copy: dict, *,
                    has_logo: bool = False,
                    has_drawing: bool = False,
                    protect_product: bool = False) -> dict:
    """Return only collision-free text boxes based on AI-generated regions.

    Reject invalid schemas outright. Preserve every AI box if it was already
    valid; never silently replace AI artwork with a procedural design.
    """
    # Empty copy checks the full JSON shape, geometry values and canvas
    # containment before attempting any repair on model-supplied input.
    validate_slots(geometry,{})
    try:
        validated=validate_slots(
            geometry,copy,has_logo=has_logo,has_drawing=has_drawing)
        if (all(_fits_copy(role,validated[fmt][role],fmt,copy)
                for fmt in FORMATS for role in ROLES if copy.get(role))
                and (not protect_product or all(
                    _intersection(validated[fmt][role],
                                  _protected_product(validated[fmt]["product"],fmt))==0
                    for fmt in FORMATS for role in ROLES if copy.get(role)))):
            return validated
    except ValueError:
        pass

    result={}
    active=set(role for role in ROLES if copy.get(role))
    if has_logo: active.add("logo")
    if has_drawing: active.add("drawing")
    for fmt, ai in geometry.items():
        repaired={role:dict(rect) for role,rect in ai.items()}
        product_box=ai["product"]
        occupied=[_protected_product(product_box,fmt)
                  if protect_product else product_box]
        for role in PRIORITY:
            if role not in active:
                continue
            original=ai[role]
            # Existing valid high-priority AI slots are not moved unless
            # they actually intersect another protected region/vehicle or
            # cannot fit their exact approved customer text.
            if (_clear(original,occupied)
                    and _fits_copy(role,original,fmt,copy)):
                chosen=original
            else:
                chosen=_relocate(role,original,fmt,copy,occupied)
            repaired[role]=dict(chosen)
            occupied.append(chosen)
        result[fmt]=repaired
    # The same strict, public validation runs AFTER reconciliation: no
    # geometric overlap or out-of-bounds facts can escape into the SVG.
    return validate_slots(
        result,copy,has_logo=has_logo,has_drawing=has_drawing,
    )
