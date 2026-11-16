"""PRO v4: product-first advertising, all claims and figures from the brief.

4:3 draws an editorial layout using the supplied photos, a factual specs
column, a photo-derived illustrative contour when a real drawing is absent,
and the user's own marketing claims. 9:16 retains the validated v3 engine.
"""
from __future__ import annotations

import math

from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageChops

from . import campaign_pro_v3 as v3
from .campaign_layout import _check, _lines, _photo, _rule, _spec_symbol
from .campaign_pro import _tint, _benefit_icon
from .editable_export import Scene
from .render import compute_roi

INK = "#151923"


def _specs_four(scene, facts, x, y, w, h, accent):
    """High-contrast, fully editable fact rows; visually prioritize numbers."""
    if not facts:
        return
    gap = 4
    rh = (h-gap*(len(facts)-1))/len(facts)
    for i, (title, value) in enumerate(facts):
        by = y+i*(rh+gap)
        points=[(x+19,by),(x+w-13,by),(x+w-2,by+rh*.5),
                (x+w-13,by+rh-1),(x,by+rh-1),(x+15,by+5)]
        scene.polygon("specs",points,"#FFFFFF",ident=f"pro-spec-card-{i}")
        scene.el("specs","polygon",f"pro4-spec-outline-{i}",{
            "points":" ".join(f"{a:.1f},{b:.1f}" for a,b in points),
            "fill":"none","stroke":accent,"stroke-width":2.0
        })
        scene.polygon("specs",[(x+4,by+rh-1),(x+63,by+rh-1),
                               (x+104,by+2),(x+22,by+2)],
                      accent,ident=f"pro4-spec-flag-{i}")
        idx=v3._spec_index(title,i)
        ix=x+12
        iy=by+(rh-60)/2
        before=len(scene.groups["specs"])
        _spec_symbol(scene,ix,iy,idx,accent)
        scale=min(.86,max(.52,(rh-9)/60))
        for element in list(scene.groups["specs"])[before:]:
            element.set("transform",f"translate({ix*(1-scale):.2f} "
                        f"{iy*(1-scale):.2f}) scale({scale:.3f})")
        value_len=len(str(value))
        right=165 if value_len<=8 else (188 if value_len<=14 else 210)
        nx=x+w-right-5
        lx=x+104
        label_width=nx-lx-15
        _rule(scene,"specs",nx-11,by+8,nx-11,by+rh-10,
              "#E4E6E8",1.6,f"pro4-spec-separator-{i}")
        v3._type(scene,"specs",title,lx,by+3,label_width,rh-8,
                 29 if i<4 else 26,12,INK,True,
                 f"pro-spec-name-{i}",2)
        v3._type(scene,"specs",value,nx,by+3,right-18,rh-8,
                 43 if i<4 and value_len<=9 else (35 if value_len<=11 else 24),
                 12,accent,True,f"pro-spec-value-{i}",2)


def _hero_four(scene,brief,hero,backdrop,ai_product,x,y,w,h,accent):
    category=str(brief.get("category") or "").casefold()
    grain=any(token in category for token in ("зерн","агро","сельхоз"))
    photo_height=min(395,h*.72) if _lines(brief,"dimensions",4) else h
    v3._new_atmosphere(scene,x,y,w,photo_height,accent,grain)
    if backdrop is not None and not ai_product:
        _photo(scene,backdrop,x,y,w,photo_height,"pro-ai-background",cover=True)
        scene.rect("photos",x,y,w,photo_height,"#FFFFFF",opacity=".065",
                   ident="pro4-photo-veil")
    for j,(radius,opacity) in enumerate(((.45,.075),(.37,.10),(.29,.12))):
        scene.el("photos","ellipse",f"pro4-ground-shadow-{j}",{
            "cx":x+w*.53,"cy":y+photo_height*.87,
            "rx":w*radius,"ry":photo_height*.077,"fill":"#1D242D",
            "opacity":opacity})
    image=backdrop if ai_product else hero
    if image is not None:
        if ai_product:
            # An AI product composite already includes its environment.
            # Cover the visible photo strip without deforming the trailer.
            _photo(scene,image,x,y,w,min(395,h*.72),
                   "ai-product-bitmap",cover=True)
        else:
            # Keep the original product a separate, editable bitmap.
            # Its bounding rectangle ends above the dimensions panel.
            _photo(scene,image,x+64,y+5,w-110,min(390,h*.72),
                   "original-product-photo",trim=True)
    scene.polygon("photos",[(x,y+photo_height-9),(x+w-98,y+photo_height-9),
                            (x+w-112,y+photo_height),(x,y+photo_height)],
                  accent,ident="pro4-scene-bottom-slash")
    if ai_product:
        tag_y=y+min(395,h*.72)-35
        scene.rect("claims",x+w-248,tag_y,226,28,"#293039",
                   rad=4,ident="pro4-ai-label-back")
        v3._type(scene,"claims","AI-ВИЗУАЛИЗАЦИЯ",x+w-241,tag_y+2,
                 213,24,16,12,"#FFFFFF",True,"pro4-ai-label",1)


def _source_schematic(photo):
    """Trace source pixels only: a photo contour, NOT an engineering drawing.

    Only useful for pictures with a genuinely transparent background. The
    result is a separate replaceable raster; no geometry is synthesized.
    """
    if photo is None or not isinstance(photo,Image.Image):
        return None
    image=ImageOps.exif_transpose(photo).convert("RGBA")
    alpha=image.getchannel("A")
    if alpha.getextrema()[0]>12:
        return None
    box=alpha.point(lambda px:255 if px>25 else 0).getbbox()
    if not box:
        return None
    image=image.crop(box)
    image.thumbnail((640,300),Image.Resampling.LANCZOS)
    mask=image.getchannel("A")
    edges=ImageOps.grayscale(image).filter(ImageFilter.FIND_EDGES)
    edges=ImageEnhance.Contrast(edges).enhance(2.3)
    edges=ImageChops.multiply(edges,mask)
    lines=edges.point(lambda px:236 if px>71 else 0)
    if not lines.getbbox():
        return None
    target=Image.new("RGBA",image.size,(255,255,255,0))
    target.paste(Image.new("RGBA",image.size,(214,13,35,255)),(0,0),lines)
    return target


def _dims_four(scene,brief,detail,drawing,hero,x,y,w,h,accent):
    """Reference-like dimensions with a real detail or a labeled photo trace."""
    if not _lines(brief,"dimensions",4) and drawing is None:
        return
    sketch=None
    if detail is None and drawing is None:
        sketch=_source_schematic(hero)
    shown_detail=detail if detail is not None else sketch
    v3._dims(scene,brief,shown_detail,drawing,x,y,w,h,accent,False)
    if sketch is not None:
        v3._type(scene,"dimensions","КОНТУР ПО ФОТО",
                 x+18,y+h-31,278,22,15,10,
                 accent,True,"pro4-photo-contour-note",1)
    scene.rect("dimensions",x,y+h-5,w-13,4,accent,
               ident="pro4-dimension-bottom-guide")


def _benefits_four(scene,benefits,x,y,w,h,accent):
    if not benefits:
        return
    n=min(6,len(benefits))
    if n!=4:
        return v3._benefits(scene,benefits,x,y,w,h,accent,False)
    scene.rect("benefits",x,y,w,h,"#FFFFFF",
               ident="pro3-benefits-stage")
    v3._slug(scene,"benefits","ПРЕИМУЩЕСТВА",x+14,y+3,
             min(w*.52,665),40,accent,"pro-benefits-title",29)
    col_w=(w-28)/n
    start=y+47
    for i,caption in enumerate(benefits[:n]):
        bx=x+14+col_w*i
        if i:
            _rule(scene,"benefits",bx,start+8,bx,start+h-54,
                  accent,1.7,f"pro4-benefit-divider-{i}")
        cx=bx+49
        cy=start+39
        icon=_benefit_icon(scene,cx,cy,i,accent)
        scale=1.16
        icon.set("transform",f"translate({cx*(1-scale):.2f} "
                 f"{cy*(1-scale):.2f}) scale({scale:.3f})")
        v3._type(scene,"benefits",caption,bx+96,start+7,
                 col_w-108,h-58,25,13,INK,True,
                 f"pro-benefit-{i}",3)


def _trust_and_finance(scene,brief,proof,x,y,w,h,accent):
    """No invented proof: optional user-confirmed claims and calculated ROI."""
    roi=compute_roi(brief) if brief.get("show_roi") else None
    if not proof and roi is None:
        return
    scene.rect("benefits",x,y,w,h,"#FFFFFF",
               ident="pro4-claims-finance-band")
    full_width=bool(proof and not roi)
    if proof:
        claims_width=w if full_width else w*.65
        slug_w=min(266,claims_width*.36)
        heading=("ПОДТВЕРЖДЕНО"
                 if brief.get("proof_points") else "КЛЮЧЕВЫЕ ТЕЗИСЫ")
        v3._slug(scene,"benefits",heading,x+5,y+5,slug_w,h-10,
                 accent,"pro4-trust-title",24)
        start=x+slug_w+26
        fact_width=claims_width-slug_w-29
        columns=2 if len(proof)>1 else 1
        rows=math.ceil(len(proof)/columns)
        cw=fact_width/columns
        rh=(h-11)/rows
        for i,claim in enumerate(proof):
            px=start+(i%columns)*cw
            py=y+5+(i//columns)*rh
            center=py+rh*.5
            scene.el("benefits","circle",f"pro4-proof-ring-{i}",{
                "cx":px+12,"cy":center,"r":10,
                "fill":"none","stroke":accent,"stroke-width":2})
            _check(scene,"benefits",px+6,center-7,13,accent,
                   f"pro4-proof-check-{i}")
            v3._type(scene,"benefits",claim,px+29,py+4,
                     cw-36,rh-8,20,10,INK,True,
                     f"pro4-proof-statement-{i}",3)
    if roi:
        money=str(brief.get("currency") or "Br").strip()[:10] or "Br"
        names=[("ЗА РЕЙС",roi["per_trip"]),("РЕЙСОВ В ГОД",roi["trips"]),
               ("ЗА ГОД",roi["annual"]),("БАЛАНС",roi["net"])]
        rx=x+w*.65+8 if proof else x+4
        rw=w-(rx-x)-6
        scene.rect("roi",rx,y+4,rw,h-8,"#FFF1F2",
                   ident="pro4-economy-card")
        columns=2 if proof else 4
        rows=math.ceil(len(names)/columns)
        cw=rw/columns
        ch=(h-8)/rows
        for i,(name,value) in enumerate(names):
            px=rx+(i%columns)*cw
            py=y+4+(i//columns)*ch
            if i%columns:
                _rule(scene,"roi",px,py+5,px,py+ch-5,
                      "#DBA6B0",1.3,f"pro4-eco-divider-{i}")
            label=name+(f", {money}" if i!=1 else "")
            v3._type(scene,"roi",label,px+12,py+3,cw-17,ch*.37,
                     15,10,"#71333F",True,f"pro-roi-label-{i}",1)
            v3._type(scene,"roi",f"{value:,.0f}".replace(","," "),
                     px+12,py+ch*.39,cw-17,ch*.56,
                     28,14,accent,True,f"pro-roi-value-{i}",1)


def create_pro_campaign_svg(brief,key,hero=None,detail=None,logo=None,
                            drawing=None,backdrop=None,ai_product=False):
    if key not in ("4x3","9x16"):
        raise ValueError("Неизвестное соотношение сторон.")
    if key=="9x16":
        # Preserve the separately reviewed portrait engine in this release.
        return v3.create_pro_campaign_svg(
            brief,key,hero=hero,detail=detail,logo=logo,drawing=drawing,
            backdrop=backdrop,ai_product=ai_product)
    scene=Scene(key,brief.get("accent"),"industrial")
    accent=scene.accent
    _tint(scene,accent)
    scene.rect("decor",0,0,scene.w,scene.h,"#FCFCFD",
               ident="pro4-paper")
    specs=_lines(brief,"specs",8)
    dims=_lines(brief,"dimensions",4)
    benefits=[str(s).strip()[:150] for s in (brief.get("benefits") or [])
              if str(s).strip()][:6]
    proof=[str(s).strip()[:180] for s in (brief.get("proof_points") or [])
           if str(s).strip()][:4]
    if not proof:
        proof=[str(s).strip()[:120] for s in (brief.get("hero_claims") or [])
               if str(s).strip()][:4]
    has_dim=bool(dims or drawing is not None)
    has_trust=bool(proof or (brief.get("show_roi") and compute_roi(brief)))
    v3._header(scene,brief,logo,accent,False)
    top=171
    if has_dim:
        bottom=862 if not benefits else 729
    else:
        bottom=729 if benefits else (965 if not has_trust else 858)
    hero_w=934 if specs else scene.w
    _hero_four(scene,brief,hero,backdrop,ai_product,
               0,top,hero_w,bottom-top,accent)
    if specs:
        _specs_four(scene,specs,944,176,496,bottom-182,accent)
    if has_dim:
        _dims_four(scene,brief,detail,drawing,hero,0,bottom-163,
                   hero_w,163,accent)
    if benefits:
        _benefits_four(scene,benefits,0,734,1440,127,accent)
    if has_trust:
        _trust_and_finance(scene,brief,proof,0,866,1440,99,accent)
    v3._footer(scene,brief,accent,False)
    return scene.export()
