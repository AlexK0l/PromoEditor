"""Reference-pro ZUBR TRAIL advert, based on customer-approved 4:3 / 9:16 samples.

This is a factual, information-rich PROMOTIONAL POSTER, not a sparse photo
with mismatched text boxes. Both formats contain the customer's real logo,
trailer, drawing, ALL approved technical specifications and dimensions,
claims, real benefits, ROI (only with source inputs), price and contacts.

Every technical value is editable SVG text; no invented specifications,
fake phone numbers, OCR, clipped copy or synthetic ROI assumptions. Use an
actual second uploaded photo when available; otherwise use AI scenery as a
visually different inset, never claim it is another real camera angle.

All geometry, vector icons, headings and color hierarchy are locally
rendered without paid calls. It is an exact-copy typographic overlay stage.
"""
from __future__ import annotations

import base64
import io
import math
import xml.etree.ElementTree as ET

from PIL import Image

from .ai_exact_copy_render import FORMATS, _size_and_lines, verified_copy, _format_money
from .editable_export import Scene, NS, XLINK
from .render import compute_roi

_FONT = "DejaVu Sans Condensed"
_RED = "#D51125"
_RED_DARK = "#B90B1C"
_INK = "#171C25"
_MUTED = "#4F5A68"
_PAPER = "#F7F8FB"
_BORDER = "#D7DEE8"
_WHITE = "#FFFFFF"


def _pairs(brief: dict, name: str) -> list[tuple[str,str]]:
    result=[]
    for pair in (brief.get(name) or []):
        if not isinstance(pair,(tuple,list)) or len(pair)!=2:
            continue
        label,value = str(pair[0]).strip(),str(pair[1]).strip()
        if label and value:
            result.append((label,value))
    return result


def _role_text(scene: Scene, group: str, role: str | None, value: str,
               x: float,y: float,w: float,h: float,
               size: int,minimum: int, color: str = _INK,
               bold: bool = False) -> None:
    """Fit ALL user text as editable SVG tspans or raise an explicit error."""
    value=str(value or "").strip()
    if not value:
        return
    if w<10 or h<10:
        raise ValueError("Недостаточно места для "+(role or "заголовка"))
    try:
        fs,lines=_size_and_lines([value],w,h,_FONT,bold,size,minimum)
    except ValueError as exc:
        raise ValueError(
            "Стиль референса: не помещается точное значение «"
            + (role or "заголовок") + "»; источник не сокращён."
        ) from exc
    text=scene.el(group,"text","reference-"+(role or "section"),{
        "x":x,"y":y+fs,"font-family":_FONT,"font-weight":"700" if bold else "400",
        "font-size":fs,"fill":color,"xml:space":"preserve",
        "data-verified-role":role,"data-exact-copy":value if role else None,
    })
    for i,line in enumerate(lines):
        child=ET.SubElement(text,f"{{{NS}}}tspan",{
            "x":str(round(x,2)),"dy":"0" if i==0 else str(round(fs*1.24,2))})
        child.text=line


def _photo(scene: Scene, raw: bytes | Image.Image,
           x: float,y: float,w: float,h: float,
           *, ident: str, provenance: str) -> None:
    """Bounded photographic source downsampling (safe on the 760MB cgroup)."""
    if isinstance(raw,Image.Image):
        source=raw.copy()
    else:
        source=Image.open(io.BytesIO(raw))
    try:
        source.draft("RGB",(1300,950))
        source.thumbnail((1600,1200),Image.Resampling.LANCZOS)
        buf=io.BytesIO()
        source.convert("RGB").save(buf,format="JPEG",quality=87,
                                   subsampling=0,optimize=False)
    finally:
        source.close()
    scene.el("photos","image",ident,{
        "x":x,"y":y,"width":w,"height":h,
        "preserveAspectRatio":"xMidYMid meet",
        "data-source":provenance,
        f"{{{XLINK}}}href":"data:image/jpeg;base64,"
        +base64.b64encode(buf.getvalue()).decode("ascii"),
    })


def _panel(scene: Scene, x: float,y: float,w: float,h: float,
           title: str, *, accent: str) -> None:
    scene.rect("decor",x,y,w,h,_WHITE,rad=12,ident="ref-paper")
    scene.rect("decor",x,y,w,35,"#F0F2F6",rad=8,ident="ref-heading-band")
    scene.polygon("decor",[(x,y),(x+96,y),(x+81,y+35),(x,y+35)],
                  accent,ident="ref-red-cut")
    scene.polygon("decor",[(x+92,y),(x+w,y),(x+w-21,y+35),
                            (x+78,y+35)],"#272A30",
                  ident="ref-slate-cut")
    _role_text(scene,"heading",None,title,x+24,y+3,w-34,30,
               size=22,minimum=16,color=_WHITE,bold=True)


def _rule(scene: Scene,x: float,y: float,w: float,
          color: str = _BORDER) -> None:
    scene.rect("decor",x,y,w,1,color,ident="ref-row-rule")


def _kv_rows(scene: Scene, role: str, rows: list[tuple[str,str]],
             x: float,y: float,w: float,h: float, *,
             label_share: float = .49, font: int = 17,
             min_font: int = 12) -> None:
    if not rows:
        return
    if len(rows)>20:
        raise ValueError("Референсный макет вмещает максимум 20 строк "+role)
    # Long component facts need more vertical room without losing a word.
    weights=[]
    for label,value in rows:
        weights.append(1.55 if len(value)>42 else
                       1.31 if len(value)>24 else
                       1.0)
    total=sum(weights)
    current=y
    for (label,value),weight in zip(rows,weights):
        row_h=h*weight/total
        label_w=w*label_share-10
        value_x=x+w*label_share
        value_w=w*(1-label_share)-12
        _role_text(scene,role,None if False else None,"",0,0,0,0,1,1)
        # Mark the row as ONE verified exact field. Its label and value
        # remain independent, editable text elements, never a bitmap.
        row_group=scene.el(
            role if role in scene.groups else "specs","g",
            "verified-fact-row",{
                "data-verified-role":role,
                "data-exact-copy":label+": "+value,
                "data-fact-label":label,
                "data-fact-value":value,
            })
        first_i=len(scene.groups[role])
        _role_text(scene,role,None,label,
                   x+7,current+3,label_w,row_h-5,
                   size=font,minimum=min_font,color=_INK)
        _role_text(scene,role,None,value,
                   value_x+2,current+3,value_w,row_h-5,
                   size=font+1,minimum=min_font,color=_RED_DARK,bold=True)
        # Put both editable text nodes inside the tagged SVG fact row.
        for node in list(scene.groups[role])[first_i:]:
            scene.groups[role].remove(node)
            row_group.append(node)
        _rule(scene,x+5,current+row_h-2,w-12,"#E8EBF0")
        current+=row_h


def _static_bullet(scene: Scene, x: float,y: float,r: float = 9) -> None:
    scene.el("decor","circle","ref-red-check",{
        "cx":x,"cy":y,"r":r,"fill":_RED})
    scene.el("decor","path","ref-check-stroke",{
        "d":f"M {x-r*.52} {y} L {x-r*.08} {y+r*.38} "
            f"L {x+r*.60} {y-r*.44}",
        "stroke":_WHITE,"stroke-width":max(2,r*.20),
        "stroke-linecap":"round","stroke-linejoin":"round","fill":"none"})


def _claims(scene: Scene, lines: list[str], x: float,y: float,
            w: float,h: float, *, font: int) -> None:
    if not lines:
        return
    cell=h/len(lines)
    for i,value in enumerate(lines):
        top=y+i*cell
        scene.polygon("decor",[
            (x+25,top+2),(x+w-3,top+2),(x+w-15,top+cell-5),
            (x+8,top+cell-5)],
            _WHITE,ident="ref-claim-light")
        scene.polygon("decor",[
            (x+7,top+2),(x+91,top+2),(x+78,top+cell-5),
            (x-5,top+cell-5)],
            _RED,ident="ref-claim-red")
        _static_bullet(scene,x+40,top+cell/2,10)
        _role_text(scene,"claims","claims",value,
                   x+106,top+5,w-120,cell-13,
                   size=font,minimum=max(13,font-6),color=_INK,bold=True)


def _proof(scene: Scene, lines: list[str], x: float,y: float,
           w: float,h: float, *, font: int) -> None:
    if not lines:
        return
    row_h=h/len(lines)
    for i,value in enumerate(lines):
        yp=y+i*row_h
        _static_bullet(scene,x+13,yp+18,8)
        _role_text(scene,"benefits","proofs",value,
                   x+32,yp+4,w-43,row_h-7,font,max(12,font-4),_INK)
        _rule(scene,x+32,yp+row_h-1,w-39)


def _benefits_wide(scene: Scene, lines: list[str],
                   x: float,y: float,w: float,h: float) -> None:
    if not lines:
        return
    cols=len(lines)
    cw=w/cols
    for i,value in enumerate(lines):
        xx=x+i*cw
        if i:
            scene.rect("decor",xx-5,y+10,1,h-17,_BORDER)
        scene.rect("decor",xx+12,y+3,31,4,_RED,ident="ref-benefit-marker")
        _role_text(scene,"benefits","benefits",value,
                   xx+10,y+16,cw-23,h-21,
                   size=16,minimum=11,color=_INK)


def _benefits_tall(scene: Scene, lines: list[str],
                   x: float,y: float,w: float,h: float) -> None:
    for i,value in enumerate(lines):
        col=i%2;row=i//2
        xx=x+col*(w/2);yy=y+row*(h/3)
        _static_bullet(scene,xx+12,yy+23,9)
        _role_text(scene,"benefits","benefits",value,
                   xx+35,yy+6,w/2-48,h/3-11,
                   size=20,minimum=13,color=_INK)
        if row<2:
            _rule(scene,xx+9,yy+h/3-1,w/2-18)


def _roi_data(brief: dict) -> list[tuple[str,str]]:
    if not brief.get("show_roi"):
        return []
    roi=compute_roi(brief)
    if not roi or not roi["annual"] or not math.isfinite(roi["annual"]):
        return []
    curr=str(brief.get("currency") or "₽").strip()
    results=[
        ("Доп. выручка за рейс",_format_money(roi["per_trip"])+" "+curr),
        ("Рейсов в год",_format_money(roi["trips"])),
        ("Доп. выручка в год",_format_money(roi["annual"])+" "+curr),
        ("За "+_format_money(roi["year"])+" лет",
            _format_money(roi["gross"])+" "+curr),
    ]
    if roi["premium"]>0:
        results.append(("Разница в цене",_format_money(roi["premium"])+" "+curr))
    results.append(("Итоговый расчётный эффект",
                    _format_money(roi["net"])+" "+curr))
    if roi["payback"] is not None and math.isfinite(roi["payback"]):
        results.append(("Окупаемость разницы",
                        f'{roi["payback"]:.2f}'.replace(".",",")+" года"))
    return results


def _roi(scene: Scene, brief: dict, x: float,y: float,
         w: float,h: float, *, tall: bool) -> None:
    data=_roi_data(brief)
    if not data:
        return
    if tall:
        # 6-7 balanced lines on a dedicated 360px economics panel.
        _kv_rows(scene,"roi",data,x,y,w,h,label_share=.58,
                 font=23,min_font=15)
    else:
        _kv_rows(scene,"roi",data,x,y,w,h,label_share=.57,
                 font=17,min_font=11)


def _headline(scene: Scene, brief: dict, logo: bytes | None, *,
              tall: bool) -> None:
    w=1080 if tall else 1440
    h=166 if tall else 132
    scene.rect("decor",0,0,w,h,"#FAFBFD",ident="ref-header")
    scene.polygon("decor",[(w-144,0),(w,0),(w-64,96),(w-214,96)],
                  _RED,ident="ref-top-stripe")
    scene.polygon("decor",[(w-55,0),(w,0),(w-29,41)],"#191E29",
                  ident="ref-top-slate")
    lx=20;ly=4;lw=234 if tall else 250;lh=126 if tall else 116
    if logo:
        _photo(scene,logo,lx,ly,lw,lh,
               ident="ref-source-customer-logo",provenance="original-customer-logo")
    else:
        _role_text(scene,"heading","brand",
                   str(brief.get("brand") or ""),lx+9,ly+28,lw-16,68,
                   size=34,minimum=20,color=_RED,bold=True)
    bx=279 if tall else 295
    _role_text(scene,"heading","category",
               str(brief.get("category") or ""),
               bx,11,w-bx-170,38,30 if tall else 29,18,_INK,True)
    _role_text(scene,"heading","model",
               str(brief.get("model") or ""),
               bx,48,w-bx-168,60,59 if tall else 58,34,_INK,True)
    slogan=str(brief.get("slogan") or "").strip()
    if slogan:
        scene.polygon("decor",[
            (bx-15,h-43),(w-38,h-43),(w-61,h-4),(bx-34,h-4)],
            _RED,ident="ref-ribbon-slogan")
        _role_text(scene,"heading","slogan",slogan,
                   bx+7,h-42,w-bx-100,35,
                   23 if tall else 24,16,_WHITE,True)


def _price_footer(scene: Scene, data: dict, *,
                  tall: bool) -> None:
    w,h=FORMATS["9x16" if tall else "4x3"]
    price_y=1752 if tall else 947
    price_h=101 if tall else 70
    scene.polygon("cta_bg",[(29,price_y),(w-35,price_y),
                             (w-3,price_y+20),(w-36,price_y+price_h),
                             (10,price_y+price_h),(0,price_y+price_h-18)],
                  _RED,ident="ref-price-ribbon")
    if data.get("price"):
        _role_text(scene,"price","price","Цена: "+data["price"][0],
                   82 if tall else 180,price_y+12,
                   w-(130 if tall else 220),price_h-20,
                   53 if tall else 52,33,_WHITE,True)
    contact_y=1862 if tall else 1025
    scene.rect("cta_bg",0,contact_y,w,h-contact_y,_RED_DARK,
               ident="ref-phone-footer")
    _role_text(scene,"contacts",None,"Свяжитесь с нами",
               28,contact_y+9,260,h-contact_y-15,
               26 if tall else 25,17,_WHITE,True)
    phones=data.get("phones") or []
    for i,value in enumerate(phones[:2]):
        xx=(295+i*380) if tall else (455+i*470)
        ww=365 if tall else 450
        _role_text(scene,"contacts","phones",value,
                   xx,contact_y+8,ww,h-contact_y-14,
                   28 if tall else 28,18,_WHITE,True)


def _body_wide(scene: Scene, brief: dict, data: dict,
               hero: bytes | Image.Image, inset: bytes | Image.Image,
               drawing: bytes | None) -> None:
    # Two real product scenes and the user's four advertising claims.
    scene.rect("decor",17,142,635,264,_WHITE,rad=13,
               ident="ref-hero-wide")
    _photo(scene,hero,22,147,623,253,ident="ref-hero-photo",
           provenance="rebranded-customer-product")
    if data["claims"]:
        _claims(scene,data["claims"][:4],666,147,283,250,font=20)
    scene.rect("decor",965,142,459,264,_WHITE,rad=13,
               ident="ref-inset-wide")
    _photo(scene,inset,971,148,446,251,ident="ref-inset-photo",
           provenance="secondary-photo-or-paid-ai-scene")

    spec_box=(19,412,422,390)
    dim_box=(451,412,447,390)
    proof_box=(908,412,513,390)
    for box,name in (
        (spec_box,"Основные ТТХ"),
        (dim_box,"Габаритные размеры, мм"),
        (proof_box,"Почему выгоднее стального аналога"),
    ):
        _panel(scene,*box,name,accent=_RED)
    spec=_pairs(brief,"specs")
    dims=_pairs(brief,"dimensions")
    _kv_rows(scene,"specs",spec,29,454,405,337,
             label_share=.47,font=17,min_font=12)
    if drawing:
        _photo(scene,drawing,466,456,420,198,
               ident="ref-original-drawing-wide",
               provenance="original-customer-drawing")
    _kv_rows(scene,"dimensions",dims,463,664,421,126,
             label_share=.62,font=15,min_font=12)
    _proof(scene,data["proofs"][:6],921,455,488,335,font=20)

    _panel(scene,19,809,871,130,"Наши преимущества",accent=_RED)
    _panel(scene,898,809,523,130,
           "Экономический эффект · расчётный",accent=_RED)
    _benefits_wide(scene,data["benefits"][:6],27,850,854,78)
    _roi(scene,brief,912,851,491,78,tall=False)
    _price_footer(scene,data,tall=False)


def _body_tall(scene: Scene, brief: dict, data: dict,
               hero: bytes | Image.Image, inset: bytes | Image.Image,
               drawing: bytes | None) -> None:
    scene.rect("decor",17,175,652,267,_WHITE,rad=12,
               ident="ref-hero-tall")
    _photo(scene,hero,22,180,642,258,ident="ref-hero-photo",
           provenance="rebranded-customer-product")
    _claims(scene,data["claims"][:4],693,184,369,251,font=27)
    scene.rect("decor",17,450,581,198,_WHITE,rad=12,
               ident="ref-inset-tall")
    _photo(scene,inset,22,454,572,188,ident="ref-inset-photo",
           provenance="secondary-photo-or-paid-ai-scene")
    _proof(scene,data["proofs"][:4],617,448,441,202,font=19)

    _panel(scene,16,663,486,445,"Основные ТТХ",accent=_RED)
    _panel(scene,512,663,552,445,"Габаритные размеры, мм",accent=_RED)
    _kv_rows(scene,"specs",_pairs(brief,"specs"),
             24,704,468,388,label_share=.47,font=21,min_font=14)
    if drawing:
        _photo(scene,drawing,529,707,518,206,
               ident="ref-original-drawing-tall",
               provenance="original-customer-drawing")
    _kv_rows(scene,"dimensions",_pairs(brief,"dimensions"),
             529,923,518,173,label_share=.61,font=20,min_font=13)

    _panel(scene,16,1117,1048,227,
           "Наши преимущества",accent=_RED)
    _benefits_tall(scene,data["benefits"][:6],31,1161,1018,168)
    _panel(scene,16,1353,1048,388,
           "Экономический эффект · расчётный сценарий",
           accent=_RED)
    _roi(scene,brief,34,1407,1013,318,tall=True)
    _price_footer(scene,data,tall=True)


def reference_poster_copy(brief: dict, *, drawing: bool) -> dict:
    """All user facts the reference design actually prints on BOTH formats."""
    copy=verified_copy(brief)
    copy["claims"]=copy["claims"][:4]
    copy["proofs"]=copy["proofs"][:4]
    copy["benefits"]=copy["benefits"][:6]
    copy["phones"]=copy["phones"][:2]
    copy["roi"]=[label+": "+value for label,value in _roi_data(brief)]
    # Do not claim to render an extra user-provided fact that did not fit.
    # Existing business limits are 10 specs and 7 dimensions in this mode;
    # fail closed rather than silently drop any submitted technical data.
    if len(copy["specs"])>10 or len(copy["dimensions"])>7:
        raise ValueError(
            "Референсный плакат получил больше 10 ТТХ / 7 размеров. "
            "Исходные строки не обрезаны.")
    return copy


def render_reference_svg(brief: dict, fmt: str, artwork: Image.Image,
                         slots: dict, styling: dict, *,
                         hero: bytes | None = None,
                         detail: bytes | None = None,
                         logo: bytes | None = None,
                         drawing: bytes | None = None,
                         copy_override: dict | None = None) -> bytes:
    """Structured 4:3 or 9:16 editorial ad following the customer's photos."""
    if fmt not in FORMATS or artwork.size!=FORMATS[fmt]:
        raise ValueError("Неверное разрешение оплаченной композиции.")
    copy=copy_override if copy_override is not None else reference_poster_copy(
        brief,drawing=bool(drawing))
    if not isinstance(copy,dict):
        raise ValueError("Недоступны проверенные данные референсного макета.")
    scene=Scene(fmt,brief.get("accent"),brief.get("style"))
    scene.groups["background"].clear()
    scene.groups["decor"].clear()
    scene.rect("background",0,0,scene.w,scene.h,_PAPER,
               ident="ref-ivory-page")
    scene.polygon("decor",[(0,0),(163,0),(0,380)],"#E9EEF5",
                  ident="ref-corner-sheen")
    scene.polygon("decor",[(scene.w-360,0),(scene.w,0),
                            (scene.w-160,160)],"#EDF0F7",
                  ident="ref-upper-gloss")
    tall=fmt=="9x16"
    _headline(scene,brief,logo,tall=tall)
    # User-supplied rebadged image is authoritative. If no secondary
    # original is supplied, use the paid AI artwork for the inset but never
    # misrepresent its scene as a genuinely second photographic angle.
    main=hero if hero else artwork
    secondary=detail if detail else artwork
    if tall:
        _body_tall(scene,brief,copy,main,secondary,drawing)
    else:
        _body_wide(scene,brief,copy,main,secondary,drawing)
    return scene.export()
