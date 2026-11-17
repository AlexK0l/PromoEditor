"""Premium source-driven 4:3 advertising composition for the PRO style.

The validated brief supplies every factual claim and numeric value. Source
product photography, drawing and logo remain separate replaceable SVG images.
A real background must be uploaded or explicitly generated through the paid
OpenAI workflow; this module never embeds a pre-rendered sample poster.
"""
from __future__ import annotations
import math

from . import campaign_pro_v3 as v3
from .campaign_pro_v4 import _hero_four, _specs_four, _dims_four, _benefits_four
from .campaign_pro import _tint
from .campaign_layout import _check, _rule, _lines, _photo
from .editable_export import Scene
from .render import compute_roi

INK = "#151923"


def _trust_and_finance(scene,brief,proof,x,y,w,h,accent):
    """Keep verified claims distinct from four large ROI figures."""
    roi=compute_roi(brief) if brief.get("show_roi") else None
    if not proof and roi is None:return
    scene.rect("benefits",x,y,w,h,"#FFFFFF",ident="pro4-claims-finance-band")
    long_copy=bool(proof and max(map(len,proof))>34)
    share=1.0 if roi is None else (.50 if long_copy else .43)
    if proof:
        claims_width=w*share
        slug_w=min(245,claims_width*.45)
        heading=("ПОДТВЕРЖДЕНО" if brief.get("proof_points")
                 else "КЛЮЧЕВЫЕ ТЕЗИСЫ")
        v3._slug(scene,"benefits",heading,x+6,y+5,slug_w,h-10,
                 accent,"pro4-trust-title",23)
        px0=x+slug_w+28
        claim_w=claims_width-slug_w-39
        columns=2 if long_copy else 1
        rows=math.ceil(len(proof)/columns)
        cw=claim_w/columns
        rh=(h-12)/max(1,rows)
        for i,claim in enumerate(proof):
            px=px0+(i%columns)*cw
            py=y+6+(i//columns)*rh
            center=py+rh*.5
            scene.el("benefits","circle",f"pro4-proof-ring-{i}",{
                "cx":px+13,"cy":center,"r":10,
                "fill":"none","stroke":accent,"stroke-width":2})
            _check(scene,"benefits",px+7,center-7,13,accent,
                   f"pro4-proof-check-{i}")
            v3._type(scene,"benefits",claim,px+33,py+2,cw-38,rh-3,
                     22 if rows<=3 else 19,10,INK,True,
                     f"pro4-proof-statement-{i}",3)
    if roi:
        money=str(brief.get("currency") or "Br").strip()[:10] or "Br"
        names=[("ЗА РЕЙС",roi["per_trip"]),
               ("РЕЙСОВ В ГОД",roi["trips"]),
               ("ЗА ГОД",roi["annual"]),
               ("БАЛАНС",roi["net"])]
        rx=x+w*share+6 if proof else x+5
        rw=w-(rx-x)-10
        scene.rect("roi",rx,y+5,rw,h-10,"#FFF3F4",
                   rad=7,ident="pro4-economy-card")
        cw=rw/4
        for i,(name,value) in enumerate(names):
            px=rx+i*cw
            if i:
                _rule(scene,"roi",px,y+11,px,y+h-11,
                      "#DE9FA9",1.7,f"pro4-eco-divider-{i}")
            label=name+(f", {money}" if i!=1 else "")
            v3._type(scene,"roi",label,px+10,y+11,cw-20,h*.29,
                     19,11,"#592C33",True,f"pro-roi-label-{i}",1)
            node=v3._type(scene,"roi",f"{value:,.0f}".replace(","," "),
                     px+11,y+h*.41,cw-21,h*.54,
                     49 if cw>195 else 40,17,accent,True,
                     f"pro-roi-value-{i}",1)
            if node is not None:
                # All four metrics share the same typographic baseline, even
                # if a longer amount needs a 1px smaller fitted font.
                node.set("y",str(round(y+h*.41+48,2)))


def _premium_footer(scene,brief,accent):
    """Large, legible contact and price ribbons instead of a tiny footer."""
    from .campaign_layout import _format_price
    y=951
    h=129
    scene.rect("cta_bg",0,y,1440,h,"#FFFFFF",ident="pro-cta")
    scene.polygon("cta_bg",[(0,y+7),(724,y+7),(676,y+121),(0,y+121)],
                  "url(#pro-red-gradient)",ident="pro7-price-ribbon")
    scene.polygon("cta_bg",[(740,y+7),(1440,y+7),
                            (1409,y+121),(702,y+121)],
                  accent,ident="pro7-contact-ribbon")
    scene.polygon("cta_bg",[(714,y+7),(737,y+7),(702,y+121),(681,y+121)],
                  "#FFFFFF",ident="pro7-footer-divider")
    for i in range(3):
        xx=1320+i*43
        scene.polygon("cta_bg",[(xx,y+7),(xx+17,y+7),
                                (xx-42,y+121),(xx-59,y+121)],
                      "#FFFFFF",opacity=".11",
                      ident=f"pro7-cta-chevron-{i}")
    for i,dx in enumerate((0,24)):
        scene.el("cta_bg","ellipse",f"pro7-price-coin-{i}",{
            "cx":46+dx,"cy":y+66-i*16,"rx":18,"ry":8,
            "fill":"none","stroke":"#FFFFFF","stroke-width":3})
        _rule(scene,"cta_bg",28+dx,y+66-i*16,
              28+dx,y+80-i*16,"#FFFFFF",2,f"pro7-coin-left-{i}")
        _rule(scene,"cta_bg",64+dx,y+66-i*16,
              64+dx,y+80-i*16,"#FFFFFF",2,f"pro7-coin-right-{i}")
    price=_format_price(brief.get("price"))
    unit=str(brief.get("currency") or "Br").strip()
    full_price=(f"{price} {unit}"+(" с НДС" if brief.get("vat",True) else "")
                if price else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ")
    v3._type(scene,"price",full_price,105,y+21,580,92,
             69 if price else 39,25,"#FFFFFF",True,
             "pro-price",1,italic=True)
    phones=[str(p).strip() for p in (brief.get("phones") or [])[:2]
            if str(p).strip()]
    if phones:
        scene.el("contacts","path","pro7-phone-icon",{
            "d":(f"M 772 {y+63} q -14 -16 -6 -27 l 10 -9 l 15 18 "
                 f"l -6 10 q 11 18 25 26 l 10 -7 l 15 18 l -12 11 "
                 f"q -13 8 -51 -27"),
            "fill":"none","stroke":"#FFFFFF","stroke-width":5,
            "stroke-linecap":"round","stroke-linejoin":"round",
            "transform":"translate(-17,0)"})
        v3._type(scene,"contacts","СВЯЖИТЕСЬ С НАМИ",
                 839,y+24,217,82,30,17,"#FFFFFF",True,
                 "pro7-contact-title",2,italic=True)
        _rule(scene,"contacts",1070,y+23,1070,y+100,
              "#FFFFFF",2.2,"pro7-contact-divider")
        for i,p in enumerate(phones):
            v3._type(scene,"contacts",p,1090,y+24+i*42,
                     315,39,29,16,"#FFFFFF",True,
                     f"pro7-phone-{i}",1)


def create_pro_campaign_svg(brief,key,hero=None,detail=None,logo=None,
                            drawing=None,backdrop=None,ai_product=False):
    """Poster-first 4:3 layout with true source assets and editable SVG."""
    if key not in ("4x3","9x16"):
        raise ValueError("Неизвестное соотношение сторон.")
    if key=="9x16":
        # The distinct portrait geometry remains independently regression-tested.
        return v3.create_pro_campaign_svg(
            brief,key,hero=hero,detail=detail,logo=logo,drawing=drawing,
            backdrop=backdrop,ai_product=ai_product)
    scene=Scene(key,brief.get("accent"),"industrial")
    accent=scene.accent
    _tint(scene,accent)
    scene.rect("decor",0,0,scene.w,scene.h,"#FCFCFD",ident="pro4-paper")
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
    start=171
    benefits_y=712 if benefits else None
    finance_y=835 if has_trust else None
    foot_y=951
    body_end=(benefits_y-8 if benefits else
              finance_y-8 if has_trust else foot_y-10)
    hero_w=944 if specs else scene.w
    if has_dim:
        dim_h=211 if benefits else 229
        dim_y=body_end-dim_h
        photo_h=dim_y-start
    else:
        dim_h=0
        dim_y=None
        photo_h=body_end-start
    _hero_four(scene,brief,hero,backdrop,ai_product,
               0,start,hero_w,photo_h,accent)
    if detail is not None and drawing is not None:
        # Keep the user's second product angle as a small, independently
        # replaceable photograph; never squeeze the technical drawing for it.
        inset_x=18
        inset_y=start+photo_h-111
        scene.rect("photos",inset_x,inset_y,160,103,"#FFFFFF",
                   rad=6,ident="pro7-secondary-frame")
        _photo(scene,detail,inset_x+5,inset_y+4,150,92,
               "detail-photo",layer="photos",trim=True)
        scene.rect("photos",inset_x+6,inset_y+98,147,4,
                   accent,ident="pro7-secondary-underline")
    if specs:
        spec_h=min(470,body_end-start-4)
        _specs_four(scene,specs,952,171,488,spec_h,accent)
    if has_dim:
        _dims_four(scene,brief,detail,drawing,hero,0,dim_y,
                   hero_w,dim_h,accent)
    if benefits:
        bh=(finance_y-benefits_y-8) if has_trust else (foot_y-benefits_y-9)
        _benefits_four(scene,benefits,0,benefits_y,1440,bh,accent)
    if has_trust:
        _trust_and_finance(scene,brief,proof,0,finance_y,1440,
                           foot_y-finance_y-5,accent)
    _premium_footer(scene,brief,accent)
    return scene.export()
