"""Editable SVG compositor driven by a validated OpenAI layout specification.

OpenAI determines geometries, palette and art direction; all Russian copy,
numeric specifications and contact details come solely from the approved brief.
No generated poster raster is used as a false 'editable' SVG.
"""
from __future__ import annotations

from .ai_layout import validate_concept, ZONES
from .editable_export import Scene
from .campaign_layout import _lines, _photo
from .campaign_pro_v4 import _tight_product_photo, _side_elevation
from .render import compute_roi


def _rect(layout, name, canvas):
    area = layout[name]
    width, height = canvas.w, canvas.h
    return (area["x"] * width / 1000, area["y"] * height / 1000,
            area["w"] * width / 1000, area["h"] * height / 1000)


def _panel(scene, layer, x, y, w, h, name, color="#FFFFFF", roundness=6):
    scene.rect(layer, x, y, w, h, color, rad=roundness, ident=f"ai-{name}-panel")


def _heading(scene, layer, text, x, y, w, h, color, large=24):
    if text:
        scene.text(layer, text, x, y, w, h, large,
                   12, color, True, f"ai-{layer}-heading", 2)


def _header(scene, brief, logo, rect, colors):
    x,y,w,h=rect
    accent, ink=colors["accent"], colors["foreground"]
    _panel(scene,"heading",x,y,w,h,"header","#F9FAFC",0)
    scene.rect("heading",x,y,w,max(9,h*.09),accent,ident="ai-header-line")
    logo_w=min(w*.19, max(100,h*1.2))
    if logo is not None:
        scene.bitmap("logo",logo,x+11,y+16,logo_w-19,h-29,"original-logo")
    else:
        scene.text("logo",str(brief.get("brand") or "ПРОМО").upper(),x+10,y+25,
                   logo_w-14,h-30,max(20,min(39,h*.32)),13,accent,
                   True,"ai-brand",2)
    left=x+logo_w+14
    _heading(scene,"heading",str(brief.get("category") or "").upper(),
             left,y+12,w-logo_w-28,h*.22,ink,29)
    scene.text("heading",str(brief.get("model") or ""),
               left,y+h*.32,w-logo_w-28,h*.40,
               max(31,min(64,h*.42)),20,accent,True,"ai-product-model",2)
    slogan=str(brief.get("slogan") or "")
    if slogan:
        scene.text("heading",slogan,left,y+h*.77,w-logo_w-28,h*.22,
                   max(16,min(25,h*.19)),12,ink,True,"ai-slogan",2)


def _hero(scene, hero, detail, backdrop, rect, colors, ai_product):
    x,y,w,h=rect
    _panel(scene,"photos",x,y,w,h,"hero","#EAF0F4")
    if backdrop is not None and not ai_product:
        item=_photo(scene,backdrop,x,y,w,h,"ai-scene",layer="photos",cover=True)
    else:
        scene.polygon("photos",[(x,y+h*.72),(x+w,y+h*.59),(x+w,y+h),
                               (x,y+h)],"#DAE1E8",ident="ai-ground-plane")
        scene.polygon("photos",[(x,y),(x+w*.32,y),(x+w*.10,y+h)],
                      "#F5F7FA",ident="ai-light-beam")
    source=hero
    if source is not None:
        product=source if ai_product else _tight_product_photo(source)
        _photo(scene,product,x+w*.015,y+h*.02,w*.97,h*.94,
               "ai-product-bitmap" if ai_product else "original-product-photo")
        if ai_product:
            scene.text("claims","AI-ВИЗУАЛИЗАЦИЯ",x+15,y+h*.88,w*.45,h*.08,
                       19,12,"#B11D2E",True,"ai-visual-disclosure",1)
    else:
        scene.text("photos","ФОТО ТОВАРА",x+w*.20,y+h*.38,w*.60,h*.22,
                   35,18,"#8995A6",True,"ai-photo-placeholder",1)
    if detail is not None and h >= 160 and w >= 340:
        dx=x+11
        dy=y+h*.73
        iw=min(w*.25,160)
        ih=min(h*.24,110)
        scene.rect("photos",dx-3,dy-3,iw+6,ih+6,"#FFFFFF",
                   rad=6,ident="ai-detail-frame")
        _photo(scene,detail,dx,dy,iw,ih,"detail-photo",layer="photos",trim=True)
    scene.rect("photos",x,y+h-5,w,5,colors["accent"],ident="ai-hero-underline")


def _specs(scene, brief, rect, colors):
    rows=_lines(brief,"specs",8)
    if not rows:return
    x,y,w,h=rect
    _panel(scene,"specs",x,y,w,h,"specs")
    accent, ink=colors["accent"],colors["foreground"]
    title_h=min(40,h*.17)
    scene.rect("specs",x,y,w,title_h,accent,ident="ai-specs-ribbon")
    _heading(scene,"specs","ХАРАКТЕРИСТИКИ",x+12,y+4,w-24,title_h-5,
             "#FFFFFF",max(17,min(25,w*.045)))
    gap=3
    row_h=(h-title_h-12-gap*(len(rows)-1))/len(rows)
    if row_h < 28:raise ValueError("AI выделил слишком мало места для характеристик.")
    for i,(name,value) in enumerate(rows):
        sy=y+title_h+7+i*(row_h+gap)
        scene.rect("specs",x+5,sy,w-10,row_h,
                   "#F3F5F7" if i%2==0 else "#FFFFFF",
                   rad=3,ident=f"ai-spec-row-{i}")
        scene.rect("specs",x+5,sy,5,row_h,accent,ident=f"ai-spec-edge-{i}")
        label_w=w*.58
        scene.text("specs",name,x+15,sy+2,label_w-21,row_h-4,
                   max(14,min(21,row_h*.44)),11,ink,True,
                   f"ai-spec-name-{i}",2)
        scene.text("specs",value,x+label_w,sy+2,w-label_w-13,row_h-4,
                   max(16,min(26,row_h*.52)),11,accent,True,
                   f"ai-spec-value-{i}",2)


def _dimensions(scene, brief, drawing, rect, colors):
    sizes=_lines(brief,"dimensions",4)
    if not sizes and drawing is None:return
    x,y,w,h=rect
    _panel(scene,"dimensions",x,y,w,h,"dimensions")
    accent, ink=colors["accent"],colors["foreground"]
    title_h=min(39,h*.24)
    scene.rect("dimensions",x,y,w,title_h,accent,ident="ai-dims-title-bar")
    _heading(scene,"dimensions","ГАБАРИТЫ И ЧЕРТЁЖ",x+12,y+3,w-24,
             title_h-4,"#FFFFFF",max(17,min(26,title_h*.66)))
    inside_y=y+title_h+5
    inside_h=h-title_h-12
    if inside_h < 28:raise ValueError("AI выделил мало места для инженерной схемы.")
    fact_w=min(w*.36,max(160,w*.30)) if sizes else 0
    drawing_w=w-fact_w-12
    if drawing is not None:
        projection,_=_side_elevation(drawing)
        _photo(scene,projection,x+7,inside_y+2,drawing_w-12,inside_h-4,
               "original-drawing",layer="dimensions")
    elif sizes:
        scene.rect("dimensions",x+7,inside_y,drawing_w-12,inside_h,
                   "#F0F3F6",ident="ai-no-drawing")
    if sizes:
        cell_h=inside_h/len(sizes)
        for i,(name,value) in enumerate(sizes):
            sx=x+w-fact_w+3; sy=inside_y+i*cell_h
            scene.rect("dimensions",sx,sy,fact_w-8,max(4,cell_h-3),
                       "#F3F5F8",ident=f"ai-dim-cell-{i}")
            scene.text("dimensions",name.upper(),sx+8,sy+1,fact_w*.48-10,
                       cell_h-4,max(12,min(17,cell_h*.37)),10,ink,True,
                       f"ai-dim-name-{i}",2)
            scene.text("dimensions",value,sx+fact_w*.49,sy+1,
                       fact_w*.48-5,cell_h-4,max(15,min(24,cell_h*.47)),
                       11,accent,True,f"ai-dim-value-{i}",2)


def _benefits(scene, brief, rect, colors):
    claims=[str(t).strip() for t in
            ((brief.get("benefits") or []) or (brief.get("hero_claims") or []))
            if str(t).strip()][:4]
    proof=[str(t).strip() for t in (brief.get("proof_points") or [])
           if str(t).strip()][:3]
    if not claims and not proof:return
    x,y,w,h=rect
    accent,ink=colors["accent"],colors["foreground"]
    _panel(scene,"benefits",x,y,w,h,"benefits")
    title_h=min(37,h*.21)
    scene.rect("benefits",x,y,w,title_h,accent,ident="ai-benefits-title-bar")
    _heading(scene,"benefits","ПРЕИМУЩЕСТВА",x+11,y+2,w-20,title_h-4,
             "#FFFFFF",max(17,min(26,title_h*.65)))
    area_y=y+title_h+5
    proof_h=min(h*.30,48) if proof else 0
    area_h=h-title_h-10-proof_h
    if claims:
        columns=4 if w>=900 else 2
        rows=(len(claims)+columns-1)//columns
        cell_w=(w-16)/columns
        cell_h=area_h/max(1,rows)
        for i,claim in enumerate(claims):
            cx=x+8+(i%columns)*cell_w
            cy=area_y+(i//columns)*cell_h
            scene.el("benefits","circle",f"ai-benefit-icon-{i}",{
                "cx":cx+16,"cy":cy+min(22,cell_h*.40),"r":10,
                "fill":"none","stroke":accent,"stroke-width":3})
            scene.text("benefits",claim,cx+34,cy+2,cell_w-39,max(15,cell_h-5),
                       max(16,min(22,cell_h*.32)),11,ink,True,
                       f"ai-benefit-text-{i}",3)
    if proof:
        msg="  •  ".join(proof)
        scene.text("benefits",msg,x+14,y+h-proof_h-3,w-28,max(17,proof_h),
                   17,10,accent,True,"ai-verified-proof",2)


def _economy(scene, brief, rect, colors):
    if not brief.get("show_roi"):return
    data=compute_roi(brief)
    if not data:return
    x,y,w,h=rect
    _panel(scene,"roi",x,y,w,h,"roi","#FFF3F4")
    accent,ink=colors["accent"],colors["foreground"]
    title_h=min(32,h*.23)
    _heading(scene,"roi","ЭКОНОМИКА",x+12,y+4,w-24,title_h,accent,22)
    unit=str(brief.get("currency") or "Br")[:9]
    pairs=[("ЗА РЕЙС, "+unit,data["per_trip"]),
           ("РЕЙСОВ В ГОД",data["trips"]),
           ("ЗА ГОД, "+unit,data["annual"]),
           ("БАЛАНС, "+unit,data["net"])]
    # Geometry is authored by AI, but the factual layout adapts to the
    # available width. Four tiny columns previously truncated portrait labels.
    columns=2 if w<520 else 4
    rows=4//columns
    cw=(w-12)/columns
    cell_h=(h-title_h-10)/rows
    for i,(name,value) in enumerate(pairs):
        column=i%columns
        row=i//columns
        bx=x+6+column*cw
        by=y+title_h+5+row*cell_h
        if column:
            scene.rect("roi",bx,by+3,1.5,cell_h-6,
                       "#E8B1B8",ident=f"ai-roi-divider-{i}")
        if row and column==0:
            scene.rect("roi",x+11,by-1,w-22,1.5,
                       "#E8B1B8",ident="ai-roi-horizontal-rule")
        scene.text("roi",name,bx+7,by+2,cw-14,cell_h*.34,
                   max(12,min(18,cw*.093)),10,ink,True,
                   f"ai-roi-name-{i}",2)
        scene.text("roi",f"{value:,.0f}".replace(","," "),
                   bx+7,by+cell_h*.38,cw-14,cell_h*.55,
                   max(20,min(42,cw*.185)),14,accent,True,
                   f"ai-roi-value-{i}",1)


def _footer(scene, brief, rect, colors):
    x,y,w,h=rect
    accent=colors["accent"]
    split=w*.58
    scene.polygon("cta_bg",[(x,y),(x+split+20,y),
                             (x+split-30,y+h),(x,y+h)],
                  accent,ident="ai-cta-price")
    scene.polygon("cta_bg",[(x+split+28,y),(x+w,y),
                             (x+w,y+h),(x+split-18,y+h)],
                  "#A31324",ident="ai-cta-contacts")
    from .campaign_layout import _format_price
    cost=_format_price(brief.get("price"))
    currency=str(brief.get("currency") or "Br")
    text=(cost+" "+currency+(" с НДС" if brief.get("vat",True) else "")
          if cost else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    scene.text("price",text,x+18,y+h*.24,split-35,h*.55,
               max(29,min(56,split*.09)),19,"#FFFFFF",True,"ai-price",2)
    phones=[str(p).strip() for p in (brief.get("phones") or []) if str(p).strip()][:2]
    if phones:
        sx=x+split+45
        scene.text("contacts","СВЯЖИТЕСЬ С НАМИ",sx,y+9,w-(sx-x)-16,h*.26,
                   max(15,min(26,h*.24)),12,"#FFFFFF",True,
                   "ai-contact-heading",2)
        for i,phone in enumerate(phones):
            scene.text("contacts",phone,sx,y+h*(.35+i*.28),
                       w-(sx-x)-16,h*.28,max(16,min(26,h*.22)),
                       12,"#FFFFFF",True,f"ai-contact-{i}",1)


def render_ai_concept_svg(brief, key, concept, *,
                          hero=None, detail=None, logo=None,
                          drawing=None, backdrop=None, ai_product=False):
    """Render the chosen AI-authored layout into separately editable SVG layers."""
    validate_concept({k:v for k,v in concept.items() if k!="id"})
    if key not in ("4x3", "9x16"):
        raise ValueError("Неизвестный формат.")
    scene=Scene(key,brief.get("accent"),"industrial")
    palette=concept["palette"]
    colors={
        "background":palette["background"],
        "foreground":palette["foreground"],
        "accent":brief.get("accent") if brief.get("accent") else palette["accent"],
    }
    scene.rect("background",0,0,scene.w,scene.h,colors["background"],
               ident="ai-art-directed-paper")
    layout=concept["layouts"][key]
    # Layout geometry is entirely AI-authored and passed through validation.
    _header(scene,brief,logo,_rect(layout,"header",scene),colors)
    _hero(scene,hero,detail,backdrop,_rect(layout,"hero",scene),colors,ai_product)
    _specs(scene,brief,_rect(layout,"specs",scene),colors)
    _dimensions(scene,brief,drawing,_rect(layout,"dimensions",scene),colors)
    _benefits(scene,brief,_rect(layout,"benefits",scene),colors)
    _economy(scene,brief,_rect(layout,"roi",scene),colors)
    _footer(scene,brief,_rect(layout,"footer",scene),colors)
    return scene.export()
