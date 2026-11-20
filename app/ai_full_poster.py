"""Full AI-authored poster artwork with exact customer data overlays.

OpenAI Images paints the COMPLETE poster graphics, including the photo scene,
decoration, typography-safe panels and separators. OpenAI Responses supplies
their positions. This renderer has NO hand-coded graphic panels or templates:
it only embeds the customer's unchanged source assets and typesets approved
facts into the AI-selected regions. All factual text stays editable in SVG.
"""
from __future__ import annotations

from PIL import Image, ImageOps

from .ai_layout import validate_concept, validate_renderability
from .campaign_layout import _format_price, _lines
from .campaign_pro_v4 import _tight_product_photo, _side_elevation
from .editable_export import Scene
from .render import compute_roi


def _box(scene, layout, zone):
    item = layout[zone]
    return (
        item["x"] * scene.w / 1000,
        item["y"] * scene.h / 1000,
        item["w"] * scene.w / 1000,
        item["h"] * scene.h / 1000,
    )


def _copy(scene, group, text, rect, *, size=25, minimum=13,
          color="#161B24", bold=True, ident="ai-copy", lines=2):
    x, y, w, h = rect
    scene.text(group, str(text or ""), x, y, w, h,
               size, minimum, color, bold, ident, lines)


def _header(scene, brief, logo, rect, ink, accent):
    x, y, w, h = rect
    pad = max(8, min(16, w * .024))
    logo_w = min(w * .21, max(65, h * .88)) if logo is not None else 0
    if logo is not None:
        scene.bitmap("logo", logo, x + pad, y + h * .12,
                     max(20, logo_w - pad), h * .73, "original-logo")
    tx = x + pad + (logo_w if logo is not None else 0)
    tw = max(50, w - (tx - x) - pad)
    _copy(scene, "heading", brief.get("category", ""), (tx, y + h*.03, tw, h*.19),
          size=max(16, min(24, h*.16)), color=ink, ident="ai-category", lines=1)
    _copy(scene, "heading", brief.get("model", ""), (tx, y + h*.22, tw, h*.41),
          size=max(29, min(65, h*.38)), minimum=17, color=accent,
          ident="ai-product-model", lines=2)
    _copy(scene, "heading", brief.get("slogan", ""), (tx, y + h*.68, tw, h*.28),
          size=max(16, min(25, h*.17)), minimum=12, color=ink,
          ident="ai-slogan", lines=2)


def _product(scene, hero, detail, rect):
    x, y, w, h = rect
    if hero is None:
        raise ValueError("AI-постеру требуется оригинальное фото товара.")
    # An actual alpha mask may be cropped; opaque originals are not cropped.
    # They remain byte-identical as files in the ZIP.
    scene.bitmap("photos", _tight_product_photo(hero),
                 x + w*.012, y + h*.015, w*.976, h*.965,
                 "original-product-photo")
    if detail is not None and w > 390 and h > 260:
        scene.bitmap("photos", detail, x+w*.79, y+h*.04,
                     w*.19, h*.24, "original-detail-photo")


def _specifications(scene, brief, rect, ink, accent):
    rows = _lines(brief, "specs", 8)
    if not rows:
        return
    x, y, w, h = rect
    pad=max(8,min(14,w*.025))
    title=min(35,h*.17)
    _copy(scene, "specs", "ХАРАКТЕРИСТИКИ",
          (x+pad,y+2,w-2*pad,title),size=min(23,max(15,title*.69)),
          color=accent,ident="ai-specs-heading",lines=1)
    row_h=(h-title-8)/len(rows)
    for i,(label,value) in enumerate(rows):
        sy=y+title+4+i*row_h
        _copy(scene,"specs",label,
              (x+pad,sy,w*.56-pad-4,row_h-1),
              size=min(20,max(13,row_h*.47)),minimum=11,
              color=ink,ident=f"ai-spec-label-{i}",lines=2)
        _copy(scene,"specs",value,
              (x+w*.57,sy,w*.43-pad,row_h-1),
              size=min(25,max(15,row_h*.56)),minimum=11,
              color=accent,ident=f"ai-spec-value-{i}",lines=2)


def _dimensions(scene, brief, drawing, rect, ink, accent):
    rows=_lines(brief,"dimensions",4)
    if not rows and drawing is None:
        return
    x,y,w,h=rect
    pad=max(8,min(13,w*.025))
    title=min(34,h*.21)
    _copy(scene,"dimensions","ГАБАРИТЫ",
          (x+pad,y+2,w-2*pad,title),size=min(22,max(15,title*.67)),
          color=accent,ident="ai-dimensions-heading",lines=1)
    base=y+title+5
    available=max(25,h-title-9)
    left=w*.44 if drawing is not None else 0
    if drawing is not None:
        original,_=_side_elevation(drawing)
        scene.bitmap("dimensions",original,
                     x+pad,base,left-pad*1.5,available,"original-drawing")
    if rows:
        tx=x+left+pad
        tw=w-left-pad*2
        step=available/len(rows)
        for i,(label,value) in enumerate(rows):
            _copy(scene,"dimensions",label,
                  (tx,base+i*step,tw*.48,step-2),
                  size=min(16,max(12,step*.36)),minimum=10,
                  color=ink,ident=f"ai-dim-label-{i}",lines=2)
            _copy(scene,"dimensions",value,
                  (tx+tw*.49,base+i*step,tw*.51,step-2),
                  size=min(23,max(14,step*.48)),minimum=11,
                  color=accent,ident=f"ai-dim-value-{i}",lines=2)


def _benefits(scene, brief, rect, ink, accent):
    # Benefits must not silently disappear when hero_claims is absent.
    claims=[]
    seen=set()
    for item in list(brief.get("hero_claims") or [])+list(brief.get("benefits") or []):
        value=str(item).strip()
        if value and value.casefold() not in seen:
            claims.append(value)
            seen.add(value.casefold())
        if len(claims)>=4:
            break
    if not claims:
        return
    x,y,w,h=rect
    pad=max(8,min(14,w*.025))
    title=min(34,h*.21)
    _copy(scene,"benefits","ПРЕИМУЩЕСТВА",
          (x+pad,y+2,w-pad*2,title),size=min(22,max(15,title*.65)),
          color=accent,ident="ai-benefits-heading",lines=1)
    columns=2 if w<800 else 4
    rows=(len(claims)+columns-1)//columns
    cell_w=(w-2*pad)/columns
    cell_h=(h-title-6)/rows
    for i,claim in enumerate(claims):
        row,col=divmod(i,columns)
        _copy(scene,"benefits",claim,
              (x+pad+col*cell_w,y+title+4+row*cell_h,
               cell_w-7,cell_h-4),
              size=min(21,max(14,cell_h*.35)),minimum=11,
              color=ink,ident=f"ai-benefit-{i}",lines=3)


def _roi(scene, brief, rect, ink, accent):
    if not brief.get("show_roi"):
        return
    data=compute_roi(brief)
    if not data:
        return
    x,y,w,h=rect
    pad=max(8,min(13,w*.023))
    title=min(32,h*.22)
    _copy(scene,"roi","ЭКОНОМИКА",
          (x+pad,y,w-2*pad,title),size=min(22,max(14,title*.70)),
          color=accent,ident="ai-roi-heading",lines=1)
    currency=str(brief.get("currency") or "").strip()[:10]
    rows=[("ЗА РЕЙС, "+currency,data["per_trip"]),
          ("РЕЙСОВ В ГОД",data["trips"]),
          ("ЗА ГОД, "+currency,data["annual"]),
          ("БАЛАНС, "+currency,data["net"])]
    cols=2 if w<520 else 4
    cell_w=(w-2*pad)/cols
    cell_h=(h-title-6)/(4//cols)
    for i,(name,value) in enumerate(rows):
        row,col=divmod(i,cols)
        xx=x+pad+col*cell_w
        yy=y+title+4+row*cell_h
        _copy(scene,"roi",name,(xx,yy,cell_w-8,cell_h*.41),
              size=min(15,max(11,cell_h*.25)),minimum=10,
              color=ink,ident=f"ai-roi-label-{i}",lines=2)
        _copy(scene,"roi",f"{value:,.0f}".replace(","," "),
              (xx,yy+cell_h*.42,cell_w-8,cell_h*.55),
              size=min(28,max(17,cell_h*.45)),minimum=12,
              color=accent,ident=f"ai-roi-value-{i}",lines=1)


def _footer(scene, brief, rect, ink, accent):
    x,y,w,h=rect
    pad=max(9,min(18,w*.028))
    price=_format_price(brief.get("price"))
    currency=str(brief.get("currency") or "").strip()
    price=(f"{price} {currency}"+(" с НДС" if brief.get("vat",True) else "")
           if price else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    if brief.get("phones"):
        half=w*.59
        _copy(scene,"price",price,
              (x+pad,y+h*.22,half-2*pad,h*.67),
              size=min(52,max(27,h*.48)),minimum=19,
              color=accent,ident="ai-price",lines=2)
        contact_x=x+half+pad
        contact_w=w-half-2*pad
        _copy(scene,"contacts","СВЯЖИТЕСЬ С НАМИ",
              (contact_x,y+h*.09,contact_w,h*.20),
              size=min(18,max(13,h*.14)),minimum=11,
              color=ink,ident="ai-contact-heading",lines=1)
        phones=[str(p).strip() for p in (brief.get("phones") or []) if str(p).strip()][:2]
        for i,phone in enumerate(phones):
            _copy(scene,"contacts",phone,
                  (contact_x,y+h*(.34+.29*i),contact_w,h*.28),
                  size=min(26,max(16,h*.23)),minimum=12,
                  color=ink,ident=f"ai-contact-{i}",lines=1)
    else:
        _copy(scene,"price",price,(x+pad,y+h*.22,w-2*pad,h*.64),
              size=min(54,max(29,h*.45)),minimum=19,
              color=accent,ident="ai-price",lines=2)


def render_ai_full_poster_svg(brief, fmt, concept, *,
                              artwork, hero, detail=None, logo=None,
                              drawing=None):
    """No server-drawn graphic sections: only AI poster + source/data layers."""
    if artwork is None:
        raise ValueError("OpenAI не вернул полное художественное оформление.")
    validate_concept({key:value for key,value in concept.items()
                      if key not in ("id","layout_repair")})
    validate_renderability(concept,brief,fmt,has_drawing=drawing is not None)
    scene=Scene(fmt,brief.get("accent"),brief.get("style"))
    # Scene's old procedural decoration must never cover paid AI artwork.
    scene.groups["decor"].clear()
    if not isinstance(artwork,Image.Image):
        raise ValueError("Неверный формат AI-макета.")
    final=ImageOps.fit(artwork.convert("RGB"),(scene.w,scene.h),
                       method=Image.Resampling.LANCZOS)
    scene.bitmap("background",final,0,0,scene.w,scene.h,
                 "ai-complete-poster-artwork")
    layout=concept["layouts"][fmt]
    colors=concept["palette"]
    ink=colors["foreground"]
    accent=colors["accent"]
    _product(scene,hero,detail,_box(scene,layout,"hero"))
    _header(scene,brief,logo,_box(scene,layout,"header"),ink,accent)
    _specifications(scene,brief,_box(scene,layout,"specs"),ink,accent)
    _dimensions(scene,brief,drawing,_box(scene,layout,"dimensions"),ink,accent)
    _benefits(scene,brief,_box(scene,layout,"benefits"),ink,accent)
    _roi(scene,brief,_box(scene,layout,"roi"),ink,accent)
    _footer(scene,brief,_box(scene,layout,"footer"),ink,accent)
    return scene.export()
