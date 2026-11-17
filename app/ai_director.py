"""OpenAI art director: optional style references, actual AI-planned geometry.

The model chooses the layout and produces a text-free art-direction plate.
Verified prices, specs, drawing, product and logo are then rendered as separate
editable SVG objects. No fixed sample-poster image is inserted.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from typing import Any

from PIL import Image

from .openai_service import as_image, client, _image_references
from .image_analysis import analysis_preview
from .editable_export import Scene
from .campaign_layout import _lines, _photo, _check, _rule, _format_price
from .campaign_pro_v3 import _type
from .campaign_pro_v4 import _side_elevation, _tight_product_photo
from .render import compute_roi

REGIONS = ("header", "hero", "specs", "drawing", "benefits", "proof", "finance", "footer")
SIZES = {"4x3": (1440, 1080), "9x16": (1080, 1920)}
IMAGE_SIZES = {"4x3": "1536x1024", "9x16": "1024x1536"}
HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")

# A compact, supported subset of JSON Schema for Responses structured outputs.
_RECT_SCHEMA = {"type": "array", "items": {"type": "integer"},
                "minItems": 4, "maxItems": 4}
_LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {k: _RECT_SCHEMA for k in REGIONS},
    "required": list(REGIONS), "additionalProperties": False,
}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "concept": {"type": "string"},
        "scene_prompt": {"type": "string"},
        "ink": {"type": "string"},
        "surface": {"type": "string"},
        "support": {"type": "string"},
        "layouts": {"type": "object", "properties": {
            "4x3": _LAYOUT_SCHEMA, "9x16": _LAYOUT_SCHEMA,
        }, "required": ["4x3", "9x16"], "additionalProperties": False},
    },
    "required": ["concept", "scene_prompt", "ink", "surface",
                 "support", "layouts"],
    "additionalProperties": False,
}


def _image_data(raw: bytes, *, max_edge: int = 640) -> str:
    image, _ = analysis_preview(raw, max_edge=max_edge)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _bounds(rect: list[int], key: str, name: str) -> tuple[float, ...]:
    if not isinstance(rect, list) or len(rect) != 4 or any(
        type(t) is not int for t in rect
    ):
        raise ValueError(f"AI-план: неверные координаты {key}/{name}.")
    x, y, w, h = rect
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1000 or y+h > 1000:
        raise ValueError(f"AI-план: область {key}/{name} выходит за постер.")
    return tuple(float(z) for z in rect)


def _active(brief: dict) -> set[str]:
    names = {"header", "footer", "hero"}
    for item, cond in (
        ("specs", bool(brief.get("specs"))),
        ("drawing", bool(brief.get("dimensions")) or bool(brief.get("_has_drawing"))),
        ("benefits", bool(brief.get("benefits"))),
        ("proof", bool(brief.get("proof_points") or brief.get("hero_claims"))),
        ("finance", bool(brief.get("show_roi") and compute_roi(brief))),
    ):
        if cond:
            names.add(item)
    return names


def validate_plan(plan: Any, brief: dict) -> dict:
    """Reject unsafe/overlapping layouts. Never silently fall back to a grid."""
    if not isinstance(plan, dict) or not isinstance(plan.get("layouts"), dict):
        raise ValueError("OpenAI не вернул структурированный дизайн-план.")
    for color in ("ink", "surface", "support"):
        if not HEX.fullmatch(str(plan.get(color, ""))):
            raise ValueError(f"AI-план: недопустимый цвет {color}.")
    if not str(plan.get("scene_prompt") or "").strip():
        raise ValueError("AI-план не содержит описание художественной сцены.")
    active = _active(brief)
    for key in SIZES:
        layout = plan["layouts"].get(key)
        if not isinstance(layout, dict):
            raise ValueError(f"AI-план: отсутствует формат {key}.")
        for region in REGIONS:
            _bounds(layout.get(region), key, region)
        width, height = SIZES[key]
        px = {name: tuple(
            (rect[i]/1000) * (width if i % 2 == 0 else height)
            for i in range(4)
        ) for name, rect in layout.items() if name in REGIONS}
        mins = {
            "4x3": {"header": (900, 103), "hero": (480, 250),
                    "specs": (305, 275), "drawing": (500, 122),
                    "benefits": (650, 65), "proof": (650, 48),
                    "finance": (650, 68),
                    "footer": (900, 103)},
            "9x16": {"header": (650, 145), "hero": (550, 300),
                     "specs": (570, 280), "drawing": (580, 150),
                     "benefits": (560, 125), "proof": (560, 110),
                     "finance": (560, 115),
                     "footer": (650, 165)},
        }[key]
        for name in active:
            if px[name][2] < mins[name][0] or px[name][3] < mins[name][1]:
                raise ValueError(f"AI-план: секция {key}/{name} слишком мала.")
        # Strictly separate the factual content regions. Imagery remains
        # underneath in its own layer and is not checked for intersections.
        for i, a in enumerate(REGIONS):
            if a not in active:
                continue
            x,y,w,h = px[a]
            for b in REGIONS[i+1:]:
                if b not in active:
                    continue
                u,v,p,q = px[b]
                overlap_w = max(0., min(x+w,u+p)-max(x,u))
                overlap_h = max(0., min(y+h,v+q)-max(y,v))
                if overlap_w*overlap_h > 8*min(w,h,p,q):
                    raise ValueError(
                        f"AI-план: секции {key}/{a} и {key}/{b} пересекаются."
                    )
    return plan


def _brief_for_ai(brief: dict) -> dict:
    """Only bounded task facts, no internal auth tokens or file paths."""
    keys = ("brand", "category", "model", "slogan", "specs", "dimensions",
            "benefits", "proof_points", "hero_claims", "design_notes",
            "design_actions", "accent", "price", "currency", "phones")
    return {k: brief.get(k) for k in keys}


def generate_plan(brief: dict, *, references: list[bytes] | None = None,
                  hero_raw: bytes | None = None,
                  model: str | None = None,
                  feedback: str = "") -> dict:
    """One text/vision planning call; OPTIONAL reference photos.

    Passing zero visual references is supported and expected. Existing source
    photos can be included so the model learns the product's silhouette, but
    it is forbidden to replace or invent verified product details.
    """
    format_model = model or os.environ.get(
        "OPENAI_LAYOUT_MODEL",
        os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.6-terra"))
    inputs: list[dict] = [{
        "type": "input_text",
        "text": json.dumps({
            "brief": _brief_for_ai(brief),
            "formats": ["4x3", "9x16"],
            "has_reference": bool(references),
            "active_regions": sorted(_active(brief)),
            "previous_validation_error": str(feedback)[:300],
        }, ensure_ascii=False),
    }]
    if hero_raw:
        inputs.append({"type": "input_image",
                       "image_url": _image_data(hero_raw, max_edge=640)})
    for raw in (references or [])[:2]:
        inputs.append({"type": "input_image",
                       "image_url": _image_data(raw, max_edge=640)})
    instructions = (
        "You are the creative director of a premium B2B industrial poster. "
        "Design TWO original print-ready layouts, 4:3 landscape and 9:16 portrait. "
        "Return a JSON design plan, not finished copy. Coordinates in each "
        "layout are integer [x,y,width,height] in a 1000x1000 normalized grid. "
        "Place header at top, footer at bottom. The hero should dominate. "
        "Here are safe EXAMPLE placements to understand the geometry (not "
        "a mandatory template): landscape header [0,0,1000,145], hero "
        "[0,145,645,380], specs [650,145,350,380], drawing "
        "[0,525,1000,155], benefits [0,680,1000,75], proof "
        "[0,755,1000,55], finance [0,810,1000,70], footer "
        "[0,880,1000,120]; portrait header [0,0,1000,120], "
        "hero [0,120,1000,230], specs [0,350,1000,185], "
        "drawing [0,535,1000,125], benefits [0,660,1000,95], "
        "proof [0,755,1000,70], finance [0,825,1000,80], "
        "footer [0,905,1000,95]. "
        "Create your own safe art-directed variation while "
        "maintaining these minimum visual areas and a coherent hierarchy. "
        "Reserve genuinely separate, sufficiently large areas for specifications, "
        "real technical drawing, benefits and finance where supplied. "
        "Do not overlap any active areas; follow the JSON schema. "
        "All numeric facts, phone numbers, model identifiers and provided claims "
        "are IMMUTABLE source data and will be typeset by the application, "
        "not generated into the background art. For absent sections, their "
        "rectangles may be arbitrary valid unused slots, but place active "
        "sections with generous readable spacing. "
        "You may choose editorial, cinematic, brutalist or other coherent "
        "commercial visual styles; describe a photographic/illustrative ART "
        "PLATE in scene_prompt. No text, logos, vehicles, technical diagrams, "
        "charts or numbers in that plate; reserve the hero area for the "
        "user's source product photograph. Accent is defined by the brief. "
        "If reference images were supplied, use them for art direction, "
        "NEVER copy their product, specific words or brands. "
        "If no reference images were supplied, invent the visual direction "
        "using category, brand accent and design notes. "
        "Readable contrast and a professional hierarchy are essential."
    )
    api = client()
    response = api.responses.create(
        model=format_model,
        instructions=instructions,
        input=[{"role": "user", "content": inputs}],
        text={"format": {"type": "json_schema", "name": "promo_art_direction",
                         "schema": PLAN_SCHEMA, "strict": True}},
    )
    if getattr(response, "status", "completed") not in (None, "completed"):
        raise ValueError("OpenAI не завершил подготовку дизайн-плана.")
    raw = getattr(response, "output_text", "") or ""
    try:
        candidate = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("OpenAI вернул нечитабельный дизайн-план.") from exc
    return validate_plan(candidate, brief)




def preflight_typography(brief: dict, plan: dict,
                        *, drawing_present: bool = False) -> None:
    """Check immutable copy BEFORE spending on two image requests.

    The planned coordinates are rendered offline with a tiny blank bitmap.
    Truncating numeric specs, dimensions, model names or contact numbers is
    unacceptable; bad layouts fail loudly with a clear validation error.
    """
    import xml.etree.ElementTree as ET

    placeholder=Image.new("RGB",(12,12),"#E7ECEF")
    dummy_drawing=placeholder if drawing_present else None
    for key in SIZES:
        xml=render_ai_poster(
            brief,key,plan,placeholder,drawing=dummy_drawing)
        root=ET.fromstring(xml)
        important=("ai-model-","ai-category-","ai-spec-name-",
                   "ai-spec-value-","ai-dim-name-","ai-dim-value-",
                   "ai-proof-statement-","ai-price-","ai-phone-")
        nodes=[node for node in root.iter()
               if node.tag.endswith("}text") and
               node.get("id","").startswith(important)]
        for node in nodes:
            rendered=" ".join(node.itertext())
            if "…" in rendered:
                raise ValueError(
                    f"AI-дизайн {key}: текст {node.get('id')} обрезан. "
                    "Измените краткое название/текст или повторите генерацию "
                    "дизайна. Художественные изображения ещё не создавались."
                )
        labels=" ".join(" ".join(node.itertext()) for node in nodes)
        for item in (brief.get("model") or "",
                     *[v[1] for v in _lines(brief,"specs",8)],
                     *[v[1] for v in _lines(brief,"dimensions",4)],
                     *[str(v) for v in (
                         brief.get("proof_points") or brief.get("hero_claims") or [])[:4]],
                     *[str(v) for v in (brief.get("phones") or [])[:2]]):
            if item and str(item) not in labels:
                raise ValueError(
                    f"AI-дизайн {key}: значение «{str(item)[:48]}» "
                    "не помещается в макет. Платные изображения ещё "
                    "не генерировались."
                )


def generate_artwork(brief: dict, plan: dict, *,
                     references: list[bytes] | None = None,
                     hero_raw: bytes | None = None,
                     scene_raw: bytes | None = None,
                     model: str = "gpt-image-2.5-flare",
                     quality: str = "medium",
                     design_prompt: str = "") -> dict[str, Image.Image]:
    """Image generation supplies visual art, not factual copy or source goods."""
    from .openai_service import IMAGE_MODELS, IMAGE_QUALITIES
    if model not in IMAGE_MODELS or quality not in IMAGE_QUALITIES:
        raise ValueError("Недопустимая модель OpenAI или качество.")
    api = client()
    # Product is shown to the TEXT design planner for scale and composition.
    # Never feed it to the image ART edit: even with a strict prompt, an
    # image model can accidentally draw a duplicate or altered trailer.
    materials = ([scene_raw] if scene_raw else []) + list((references or [])[:2])
    out = {}
    for key in SIZES:
        layout = plan["layouts"][key]
        prompt = (
            "Create an original premium industrial advertising ART-DIRECTION "
            "PLATE, full-bleed graphic/photographic design with sophisticated "
            "lighting, depth, material texture, directional graphic accents, "
            "and realistic industrial context. The creative director's "
            f"concept: {plan['concept'][:250]}. "
            f"Visual scene: {plan['scene_prompt'][:1200]}. "
            f"Art direction notes: {str(design_prompt)[:1500]}. "
            f"Canvas format {key}. Source category: {brief.get('category','')}. "
            f"Brand accent {brief.get('accent','#E31B26')}. "
            "All text and product source assets will be placed separately "
            "as exact editable layers. Therefore NO readable text, numbers, "
            "watermarks, logotypes, banners with letters, technical drawings "
            "or invented promotional claims anywhere in the image. "
            "Do not duplicate, reproduce, modify, redraw or invent the "
            "advertised product. The real product appears later in the "
            "reserved hero region, supplied as independent source pixels. "
            "Keep the hero region visually clean, unobstructed and convincingly "
            "grounded, using matching lighting and a believable floor. "
            "Do not add text boxes or fake technical grids. "
            "Reserved layout areas, normalized as x,y,width,height: "
            + json.dumps(layout, ensure_ascii=False)
            + ". The source image(s), if any, are solely composition, "
            "lighting and optional reference style guidance. Do NOT copy "
            "reference logos or machinery. Art should read like a polished "
            "agency-produced advertising poster after overlaying type."
        )
        if materials:
            buffers = _image_references(materials[:4])
            result = api.images.edit(
                model=model, image=buffers, prompt=prompt,
                size=IMAGE_SIZES[key], quality=quality,
                output_format="png"
            )
        else:
            result = api.images.generate(
                model=model, prompt=prompt, size=IMAGE_SIZES[key],
                quality=quality, output_format="png"
            )
        out[key] = as_image(result)
    return out


def _pos(layout: dict, key: str, name: str) -> tuple[float,float,float,float]:
    width,height = SIZES[key]
    x,y,w,h = layout[name]
    return (x*width/1000,y*height/1000,
            w*width/1000,h*height/1000)


def _text(scene, group, content, x, y, w, h, size=30, minimum=12,
          color="#151923", bold=True, ident="ai-text", max_lines=2):
    return _type(scene, group, str(content), x, y, w, h,
                 size, minimum, color, bold, ident, max_lines)


def _panel(scene,layer,x,y,w,h,surface,ident,alpha=".94"):
    scene.rect(layer,x,y,w,h,surface,rad=9,opacity=alpha,ident=ident)


def render_ai_poster(brief: dict, key: str, plan: dict,
                     artwork: Image.Image, *, hero=None, detail=None,
                     logo=None, drawing=None) -> bytes:
    """Create a fully layered CorelDRAW SVG from AI-planned geometry."""
    validate_plan(plan, {**brief, "_has_drawing": drawing is not None})
    scene = Scene(key,brief.get("accent"),"industrial")
    w,h=SIZES[key]
    a=scene.accent
    colors={k:plan[k] for k in ("ink","surface","support")}
    layout=plan["layouts"][key]
    active=_active({**brief,"_has_drawing":drawing is not None})

    # Editable full-bleed AI art: never a baked factual poster.
    background=scene.bitmap("background",artwork,0,0,w,h,"ai-art-director-artwork")
    if background is not None:
        background.set("preserveAspectRatio","xMidYMid slice")
    scene.groups["decor"].clear()

    x,y,bw,bh=_pos(layout,key,"header")
    scene.rect("decor",x,y,bw,bh,a,opacity=".98",ident="ai-header")
    scene.polygon("decor",[(x+bw*.83,y),(x+bw*.87,y),
                            (x+bw*.78,y+bh),(x+bw*.74,y+bh)],
                  "#FFFFFF",opacity=".18",ident="ai-header-stripe")
    logo_w=min(bw*.19, bh*1.12)
    if logo is not None:
        scene.rect("logo",x+9,y+7,logo_w,bh-15,"#FFFFFF",
                   rad=4,ident="ai-logo-tile")
        _photo(scene,logo,x+15,y+12,logo_w-12,bh-24,
               "original-logo",layer="logo",trim=True)
    else:
        _text(scene,"logo",brief.get("brand") or "BRAND",
              x+12,y+bh*.31,logo_w-15,bh*.5,27,14,"#FFFFFF",
              True,"ai-brand",2)
    text_x=x+logo_w+30
    text_w=max(80,bw-(text_x-x)-24)
    _text(scene,"heading",str(brief.get("category") or "").upper(),
          text_x,y+bh*.09,text_w,bh*.28,
          int(max(19,min(43,bh*.24))),15,"#FFFFFF",
          True,"ai-category",1)
    _text(scene,"heading",brief.get("model") or "",
          text_x,y+bh*.38,text_w,bh*.43,
          int(max(30,min(73,bh*.42))),18,"#FFFFFF",
          True,"ai-model",1)
    slogan=str(brief.get("slogan") or "")
    if slogan:
        _text(scene,"heading",slogan,text_x,y+bh*.82,
              text_w,bh*.19,max(16,int(bh*.15)),11,
              "#FFFFFF",True,"ai-slogan",1)

    x,y,bw,bh=_pos(layout,key,"hero")
    if hero is not None:
        # Product is untouched except cropping transparent padding in a
        # disposable presentation copy; source photo stays in the ZIP.
        product=_tight_product_photo(hero)
        _photo(scene,product,x+5,y+3,bw-10,bh-8,
               "original-product-photo",layer="photos",trim=False)
    else:
        _text(scene,"claims","AI-ВИЗУАЛИЗАЦИЯ",x+12,y+bh-38,
              min(bw*.45,300),30,18,12,a,True,"ai-no-product",1)
    if detail is not None:
        ww=min(bw*.23,140)
        hh=min(bh*.28,105)
        scene.rect("photos",x+8,y+bh-hh-12,ww+7,hh+7,
                   "#FFFFFF",rad=5,ident="ai-detail-tile")
        _photo(scene,detail,x+12,y+bh-hh-8,ww-1,hh-1,
               "detail-photo",layer="photos",trim=True)

    if "specs" in active:
        x,y,bw,bh=_pos(layout,key,"specs")
        _panel(scene,"specs",x,y,bw,bh,colors["surface"],"ai-spec-panel")
        facts=_lines(brief,"specs",8)
        cols=2 if bw>=570 else 1
        rows=math.ceil(len(facts)/cols)
        row_h=(bh-17)/rows
        col_w=(bw-18)/cols
        for i,(name,value) in enumerate(facts):
            ix=i%cols
            iy=i//cols
            xx=x+9+ix*col_w
            yy=y+6+iy*row_h
            scene.rect("specs",xx,yy+5,3,row_h-10,a,ident=f"ai-spec-accent-{i}")
            _text(scene,"specs",name,xx+11,yy+2,col_w*.56-12,
                  row_h-4,min(23,int(row_h*.32)),10,
                  colors["ink"],True,f"ai-spec-name-{i}",2)
            _text(scene,"specs",value,xx+col_w*.58,yy+2,
                  col_w*.4-8,row_h-4,
                  min(30,int(row_h*.47)),12,a,True,
                  f"ai-spec-value-{i}",2)

    if "drawing" in active:
        x,y,bw,bh=_pos(layout,key,"drawing")
        _panel(scene,"dimensions",x,y,bw,bh,colors["surface"],"ai-drawing-panel")
        title_h=max(24,min(32,bh*.18))
        _text(scene,"dimensions","ГАБАРИТЫ И ЧЕРТЁЖ",
              x+10,y+4,bw-16,title_h,25,13,a,True,
              "ai-drawing-heading",1)
        dimensions=_lines(brief,"dimensions",4)
        stats_w=min(bw*.27,255) if dimensions else 0
        if drawing is not None:
            projection, was_cropped=_side_elevation(drawing)
            _photo(scene,projection,x+8,y+title_h+5,
                   max(80,bw-stats_w-23),max(30,bh-title_h-13),
                   "original-drawing",layer="dimensions")
            if was_cropped:
                _text(scene,"dimensions","БОКОВОЙ ВИД",
                      x+bw-stats_w-185,y+6,176,title_h-2,
                      15,10,a,True,"ai-side-view",1)
        if dimensions:
            dh=(bh-title_h-8)/len(dimensions)
            for i,(name,value) in enumerate(dimensions):
                yy=y+title_h+5+i*dh
                left=x+bw-stats_w
                scene.rect("dimensions",left,yy,
                           max(1,stats_w-6),max(1,dh-3),
                           "#F5F6F7",rad=3,ident=f"ai-dim-row-{i}")
                _text(scene,"dimensions",name.upper(),left+5,yy+1,
                      stats_w*.48-8,dh-4,
                      min(17,int(dh*.37)),10,colors["ink"],
                      True,f"ai-dim-name-{i}",1)
                _text(scene,"dimensions",value,left+stats_w*.49,yy+1,
                      stats_w*.48-9,dh-4,
                      min(25,int(dh*.52)),12,a,
                      True,f"ai-dim-value-{i}",1)

    if "benefits" in active:
        x,y,bw,bh=_pos(layout,key,"benefits")
        _panel(scene,"benefits",x,y,bw,bh,colors["surface"],"ai-benefits-panel")
        benefits=[str(v).strip() for v in brief.get("benefits") or []
                  if str(v).strip()][:6]
        cols=min(4,len(benefits)) if bw>850 else min(2,len(benefits))
        rows=math.ceil(len(benefits)/max(cols,1))
        cw=(bw-12)/max(cols,1)
        ch=(bh-10)/max(1,rows)
        for i,item in enumerate(benefits):
            xx=x+6+(i%cols)*cw
            yy=y+5+(i//cols)*ch
            scene.el("benefits","circle",f"ai-benefit-icon-{i}",{
                "cx":xx+18,"cy":yy+ch*.5,"r":13,
                "fill":"none","stroke":a,"stroke-width":2.5,
            })
            _check(scene,"benefits",xx+11,yy+ch*.5-7,15,a,
                   f"ai-benefit-check-{i}")
            _text(scene,"benefits",item,xx+40,yy+3,cw-49,ch-5,
                  min(25,int(ch*.30)),12,
                  colors["ink"],True,f"ai-benefit-{i}",3)

    if "proof" in active:
        x,y,bw,bh=_pos(layout,key,"proof")
        _panel(scene,"claims",x,y,bw,bh,colors["surface"],"ai-proof-panel")
        statements=[str(t).strip() for t in (
            brief.get("proof_points") or brief.get("hero_claims") or [])
            if str(t).strip()][:4]
        heading="ПОДТВЕРЖДЁННЫЕ ФАКТЫ" if brief.get("proof_points") else "КЛЮЧЕВЫЕ ТЕЗИСЫ"
        lead=min(218,bw*.26)
        scene.rect("claims",x+4,y+4,lead,bh-8,a,
                   rad=5,ident="ai-proof-label-bg")
        _text(scene,"claims",heading,x+14,y+bh*.17,
              lead-19,bh*.70,min(23,int(bh*.31)),11,
              "#FFFFFF",True,"ai-proof-heading",2)
        ww=max(80,bw-lead-14)
        cols=4 if ww>=800 else 2
        cols=min(cols,len(statements))
        rows=math.ceil(len(statements)/max(cols,1))
        cw=ww/cols
        ch=bh/rows
        for i,item in enumerate(statements):
            xx=x+lead+12+(i%cols)*cw
            yy=y+(i//cols)*ch
            _check(scene,"claims",xx+4,yy+ch*.32,
                   min(17,max(9,ch*.23)),a,f"ai-proof-check-{i}")
            _text(scene,"claims",item,xx+27,yy+3,
                  cw-32,ch-5,min(19,int(ch*.27)),11,
                  colors["ink"],True,f"ai-proof-statement-{i}",3)

    if "finance" in active:
        roi=compute_roi(brief)
        if roi:
            x,y,bw,bh=_pos(layout,key,"finance")
            _panel(scene,"roi",x,y,bw,bh,colors["surface"],
                   "ai-finance-panel",alpha=".96")
            metrics=[("ЗА РЕЙС",roi["per_trip"]),
                     ("РЕЙСОВ В ГОД",roi["trips"]),
                     ("ЗА ГОД",roi["annual"]),
                     ("БАЛАНС",roi["net"])]
            cols=4 if bw>=840 else 2
            cw=bw/cols
            ch=bh/math.ceil(4/cols)
            for i,(label,value) in enumerate(metrics):
                xx=x+(i%cols)*cw
                yy=y+(i//cols)*ch
                if i%cols:
                    _rule(scene,"roi",xx,yy+6,xx,yy+ch-6,
                          "#DEB2BA",1.5,f"ai-finance-sep-{i}")
                _text(scene,"roi",label,xx+9,yy+4,cw-16,ch*.30,
                      min(19,int(ch*.24)),10,
                      colors["ink"],True,f"ai-finance-label-{i}",1)
                _text(scene,"roi",
                      f"{value:,.0f}".replace(","," "),
                      xx+9,yy+ch*.35,cw-17,ch*.59,
                      min(44,int(ch*.49)),15,a,True,
                      f"ai-finance-value-{i}",1)

    x,y,bw,bh=_pos(layout,key,"footer")
    scene.rect("cta_bg",x,y,bw,bh,a,ident="ai-footer")
    scene.polygon("cta_bg",[
        (x+bw*.59,y),(x+bw*.63,y),
        (x+bw*.56,y+bh),(x+bw*.52,y+bh)
    ],"#FFFFFF",ident="ai-footer-diagonal")
    px=x+12
    price=_format_price(brief.get("price"))
    unit=str(brief.get("currency") or "Br")
    offer=(price+" "+unit+(" с НДС" if brief.get("vat",True) else "")
           if price else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    _text(scene,"price",offer,px,y+bh*.16,bw*.54-24,bh*.76,
          min(72,int(bh*.56)),20,"#FFFFFF",
          True,"ai-price",2)
    phones=[str(t) for t in brief.get("phones") or [] if str(t).strip()][:2]
    phone_x=x+bw*.65
    _text(scene,"contacts","СВЯЖИТЕСЬ С НАМИ",phone_x,y+bh*.08,
          bw*.32,bh*.27,min(23,int(bh*.18)),12,
          "#FFFFFF",True,"ai-cta-heading",1)
    for i,phone in enumerate(phones):
        _text(scene,"contacts",phone,phone_x,
              y+bh*(.34+i*.29),bw*.32,bh*.29,
              min(25,int(bh*.20)),12,
              "#FFFFFF",True,f"ai-phone-{i}",1)
    return scene.export()
