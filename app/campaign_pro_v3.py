"""Promo PRO v3: editorial poster composition derived from layout principles.

No source imagery, facts, logos or claims are copied from a visual reference.
A submitted product image stays an independent bitmap; every text and diagram
element is an SVG shape that CorelDRAW can edit. Standard style stays intact.
"""
from __future__ import annotations

import math

from .campaign_layout import _check, _format_price, _lines, _photo, _rule, _spec_symbol
from .campaign_pro import _tint, _benefit_icon
from .editable_export import Scene, _wrap
from .render import compute_roi

INK = "#151923"
RED = "#E31B26"
MID = "#475260"
PAPER = "#FCFCFD"


def _type(scene, layer, value, x, y, w, h, size=26, minimum=11,
          fill=INK, bold=True, ident="pro3-label", lines=2,
          italic=False, align=None):
    """Measured typesetting: complete words are preferred to truncated specs."""
    value = str(value or "").strip()
    if not value:
        return None
    width = max(12, int(w))
    height = max(12, h)
    fs = int(minimum)
    for test in range(int(size), int(minimum)-1, -1):
        blocks = _wrap(value, width, test, bold)
        if (len(blocks) <= lines
                and not any("…" in segment for segment in blocks)
                and len(blocks)*test*1.24 <= height):
            fs = test
            break
    node = scene.text(layer, value, x, y, width, height,
                      fs, fs, fill, bold, ident, lines)
    if node is not None:
        if italic:
            node.set("font-style", "italic")
        if align:
            node.set("text-anchor", align)
            # SVG <tspan> x coordinates are the anchoring reference.
            for line in list(node):
                line.set("x", str(round(x + w/2, 2)))
    return node


def _slug(scene, layer, label, x, y, w, h, accent, ident,
          size=29, invert=False):
    points = [
        (x+5, y), (x+w, y),
        (x+w-28, y+h), (x-13, y+h)
    ]
    scene.polygon(layer, points, "#FFFFFF" if invert else accent, ident=ident)
    _type(scene, layer, label, x+16, y+3, w-53, h-5,
          size, 14, accent if invert else "#FFFFFF",
          True, ident+"-text", 1, italic=True)


def _spec_index(name, row):
    word = str(name).casefold()
    if any(x in word for x in ("объём", "объем", "кузов")):
        return 0
    if any(x in word for x in ("груз", "масса", "вес", "кг")):
        return 1
    if any(x in word for x in ("тормоз", "диск")):
        return 3
    if any(x in word for x in ("оси", "ось", "колес", "колёс", "шины")):
        return 4
    return row % 7


def _new_atmosphere(scene, x, y, w, h, accent, grain=False):
    """Muted industrial graphic, explicitly an illustration (not a photo)."""
    scene.rect("photos", x, y, w, h, "#DBE2E8", ident="pro3-hero-scene")
    scene.polygon("photos", [
        (x,y+h*.24),(x+w*.16,y+h*.14),(x+w*.32,y+h*.30),
        (x+w*.54,y+h*.15),(x+w*.74,y+h*.28),(x+w,y+h*.13),
        (x+w,y+h*.70),(x,y+h*.70)
    ], "#BDC9D1", ident="pro3-horizon-distant")
    scene.polygon("photos", [
        (x,y+h*.47),(x+w*.17,y+h*.31),(x+w*.37,y+h*.46),
        (x+w*.59,y+h*.29),(x+w*.79,y+h*.39),(x+w,y+h*.31),
        (x+w,y+h*.77),(x,y+h*.77)
    ], "#AAB7C1", ident="pro3-horizon-near")
    # A few neutral terminal silhouettes establish scale, not real geography.
    if grain:
        for index in range(4):
            bx=x+w*(.72+.057*index)
            bh=h*(.23+.018*(index%2))
            scene.rect("photos",bx,y+h*.32-bh,w*.041,bh,
                       "#9AA6B0",ident=f"pro3-silo-{index}")
            scene.polygon("photos",[
                (bx,y+h*.32-bh),(bx+w*.0205,y+h*.32-bh-h*.057),
                (bx+w*.041,y+h*.32-bh)
            ],"#9AA6B0",ident=f"pro3-silo-roof-{index}")
        _rule(scene,"photos",x+w*.76,y+h*.08,
              x+w*.96,y+h*.08,"#8797A3",3,"pro3-terminal-pipe")
    else:
        # Quarry-like terraces without copying the photographed reference.
        for k in range(3):
            yy=y+h*(.35+.095*k)
            _rule(scene,"photos",x+w*.77,yy,
                  x+w*.97,yy-h*.055,"#8C9AA6",3,
                  f"pro3-industrial-bench-{k}")
    scene.polygon("photos",[
        (x,y+h*.61),(x+w,y+h*.50),(x+w,y+h),(x,y+h)
    ],"#C4CED6",ident="pro3-ground")
    for row in range(9):
        px=x+(row%3)*15
        py=y+h*(.61+row*.04)
        _rule(scene,"photos",px,py,x+w-px+x,py-h*.085,
              "#EDF1F4",2,f"pro-hero-depth-{row}")
    scene.polygon("photos",[
        (x+w*.77,y),(x+w,y),(x+w*.61,y+h)
    ], "#FFFFFF", opacity=".26",ident="pro3-sky-light")


def _header(scene, brief, logo, accent, portrait):
    w=scene.w
    h=247 if portrait else 168
    scene.rect("decor",0,0,w,h,"url(#pro-red-gradient)",
               ident="pro-header")
    # Wider brand slash, dynamic corner and two bright fins.
    for i,shift in enumerate((0,75,145)):
        scene.polygon("decor",[
            (w-336+shift,0),(w-282+shift,0),
            (w-468+shift,h),(w-522+shift,h)
        ],"#FFFFFF",opacity=(".16" if i<2 else ".99"),
        ident=f"pro3-header-chevron-{i}")
    plate_x=22 if portrait else 25
    plate_y=20
    plate_w=228 if portrait else 270
    plate_h=121 if portrait else 113
    if logo is not None:
        scene.polygon("logo",[
            (plate_x,plate_y),(plate_x+plate_w,plate_y),
            (plate_x+plate_w-33,plate_y+plate_h),
            (plate_x,plate_y+plate_h)
        ],"#FFFFFF",ident="pro3-logo-card")
        _photo(scene,logo,plate_x+12,plate_y+9,plate_w-52,
               plate_h-18,"original-logo",layer="logo",trim=True)
    elif str(brief.get("brand") or "").strip():
        _type(scene,"logo",str(brief["brand"]).upper(),
              plate_x+6,plate_y+19,plate_w-48,plate_h-28,
              40,17,"#FFFFFF",True,"pro3-brand",2)
    sx=255 if portrait else 311
    _rule(scene,"heading",sx-17,22,sx-53,131 if portrait else 127,
          "#FFFFFF",6,"pro3-header-slash")
    category=str(brief.get("category") or "").strip().upper()
    _type(scene,"heading",category,sx+2,14,w-sx-59,48,
          38 if portrait else 40,19,"#FFFFFF",
          True,"pro3-category",1,italic=True)
    _type(scene,"heading",str(brief.get("model") or "").strip(),
          sx,59,w-sx-64,89 if portrait else 87,
          88 if portrait else 98,31,
          "#FFFFFF",True,"pro3-model",1,italic=True)
    slogan=str(brief.get("slogan") or "").strip()
    if slogan:
        sy=193 if portrait else 126
        sl=215 if portrait else 275
        scene.polygon("heading",[
            (sl+13,sy),(w-35,sy),(w-64,sy+51),(sl-17,sy+51)
        ],"#FFFFFF",ident="pro3-slogan-bg")
        _type(scene,"heading",slogan,sl+20,sy+5,
              w-sl-94,41,32 if portrait else 30,16,
              accent,True,"pro3-slogan",1,italic=True)


def _hero(scene, brief, hero, detail, backdrop, ai_product,
          x, y, w, h, accent, portrait):
    category=str(brief.get("category") or "").casefold()
    grain=any(t in category for t in ("зерно","сельхоз","агро"))
    _new_atmosphere(scene,x,y,w,h,accent,grain=grain)
    if backdrop is not None and not ai_product:
        _photo(scene,backdrop,x,y,w,h,"pro-ai-background",cover=True)
        scene.rect("photos",x,y,w,h,"#FFFFFF",opacity=".06",
                   ident="pro3-backdrop-soften")
    original = backdrop if ai_product else hero
    if original is not None:
        # Product geometry comes only from the original photo or supplied AI composite.
        pad=8 if portrait else 14
        _photo(scene,original,x+pad,y+5,w-2*pad,h-19,
               "ai-product-bitmap" if ai_product else "original-product-photo",
               trim=not ai_product)
    scene.polygon("photos",[
        (x,y+h-12),(x+w-80,y+h-12),
        (x+w-96,y+h),(x,y+h)
    ], accent,ident="pro3-hero-bottom-accent")
    scene.rect("photos",x+10,y+h-14,w-20,3,
               "#FFFFFF",ident="pro3-hero-white-rule")
    if portrait and detail is not None:
        # Rear-angle photo as a separate replaceable inset, not AI-fabricated.
        inset_w=min(290,w*.31)
        inset_h=min(158,h*.35)
        ix=x+23
        iy=y+h-inset_h-26
        scene.rect("photos",ix-8,iy-8,inset_w+16,inset_h+16,
                   "#FFFFFF",rad=11,ident="pro3-portrait-detail-frame")
        _photo(scene,detail,ix,iy,inset_w,inset_h,
               "detail-photo",layer="photos",trim=True)
        scene.rect("photos",ix-8,iy+inset_h+3,
                   inset_w+16,6,accent,ident="pro3-portrait-detail-rule")
    if ai_product:
        scene.rect("claims",x+w-254,y+h-54,230,31,
                   "#222936",rad=3,ident="pro3-ai-label-bg")
        _type(scene,"claims","AI-ВИЗУАЛИЗАЦИЯ",
              x+w-245,y+h-50,214,25,16,12,
              "#FFFFFF",True,"pro3-ai-label",1)
    # No invented selling claims: use only the user's explicitly entered copy.
    if detail is None and not portrait:
        claims=[str(v).strip() for v in (brief.get("hero_claims") or [])
                if str(v).strip()][:1]
        if claims:
            _slug(scene,"claims",claims[0],x+20,y+h-66,
                  min(435,w*.49),48,accent,
                  "pro3-hero-claim",size=23,invert=True)


def _specs(scene, facts, x, y, w, h, accent, portrait):
    if not facts:
        return
    col_count=2 if portrait and len(facts)>1 else 1
    rows=math.ceil(len(facts)/col_count)
    gap=7 if portrait else 5
    cw=(w-gap*(col_count-1))/col_count
    rh=min(112 if portrait else 80,
           (h-gap*(rows-1))/rows)
    if not portrait:
        row_heights=[rh]*rows
    else:
        row_heights=[rh]*rows
    for i,(label,value) in enumerate(facts):
        row=i//col_count
        col=i%col_count
        bx=x+col*(cw+gap)
        by=y+row*(rh+gap)
        plate=83 if portrait else 95
        point=[
            (bx+19,by+1),(bx+cw-12,by+1),
            (bx+cw,by+rh/2),(bx+cw-12,by+rh-2),
            (bx,by+rh-2),(bx+11,by+7)
        ]
        scene.polygon("specs",point,"#FFFFFF",ident=f"pro-spec-card-{i}")
        scene.el("specs","polygon",f"pro3-spec-border-{i}",{
            "points":" ".join(f"{a:.1f},{b:.1f}" for a,b in point),
            "fill":"none","stroke":accent,"stroke-width":2
        })
        scene.polygon("specs",[
            (bx+4,by+rh-3),(bx+plate-22,by+rh-3),
            (bx+plate+16,by+2),(bx+23,by+2)
        ],accent,ident=f"pro3-icon-slash-{i}")
        icon_x=bx+15
        icon_y=by+(rh-60)/2
        start=len(scene.groups["specs"])
        _spec_symbol(scene,icon_x,icon_y,_spec_index(label,i),accent)
        scale=min(.86,max(.46,(rh-12)/60))
        for part in list(scene.groups["specs"])[start:]:
            part.set("transform",f"translate({icon_x*(1-scale):.2f} "
                       f"{icon_y*(1-scale):.2f}) scale({scale:.3f})")
        # Give factual values a dedicated right zone, but let long material
        # descriptions occupy two complete lines rather than ellipsize.
        right_w=max(106,cw*.30 if cw>350 else cw*.39)
        label_x=bx+plate+13
        label_w=max(72,cw-right_w-plate-30)
        value_x=bx+cw-right_w-9
        value_w=right_w-10
        _rule(scene,"specs",value_x-9,by+10,
              value_x-9,by+rh-10,"#E4E7EB",1.7,
              f"pro3-spec-divider-{i}")
        _type(scene,"specs",label,label_x,by+7,label_w,rh-12,
              25 if not portrait else 22,12,
              INK,True,f"pro-spec-name-{i}",2)
        text_len=len(str(value))
        preferred=34 if text_len<=8 else (24 if text_len<=13 else 21)
        _type(scene,"specs",value,value_x,by+7,value_w,rh-12,
              preferred,11,accent,True,f"pro-spec-value-{i}",2)


def _detail_or_stat(scene, brief, detail, x, y, w, h, accent):
    """Use submitted rear-view image; otherwise use one real key statistic."""
    if detail is not None:
        scene.rect("dimensions",x,y,w,h,"#FFFFFF",
                   rad=12,ident="pro3-inset-frame")
        _photo(scene,detail,x+10,y+9,w-20,h-23,
               "detail-photo",layer="dimensions",trim=True)
        scene.rect("dimensions",x,y+h-7,w,7,accent,
                   ident="pro3-inset-underline")
        return
    facts=_lines(brief,"specs",8)
    scene.polygon("dimensions",[
        (x,y+5),(x+w,y+5),(x+w-16,y+h),
        (x,y+h)
    ],"#F7F7F7",ident="pro3-hero-stat-plate")
    scene.rect("dimensions",x,y+5,8,h-10,accent,
               ident="pro3-hero-stat-rail")
    if facts:
        first_name,first_value=facts[0]
        _type(scene,"dimensions",first_name.upper(),
              x+23,y+21,w-39,40,21,12,
              MID,True,"pro3-hero-stat-label",2)
        _type(scene,"dimensions",first_value,
              x+20,y+63,w-40,h-77,60,20,
              accent,True,"pro3-hero-stat-value",2)
    else:
        _type(scene,"dimensions","ПОДРОБНОСТИ У ПРОИЗВОДИТЕЛЯ",
              x+21,y+25,w-45,h-50,28,12,
              accent,True,"pro3-stat-fallback",2)


def _dims(scene, brief, detail, drawing, x, y, w, h, accent, portrait):
    facts=_lines(brief,"dimensions",4)
    if not facts and drawing is None and detail is None:
        return
    scene.rect("dimensions",x,y,w,h,"#FFFFFF",
               ident="pro3-dim-stage")
    if portrait:
        _slug(scene,"dimensions","ГАБАРИТЫ И ЧЕРТЁЖ" if drawing is not None
              else "ГАБАРИТНЫЕ РАЗМЕРЫ",
              x+8,y+4,min(595,w*.64),40,
              accent,"pro-dimensions-title",25)
        work_y=y+53
        work_h=h-59
        if drawing is not None:
            dw=w*.54
            _photo(scene,drawing,x+10,work_y,dw-16,work_h,
                   "original-drawing",layer="dimensions")
            first=x+dw+4
            rest=w-dw-14
            cols=1
        else:
            first=x+12
            rest=w-24
            cols=min(3,max(1,len(facts)))
    else:
        detail_w=318 if detail is not None else 299
        if drawing is not None and detail is None:
            detail_w=0
        if detail_w:
            _detail_or_stat(scene,brief,detail,x+10,y+9,
                            detail_w-18,h-17,accent)
        main_x=x+detail_w
        main_w=w-detail_w-8
        _slug(scene,"dimensions","ГАБАРИТЫ И ЧЕРТЁЖ" if drawing is not None
              else "ГАБАРИТНЫЕ РАЗМЕРЫ",
              main_x,y+4,min(main_w*.81,566),39,
              accent,"pro-dimensions-title",26)
        work_y=y+49
        work_h=h-56
        if drawing is not None:
            dw=main_w*.59
            _photo(scene,drawing,main_x+8,work_y,dw-14,work_h,
                   "original-drawing",layer="dimensions")
            first=main_x+dw+5
            rest=main_w-dw-16
            cols=1
        else:
            first=main_x+8
            rest=main_w-17
            cols=min(3,max(1,len(facts)))
    if not facts:
        return
    gap=8
    rows=math.ceil(len(facts)/cols)
    cw=(rest-gap*(cols-1))/cols
    ch=(work_h-gap*(rows-1))/rows
    for i,(name,value) in enumerate(facts):
        px=first+(i%cols)*(cw+gap)
        py=work_y+(i//cols)*(ch+gap)
        scene.rect("dimensions",px,py,cw,ch,
                   "#F1F4F7" if i%2==0 else "#FAFAFB",
                   rad=5,ident=f"pro-dimension-cell-{i}")
        scene.rect("dimensions",px,py,cw,4,accent,
                   ident=f"pro3-dim-cap-{i}")
        name_height=min(31,ch*.36)
        _type(scene,"dimensions",name.upper(),px+12,py+7,
              cw-22,name_height,21,11,
              MID,True,f"pro-dimension-name-{i}",1)
        _type(scene,"dimensions",value,px+10,
              py+name_height+9,cw-19,
              max(18,ch-name_height-28),
              38 if cw>135 else 27,12,
              accent,True,f"pro-dimension-value-{i}",2)
        baseline=py+ch-10
        _rule(scene,"dimensions",px+12,baseline,
              px+cw-12,baseline,accent,1.7,
              f"pro-dimension-measure-{i}")
        _rule(scene,"dimensions",px+12,baseline-4,
              px+12,baseline+3,accent,1.7,
              f"pro3-dim-tick-left-{i}")
        _rule(scene,"dimensions",px+cw-12,baseline-4,
              px+cw-12,baseline+3,accent,1.7,
              f"pro3-dim-tick-right-{i}")


def _benefits(scene, benefits, x, y, w, h, accent, portrait):
    if not benefits:
        return
    scene.rect("benefits",x,y,w,h,"#FFFFFF",
               ident="pro3-benefits-stage")
    _slug(scene,"benefits","ПРЕИМУЩЕСТВА",x+15,y+2,
          min(w*.52,630),42,accent,
          "pro-benefits-title",29)
    n=min(6,len(benefits))
    cols=2 if portrait and n<=4 else (3 if portrait else n)
    rows=math.ceil(n/cols)
    top=y+52
    area_h=h-56
    cw=(w-20)/cols
    ch=area_h/rows
    for i,claim in enumerate(benefits[:6]):
        col=i%cols
        row=i//cols
        bx=x+10+col*cw
        by=top+row*ch
        if col:
            _rule(scene,"benefits",bx,by+6,bx,by+ch-6,
                  accent,1.6,f"pro3-benefit-split-{i}")
        if portrait:
            icon_x=bx+53
            icon_y=by+ch*.49
            size=26
            text_x=bx+105
            text_y=by+8
            text_w=cw-118
            text_h=ch-15
        else:
            icon_x=bx+cw*.5
            icon_y=by+23
            size=26
            text_x=bx+16
            text_y=by+57
            text_w=cw-32
            text_h=ch-62
        scene.el("benefits","circle",f"pro-benefit-halo-{i}",{
            "cx":icon_x,"cy":icon_y,"r":size+6,
            "fill":"#FFF1F2","stroke":accent,"stroke-width":2
        })
        _benefit_icon(scene,icon_x,icon_y,i,accent)
        _type(scene,"benefits",str(claim).strip(),
              text_x,text_y,text_w,text_h,
              25 if not portrait else 24,12,
              INK,True,f"pro-benefit-{i}",2)


def _roi(scene, brief, x, y, w, h, accent):
    if not brief.get("show_roi"):
        return
    data=compute_roi(brief)
    if not data:
        return
    money=str(brief.get("currency") or "Br").strip()[:10] or "Br"
    metrics=[
        (f"ЗА РЕЙС, {money}",data["per_trip"]),
        ("РЕЙСОВ В ГОД",data["trips"]),
        (f"ЗА ГОД, {money}",data["annual"]),
        (f"БАЛАНС, {money}",data["net"])
    ]
    scene.rect("roi",x,y,w,h,"#FFF3F4",
               ident="pro3-roi-stage")
    cw=w/4
    for i,(title,value) in enumerate(metrics):
        px=x+i*cw
        if i:
            _rule(scene,"roi",px,y+8,px,y+h-8,
                  "#DE9AA3",1.6,
                  f"pro3-roi-divider-{i}")
        _type(scene,"roi",title,px+14,y+7,
              cw-27,h*.32,19,11,
              "#5E2C34",True,
              f"pro-roi-label-{i}",1)
        formatted=f"{value:,.0f}".replace(","," ")
        _type(scene,"roi",formatted,px+13,
              y+h*.36,cw-26,h*.54,
              34 if w>900 else 27,14,
              accent,True,f"pro-roi-value-{i}",1)


def _proof(scene, facts, x, y, w, h, accent):
    if not facts:
        return
    scene.rect("benefits",x,y,w,h,"#FDFDFE",
               ident="pro-proof-panel")
    proof_title="ПОДТВЕРЖДЁННЫЕ ФАКТЫ" if w>=850 else "ПОДТВЕРЖДЕНО"
    _slug(scene,"benefits",proof_title,
          x+5,y+4,min(w*.36,310),h-8,
          accent,"pro3-proof-slug",21)
    left=x+min(w*.36,310)+10
    width=x+w-left-9
    cols=min(2 if w<850 else 4,len(facts))
    rows=math.ceil(len(facts)/cols)
    cw=width/cols
    rh=(h-8)/rows
    for i,fact in enumerate(facts):
        px=left+(i%cols)*cw
        py=y+4+(i//cols)*rh
        scene.el("benefits","circle",f"pro3-proof-circle-{i}",{
            "cx":px+17,"cy":py+rh*.5,"r":10,
            "fill":"none","stroke":accent,"stroke-width":2
        })
        _check(scene,"benefits",px+11,py+rh*.5-7,
               14,accent,f"pro3-proof-check-{i}")
        text_h=min(56,rh-9)
        _type(scene,"benefits",fact,px+35,
              py+(rh-text_h)/2,
              cw-44,text_h,19,11,
              INK,True,f"pro3-proof-{i}",2)


def _bottom_band(scene, brief, proof, x, y, w, h, accent):
    with_roi=bool(brief.get("show_roi") and compute_roi(brief))
    if proof and with_roi:
        split=w*.49
        _proof(scene,proof,x,y,split-6,h,accent)
        _roi(scene,brief,x+split+4,y,w-split-4,h,accent)
    elif proof:
        _proof(scene,proof,x,y,w,h,accent)
    elif with_roi:
        _roi(scene,brief,x,y,w,h,accent)


def _footer(scene, brief, accent, portrait):
    w,h=scene.w,scene.h
    y=1706 if portrait else 969
    scene.rect("cta_bg",0,y,w,h-y,
               "url(#pro-red-gradient)",ident="pro-cta")
    for i in range(3):
        xx=w-275+i*73
        scene.polygon("cta_bg",[
            (xx,y),(xx+48,y),(xx-126,h),(xx-174,h)
        ],"#FFFFFF",opacity=".15",
        ident=f"pro3-footer-chevron-{i}")
    price=_format_price(brief.get("price"))
    currency=str(brief.get("currency") or "").strip()
    caption=price+" "+currency+(" с НДС" if brief.get("vat",True)
                                 else "") if price else "ЗАПРОСИТЕ ПРЕДЛОЖЕНИЕ"
    phones=[str(v).strip() for v in (brief.get("phones") or [])[:2]
            if str(v).strip()]
    if portrait:
        scene.polygon("cta_bg",[
            (0,y),(w-62,y),(w-144,y+98),(0,y+98)
        ],accent,ident="pro3-footer-price-plate")
        _type(scene,"price",caption,38,y+20,
              w-87,78,74 if price else 42,23,
              "#FFFFFF",True,"pro-price",1,italic=True)
        if phones:
            _rule(scene,"contacts",35,y+112,w-34,y+112,
                  "#FFFFFF",2.2,"pro3-footer-divider")
            _type(scene,"contacts","СВЯЖИТЕСЬ С НАМИ",38,
                  y+121,w*.41,39,26,16,
                  "#FFFFFF",True,"pro3-contact-title",1)
            for i,phone in enumerate(phones):
                _type(scene,"contacts",phone,w*.48,
                      y+119+i*36,w*.48,36,28,15,
                      "#FFFFFF",True,f"pro3-phone-{i}",1)
    else:
        split=w*.58
        scene.polygon("cta_bg",[
            (0,y),(split-18,y),(split-107,h),(0,h)
        ],accent,ident="pro3-footer-price-plate")
        _type(scene,"price",caption,42,y+26,
              split-129,h-y-36,71 if price else 40,
              21,"#FFFFFF",True,"pro-price",1,italic=True)
        if phones:
            _rule(scene,"contacts",split-21,y+17,
                  split-21,h-16,"#FFFFFF",2.6,
                  "pro3-footer-divider")
            _type(scene,"contacts","СВЯЖИТЕСЬ С НАМИ",
                  split+17,y+15,w-split-44,34,28,16,
                  "#FFFFFF",True,"pro3-contact-title",1)
            for i,phone in enumerate(phones):
                _type(scene,"contacts",phone,split+17,
                      y+49+i*30,w-split-48,29,27,14,
                      "#FFFFFF",True,f"pro3-phone-{i}",1)


def create_pro_campaign_svg(brief, key, hero=None, detail=None,
                            logo=None, drawing=None, backdrop=None,
                            ai_product=False):
    if key not in ("4x3","9x16"):
        raise ValueError("Неизвестное соотношение сторон.")
    portrait=key=="9x16"
    scene=Scene(key,brief.get("accent"),"industrial")
    accent=scene.accent
    _tint(scene,accent)
    scene.rect("decor",0,0,scene.w,scene.h,PAPER,ident="pro3-paper")
    facts=_lines(brief,"specs",8)
    dims=_lines(brief,"dimensions",4)
    benefits=[str(s).strip()[:150] for s in (brief.get("benefits") or [])
              if str(s).strip()][:6]
    proof=[str(s).strip()[:180] for s in (brief.get("proof_points") or [])
           if str(s).strip()][:4]
    with_dim=bool(dims or drawing is not None or detail is not None)
    with_band=bool(proof or (brief.get("show_roi") and compute_roi(brief)))
    _header(scene,brief,logo,accent,portrait)

    if not portrait:
        # 4:3 proportions mirror reference sections rather than spreadsheet rows.
        main_y=171
        main_bottom=720 if with_dim else 724
        left_w=928 if facts else 1440
        spec_x=943
        hero_h=(main_bottom-main_y-163) if with_dim else main_bottom-main_y
        _hero(scene,brief,hero,detail,backdrop,ai_product,
              0,main_y,left_w,hero_h,accent,False)
        if facts:
            _specs(scene,facts,spec_x,181,486,main_bottom-185,accent,False)
        if with_dim:
            _dims(scene,brief,detail,drawing,0,main_bottom-163,
                  left_w,163,accent,False)
        benefit_y=731
        benefit_h=140 if with_band else 230
        if benefits:
            _benefits(scene,benefits,0,benefit_y,1440,benefit_h,accent,False)
        if with_band:
            _bottom_band(scene,brief,proof,0,881,1440,77,accent)
        _footer(scene,brief,accent,False)
    else:
        # Portrait retains a dominant product followed by spacious specs.
        main_y=252
        has_roi=bool(brief.get("show_roi") and compute_roi(brief))
        both=bool(proof and has_roi)
        # A split 146px band made the proof title and claims illegible.
        # Use two full-width editorial bands when both types are supplied.
        specs_h=(370 if both else 411) if facts else 0
        dims_h=(176 if both else 202) if with_dim else 0
        benefit_h=(188 if both else 224) if benefits else 0
        proof_h=(101 if both else 0)
        roi_h=(120 if both else 0)
        band_h=proof_h+roi_h if both else (146 if with_band else 0)
        band_gap=10 if both else 0
        count=sum(bool(v) for v in (specs_h,dims_h,benefit_h,band_h))
        gaps=count*10+band_gap
        hero_h=max(380,1700-main_y-specs_h-dims_h-benefit_h-band_h-gaps)
        _hero(scene,brief,hero,detail,backdrop,ai_product,
              14,main_y,1052,hero_h,accent,True)
        cursor=main_y+hero_h+10
        if facts:
            _specs(scene,facts,19,cursor,1042,specs_h,accent,True)
            cursor+=specs_h+10
        if with_dim:
            _dims(scene,brief,detail,drawing,14,cursor,1052,
                  dims_h,accent,True)
            cursor+=dims_h+10
        if benefits:
            _benefits(scene,benefits,14,cursor,1052,
                      benefit_h,accent,True)
            cursor+=benefit_h+10
        if both:
            _proof(scene,proof,14,cursor,1052,proof_h,accent)
            cursor+=proof_h+10
            _roi(scene,brief,14,cursor,1052,roi_h,accent)
        elif with_band:
            _bottom_band(scene,brief,proof,14,cursor,
                         1052,band_h,accent)
        _footer(scene,brief,accent,True)
    return scene.export()
