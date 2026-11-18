"""Editable SVG compositor driven by a validated OpenAI layout specification.

OpenAI determines geometries, palette and art direction; all Russian copy,
numeric specifications and contact details come solely from the approved brief.
No generated poster raster is used as a false 'editable' SVG.
"""
from __future__ import annotations

from .ai_layout import validate_concept, validate_renderability, ZONES
from .editable_export import Scene
from .campaign_layout import _lines, _photo
from .campaign_pro_v4 import _tight_product_photo, _side_elevation
from .render import compute_roi
from .ai_art_direction import (direction_of,direction_mark,hero_stage,
                               hero_frame,panel_detail)


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


def _dark_accent(hex_color):
    """Use a darker version of the concept's own accent, never fixed red."""
    return "#" + "".join(
        f"{round(int(hex_color[i:i+2],16)*.35):02X}" for i in (1,3,5))


def _luminance(hex_color):
    channels=[int(hex_color[index:index+2],16)/255 for index in (1,3,5)]
    linear=[channel/12.92 if channel<=.04045
            else ((channel+.055)/1.055)**2.4 for channel in channels]
    return sum(channel*weight for channel,weight in
               zip(linear,(.2126,.7152,.0722)))


def _contrast_ratio(one, two):
    light, dark=sorted((_luminance(one),_luminance(two)),reverse=True)
    return (light+.05)/(dark+.05)


def _readable_panel_ink(preferred):
    """Use the AI foreground only if readable on ALL fixed light surfaces.

    The model chooses a palette but the renderer ALWAYS draws the header,
    alternating spec rows, benefits and ROI on near-white panels. A white
    'foreground' on these panels made real customer specs disappear.
    """
    surfaces=("#FFFFFF","#F9FAFC","#F3F5F7","#F3F5F8","#FFF3F4")
    if all(_contrast_ratio(preferred,panel)>=4.5 for panel in surfaces):
        return preferred
    return "#172235"


def _contrast_text(hex_color):
    """Keep AI-authored pale accents readable behind price text."""
    rgb=[int(hex_color[i:i+2],16)/255 for i in (1,3,5)]
    linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
            for c in rgb]
    light=sum(c*weight for c,weight in zip(
        linear,(.2126,.7152,.0722)))
    return "#172235" if light>.183 else "#FFFFFF"


def _header(scene, brief, logo, rect, colors, system='sales'):
    x,y,w,h=rect
    accent, ink=colors["accent"], colors["foreground"]
    paper="#1A3044" if system=="engineering" else (
        "#FCFBF8" if system=="editorial" else "#F9FAFC")
    _panel(scene,"heading",x,y,w,h,"header",paper,0)
    if system=="engineering":
        scene.rect("heading",x,y,w,5,accent,ident="ai-header-line")
        scene.rect("heading",x,y+h-4,w,4,accent,
                   ident="ai-engineering-header-base")
        ink="#FFFFFF"
        model_color="#FFFFFF"
    elif system=="editorial":
        scene.rect("heading",x,y,w,3,accent,ident="ai-header-line")
        scene.rect("heading",x+15,y+h-7,max(5,w*.18),2,accent,
                   ident="ai-editorial-header-hairline")
        model_color=ink
    else:
        scene.rect("heading",x,y,w,max(9,h*.09),accent,
                   ident="ai-header-line")
        model_color=accent
    logo_w=min(w*.19, max(100,h*1.2))
    if logo is not None:
        scene.bitmap("logo",logo,x+11,y+16,logo_w-19,h-29,"original-logo")
    else:
        scene.text("logo",str(brief.get("brand") or "ПРОМО").upper(),x+10,y+25,
                   logo_w-14,h-30,max(20,min(39,h*.32)),13,
                   "#FFFFFF" if system=="engineering" else accent,
                   True,"ai-brand",2)
    left=x+logo_w+14
    _heading(scene,"heading",str(brief.get("category") or "").upper(),
             left,y+12,w-logo_w-28,h*.22,ink,29)
    scene.text("heading",str(brief.get("model") or ""),
               left,y+h*.32,w-logo_w-28,h*.40,
               max(31,min(64,h*.42)),20,model_color,True,"ai-product-model",2)
    slogan=str(brief.get("slogan") or "")
    if slogan:
        scene.text("heading",slogan,left,y+h*.77,w-logo_w-28,h*.22,
                   max(16,min(25,h*.19)),12,ink,True,"ai-slogan",2)


def _hero(scene, hero, detail, backdrop, rect, colors, ai_product,
          system='sales'):
    x,y,w,h=rect
    if backdrop is not None and not ai_product:
        _panel(scene,"photos",x,y,w,h,"hero","#EAF0F4")
        _photo(scene,backdrop,x,y,w,h,"ai-scene",layer="photos",cover=True)
    else:
        hero_stage(scene,rect,colors,system)
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
    hero_frame(scene,rect,colors,system)
    if system=="sales":
        scene.rect("photos",x,y+h-5,w,5,colors["accent"],
                   ident="ai-hero-underline")


def _hero_claims(scene, brief, rect, colors, system='sales'):
    """Preserve user-written sales claims in addition to benefit cards.

    Avoid repeating claims when only hero_claims are supplied: the benefits
    block already uses them as its fallback. Never invent marketing copy.
    """
    benefits={str(item).strip().casefold()
              for item in (brief.get("benefits") or []) if str(item).strip()}
    if not benefits:
        return
    messages=[]
    seen=set()
    for item in (brief.get("hero_claims") or [])[:4]:
        claim=str(item).strip()
        canonical=claim.casefold()
        if claim and canonical not in benefits and canonical not in seen:
            messages.append(claim)
            seen.add(canonical)
    if not messages:
        return

    x,y,w,h=rect
    columns=2 if len(messages)>1 else 1
    rows=(len(messages)+columns-1)//columns
    band_h=min(h*.37,max(80,36+43*rows))
    top=y+h-band_h-9
    background=("#1E3246" if system=="engineering" else
                "#FCFAF5" if system=="editorial" else
                _dark_accent(colors["accent"]))
    claim_ink="#172235" if system=="editorial" else "#FFFFFF"
    scene.rect("claims",x+7,top,w-14,band_h,
               background,rad=6 if system=="editorial" else 8,
               opacity=".96",ident="ai-hero-claims-panel")
    scene.rect("claims",x+7,top,6,band_h,colors["accent"],
               ident="ai-hero-claims-rail")
    scene.text("claims","КЛЮЧЕВЫЕ ТЕЗИСЫ",
               x+21,top+4,w-42,24,17,11,claim_ink,
               True,"ai-hero-claims-heading",1)
    left=x+19
    upper=top+32
    cw=(w-38)/columns
    ch=(band_h-36)/rows
    for i,claim in enumerate(messages):
        col,row=i%columns,i//columns
        cx=left+col*cw
        cy=upper+row*ch
        scene.el("claims","circle",f"ai-hero-claim-dot-{i}",{
            "cx":cx+6,"cy":cy+max(9,ch*.33),
            "r":3.6,"fill":colors["accent"],
        })
        scene.text("claims",claim,cx+17,cy+1,
                   cw-25,max(16,ch-2),
                   max(13,min(18,ch*.46)),10,
                   claim_ink,True,f"ai-hero-claim-{i}",3)



def _section_banner(scene, section, text, rect, colors, system, font):
    """Three different section treatments, never white text on pale colors."""
    x,y,w,band=rect
    a,ink=colors["accent"],colors["foreground"]
    fill="#1D3449" if system=="engineering" else (
        "#FDFCFA" if system=="editorial" else a)
    foreground=("#FFFFFF" if system=="engineering" else ink if
                system=="editorial" else _contrast_text(a))
    scene.rect(section,x,y,w,band,fill,ident=f"ai-{section}-ribbon")
    if system=="engineering":
        scene.rect(section,x,y,w,3,a,ident=f"ai-blueprint-{section}-rail")
    if system=="editorial":
        scene.rect(section,x,y+band-3,w,3,a,
                   ident=f"ai-editorial-{section}-underline")
    _heading(scene,section,text,x+12,y+3,w-24,band-4,foreground,font)


def _specs(scene, brief, rect, colors, system="sales"):
    rows=_lines(brief,"specs",8)
    if not rows:return
    x,y,w,h=rect
    a,ink=colors["accent"],colors["foreground"]
    _panel(scene,"specs",x,y,w,h,"specs")
    band=min(40,h*.17)
    _section_banner(scene,"specs","ХАРАКТЕРИСТИКИ",
                    (x,y,w,band),colors,system,max(17,min(25,w*.045)))
    gap=3
    row_h=(h-band-12-gap*(len(rows)-1))/len(rows)
    if row_h<28:raise ValueError("AI выделил слишком мало места для характеристик.")
    for i,(name,value) in enumerate(rows):
        sy=y+band+7+i*(row_h+gap)
        shade=("#FFFFFF" if system=="editorial" else
               "#EEF2F5" if system=="engineering" and i%2==0 else
               "#F3F5F7" if i%2==0 else "#FFFFFF")
        scene.rect("specs",x+5,sy,w-10,row_h,shade,rad=3,
                   ident=f"ai-spec-row-{i}")
        if system=="editorial":
            scene.rect("specs",x+12,sy+row_h-2,max(2,w-24),1,
                       "#D8DAD7",ident=f"ai-editorial-spec-rule-{i}")
        else:
            scene.rect("specs",x+5,sy,5,row_h,a,ident=f"ai-spec-edge-{i}")
        label_w=w*.58
        scene.text("specs",name,x+15,sy+2,label_w-21,row_h-4,
                   max(14,min(21,row_h*.44)),11,ink,True,
                   f"ai-spec-name-{i}",2)
        value_ink=(a if system!="editorial"
                   and _contrast_ratio(a,shade)>=4.5 else ink)
        scene.text("specs",value,x+label_w,sy+2,w-label_w-13,row_h-4,
                   max(16,min(26,row_h*.52)),11,value_ink,True,
                   f"ai-spec-value-{i}",2)
    panel_detail(scene,"specs",rect,system,a)


def _dimensions(scene, brief, drawing, rect, colors, system="sales"):
    sizes=_lines(brief,"dimensions",4)
    if not sizes and drawing is None:return
    x,y,w,h=rect
    a,ink=colors["accent"],colors["foreground"]
    _panel(scene,"dimensions",x,y,w,h,"dimensions")
    band=min(39,h*.24)
    _section_banner(scene,"dimensions","ГАБАРИТЫ И ЧЕРТЁЖ",
                    (x,y,w,band),colors,system,
                    max(17,min(26,band*.66)))
    inside_y=y+band+5
    inside_h=h-band-12
    if inside_h<28:raise ValueError("AI выделил мало места для инженерной схемы.")
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
            sx=x+w-fact_w+3;sy=inside_y+i*cell_h
            scene.rect("dimensions",sx,sy,fact_w-8,max(4,cell_h-3),
                       "#F3F5F8",ident=f"ai-dim-cell-{i}")
            scene.text("dimensions",name.upper(),sx+8,sy+1,fact_w*.48-10,
                       cell_h-4,max(12,min(17,cell_h*.37)),10,ink,True,
                       f"ai-dim-name-{i}",2)
            value_ink=a if system!="editorial" and (
                _contrast_ratio(a,"#F3F5F8")>=4.5) else ink
            scene.text("dimensions",value,sx+fact_w*.49,sy+1,
                       fact_w*.48-5,cell_h-4,max(15,min(24,cell_h*.47)),
                       11,value_ink,True,f"ai-dim-value-{i}",2)
    panel_detail(scene,"dimensions",rect,system,a)


def _benefits(scene, brief, rect, colors, system="sales"):
    claims=[str(t).strip() for t in
            ((brief.get("benefits") or []) or (brief.get("hero_claims") or []))
            if str(t).strip()][:4]
    proofs=[str(t).strip() for t in (brief.get("proof_points") or [])
            if str(t).strip()][:3]
    if not claims and not proofs:return
    x,y,w,h=rect
    a,ink=colors["accent"],colors["foreground"]
    _panel(scene,"benefits",x,y,w,h,"benefits")
    band=min(37,h*.21)
    _section_banner(scene,"benefits","ПРЕИМУЩЕСТВА",
                    (x,y,w,band),colors,system,
                    max(17,min(26,band*.65)))
    area_y=y+band+5
    proof_h=min(h*.30,48) if proofs else 0
    area_h=h-band-10-proof_h
    if claims:
        columns=4 if w>=900 else 2
        rows=(len(claims)+columns-1)//columns
        cw=(w-16)/columns
        ch=area_h/max(1,rows)
        for i,claim in enumerate(claims):
            cx=x+8+(i%columns)*cw
            cy=area_y+(i//columns)*ch
            if system=="engineering":
                scene.el("benefits","rect",f"ai-benefit-icon-{i}",{
                    "x":cx+7,"y":cy+min(14,ch*.36),
                    "width":17,"height":17,"fill":"none",
                    "stroke":a,"stroke-width":2.5})
            else:
                scene.el("benefits","circle",f"ai-benefit-icon-{i}",{
                    "cx":cx+16,"cy":cy+min(22,ch*.40),
                    "r":4 if system=="editorial" else 10,
                    "fill":a if system=="editorial" else "none",
                    "stroke":a,
                    "stroke-width":2 if system=="editorial" else 3})
            scene.text("benefits",claim,cx+34,cy+2,cw-39,max(15,ch-5),
                       max(16,min(22,ch*.32)),11,ink,True,
                       f"ai-benefit-text-{i}",3)
    if proofs:
        message="  •  ".join(proofs)
        value_ink=a if _contrast_ratio(a,"#FFFFFF")>=4.5 else ink
        scene.text("benefits",message,x+14,y+h-proof_h-3,w-28,max(17,proof_h),
                   17,10,value_ink,True,"ai-verified-proof",2)
    panel_detail(scene,"benefits",rect,system,a)


def _economy(scene, brief, rect, colors, system="sales"):
    if not brief.get("show_roi"):return
    data=compute_roi(brief)
    if not data:return
    x,y,w,h=rect
    a,ink=colors["accent"],colors["foreground"]
    background=("#1A3248" if system=="engineering" else
                "#F8F7F3" if system=="editorial" else "#FFF3F4")
    text_ink="#FFFFFF" if system=="engineering" else ink
    value_ink=("#FFFFFF" if system=="engineering" else
               a if system!="editorial" and
               _contrast_ratio(a,background)>=4.5 else ink)
    _panel(scene,"roi",x,y,w,h,"roi",background)
    if system=="engineering":
        scene.rect("roi",x,y,5,h,a,ident="ai-engineering-roi-spine")
    band=min(32,h*.23)
    _heading(scene,"roi","ЭКОНОМИКА",x+12,y+4,w-24,band,
             text_ink if system=="engineering" else value_ink,22)
    unit=str(brief.get("currency") or "Br")[:9]
    pairs=[("ЗА РЕЙС, "+unit,data["per_trip"]),
           ("РЕЙСОВ В ГОД",data["trips"]),
           ("ЗА ГОД, "+unit,data["annual"]),
           ("БАЛАНС, "+unit,data["net"])]
    columns=2 if w<520 else 4
    rows=4//columns
    cw=(w-12)/columns
    ch=(h-band-10)/rows
    for i,(name,value) in enumerate(pairs):
        col,row=i%columns,i//columns
        bx=x+6+col*cw
        by=y+band+5+row*ch
        separator="#597084" if system=="engineering" else "#DAD8D4"
        if col:
            scene.rect("roi",bx,by+3,1.5,ch-6,separator,
                       ident=f"ai-roi-divider-{i}")
        if row and col==0:
            scene.rect("roi",x+11,by-1,w-22,1.5,separator,
                       ident="ai-roi-horizontal-rule")
        scene.text("roi",name,bx+7,by+2,cw-14,ch*.34,
                   max(12,min(18,cw*.093)),10,text_ink,True,
                   f"ai-roi-name-{i}",2)
        scene.text("roi",f"{value:,.0f}".replace(","," "),
                   bx+7,by+ch*.38,cw-14,ch*.55,
                   max(20,min(42,cw*.185)),14,value_ink,True,
                   f"ai-roi-value-{i}",1)
    panel_detail(scene,"roi",rect,system,a)


def _footer(scene, brief, rect, colors):
    x,y,w,h=rect
    accent=colors["accent"]
    split=w*.58
    scene.polygon("cta_bg",[(x,y),(x+split+20,y),
                             (x+split-30,y+h),(x,y+h)],
                  accent,ident="ai-cta-price")
    scene.polygon("cta_bg",[(x+split+28,y),(x+w,y),
                             (x+w,y+h),(x+split-18,y+h)],
                  _dark_accent(accent),ident="ai-cta-contacts")
    from .campaign_layout import _format_price
    cost=_format_price(brief.get("price"))
    currency=str(brief.get("currency") or "Br")
    text=(cost+" "+currency+(" с НДС" if brief.get("vat",True) else "")
          if cost else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    scene.text("price",text,x+18,y+h*.24,split-35,h*.55,
               max(29,min(56,split*.09)),19,
               _contrast_text(accent),True,"ai-price",2)
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
    validate_concept({k:v for k,v in concept.items()
                      if k not in ("id","layout_repair")})
    if key not in ("4x3", "9x16"):
        raise ValueError("Неизвестный формат.")
    validate_renderability(concept, brief, key, has_drawing=drawing is not None)
    scene=Scene(key,brief.get("accent"),"industrial")
    palette=concept["palette"]
    colors={
        "background":palette["background"],
        "foreground":_readable_panel_ink(palette["foreground"]),
        "accent":palette["accent"],
    }
    scene.rect("background",0,0,scene.w,scene.h,colors["background"],
               ident="ai-art-directed-paper")
    layout=concept["layouts"][key]
    # Layout geometry is entirely AI-authored and passed through validation.
    _header(scene,brief,logo,_rect(layout,"header",scene),colors)
    _hero(scene,hero,detail,backdrop,_rect(layout,"hero",scene),colors,ai_product)
    _hero_claims(scene,brief,_rect(layout,"hero",scene),colors)
    _specs(scene,brief,_rect(layout,"specs",scene),colors)
    _dimensions(scene,brief,drawing,_rect(layout,"dimensions",scene),colors)
    _benefits(scene,brief,_rect(layout,"benefits",scene),colors)
    _economy(scene,brief,_rect(layout,"roi",scene),colors)
    _footer(scene,brief,_rect(layout,"footer",scene),colors)
    return scene.export()
