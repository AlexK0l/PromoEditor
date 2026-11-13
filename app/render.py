"""Deterministic, Cyrillic-capable image compositor. No model-authored copy is drawn."""
from __future__ import annotations

import io
import math
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = 48_000_000
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FONT_REG = ['/usr/share/fonts/opentype/inter/Inter-Regular.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf', 'DejaVuSans.ttf']
FONT_BOLD = ['/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf', 'DejaVuSans-Bold.ttf']
FONT_SEMI = ['/usr/share/fonts/opentype/inter/Inter-SemiBold.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf', 'DejaVuSans.ttf']


def font(sz: int, bold=False, semi=False):
    paths = FONT_BOLD if bold else FONT_SEMI if semi else FONT_REG
    for p in paths:
        try:
            return ImageFont.truetype(p, int(sz))
        except OSError:
            continue
    return ImageFont.load_default()


def valid_hex(color: str, default='#E31B26') -> str:
    if isinstance(color, str) and len(color) == 7 and color[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in color[1:]):
        return color.upper()
    return default


def rgb(hex_value):
    value = valid_hex(hex_value).lstrip('#')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def rgba(value, a=255):
    if isinstance(value, tuple): return tuple(value[:3]) + (a,)
    return rgb(value) + (a,)


def blend(c1, c2, t: float):
    return tuple(int(c1[i]*(1-t) + c2[i]*t) for i in range(3))


def rounded(draw, box, radius=18, fill='#FFFFFF', outline=None, width=1):
    draw.rounded_rectangle(tuple(map(int,box)),radius=radius,fill=fill,outline=outline,width=width)


def wrap_line(draw, text, typeface, max_width):
    text = str(text)
    if not text: return ['']
    words = text.split(' ')
    lines=[]; cur=''
    for word in words:
        candidate=(cur+' '+word).strip() if cur else word
        if draw.textbbox((0,0),candidate,font=typeface)[2] <= max_width:
            cur=candidate
        else:
            if cur: lines.append(cur);cur=''
            if draw.textbbox((0,0),word,font=typeface)[2] <= max_width:
                cur=word
            else:
                part=''
                for ch in word:
                    if draw.textbbox((0,0),part+ch,font=typeface)[2] <= max_width: part+=ch
                    else:
                        if part: lines.append(part)
                        part=ch
                cur=part
    if cur: lines.append(cur)
    return lines or ['']


def fit_text(draw, text, xy, max_w, max_h, size=28, min_size=15, bold=False, semi=False, color='#17202D', max_lines=None, leading=1.16):
    raw=str(text or '')
    for s in range(size,min_size-1,-1):
        f=font(s,bold,semi)
        lines=[]
        for line in raw.splitlines() or ['']:
            lines.extend(wrap_line(draw,line,f,max_w))
        height=len(lines)*s*leading
        if (max_lines is None or len(lines)<=max_lines) and height<=max_h:
            break
    else:
        s=min_size;f=font(s,bold,semi)
        lines=[]
        for line in raw.splitlines() or ['']:
            lines.extend(wrap_line(draw,line,f,max_w))
        max_fit=max(1,int(max_h/(s*leading)))
        if max_lines: max_fit=min(max_fit,max_lines)
        lines=lines[:max_fit]
        if lines:
            last=lines[-1]
            while last and draw.textbbox((0,0),last+'…',font=f)[2]>max_w:last=last[:-1]
            if len(raw)>len(' '.join(lines)): lines[-1]=last.rstrip()+'…'
    y=float(xy[1]);step=s*leading
    for line in lines:
        draw.text((int(xy[0]),int(y)),line,font=f,fill=color,stroke_width=0)
        y+=step
    return int(y)


def label(draw,text,xy,size=22,color='#22252C',bold=False,anchor=None):
    draw.text(xy,str(text),font=font(size,bold),fill=color,anchor=anchor)


def section_bar(im,xywh,title,accent,dark='#252934',small=False):
    x,y,w,h=xywh;d=ImageDraw.Draw(im)
    # colored slash -> dark pill
    d.polygon([(x,y),(x+w-16,y),(x+w,y+h*.18),(x+w-20,y+h),(x,y+h)],fill=dark)
    d.polygon([(x+1,y),(x+80,y),(x+65,y+h),(x-12,y+h)],fill=accent)
    d.line([(x+86,y+2),(x+64,y+h-2)],fill='#FFFFFF',width=4)
    fit_text(d,title,(x+100,y+int(h*.16)),w-125,h*.78,size=24 if small else 30,min_size=17,bold=True,color='#FFFFFF',max_lines=1)


def accent_chip(d,x,y,w,h,text,accent,dark=False):
    fill='#2D323D' if dark else '#FFFFFF'
    rounded(d,(x,y,x+w,y+h),14,fill)
    d.ellipse((x+16,y+14,x+41,y+39),fill=accent)
    fit_text(d,text,(x+54,y+12),w-68,h-19,size=21,min_size=14,bold=True,max_lines=2)


def gradient_bg(size,style,accent):
    w,h=size
    im=Image.new('RGB',size,(240,243,247)); px=im.load()
    base_a=(250,251,253) if style!='graphite' else (242,244,247)
    base_b=(226,232,238)
    for y in range(h):
        t=y/h
        c=blend(base_a,base_b,min(1,t*.94))
        for x in range(w):
            f=(x/w)*.035
            px[x,y]=tuple(max(0,min(255,int(v-16*f))) for v in c)
    d=ImageDraw.Draw(im,'RGBA')
    d.polygon([(w*.83,0),(w,0),(w*.7,h*.24),(w*.55,h*.24)],fill=rgba('#FFFFFF',95))
    d.polygon([(0,h*.18),(w*.04,0),(w*.10,0),(0,h*.45)],fill=rgba('#FFFFFF',120))
    d.line([(0,h*.97),(w*.85,h*.12)],fill=rgba(accent,15),width=20)
    return im


def load_image(data: Optional[bytes]):
    if not data:return None
    try:
        img=Image.open(io.BytesIO(data))
        img.load()
        if img.width>10000 or img.height>10000: raise ValueError('Слишком крупное изображение')
        return ImageOps.exif_transpose(img).convert('RGBA')
    except Exception:
        return None


def photo_box(im, img, box, accent, atmosphere=None, preserve=True, image_label=None):
    x,y,w,h=map(int,box)
    d=ImageDraw.Draw(im)
    rounded(d,(x+3,y+6,x+w+3,y+h+8),26,fill='#C4CDD8')
    rounded(d,(x,y,x+w,y+h),26,fill='#FBFCFE',outline='#FFFFFF',width=5)
    # atmosphere covers inset, no model-generated typography
    ix,iy,iw,ih=x+8,y+8,w-16,h-16
    patch=Image.new('RGBA',(iw,ih),(247,249,251,255))
    pd=ImageDraw.Draw(patch)
    if atmosphere is not None:
        bg=ImageOps.fit(atmosphere.convert('RGB'),(iw,ih),method=Image.Resampling.LANCZOS,centering=(.5,.55)).convert('RGBA')
        veil=Image.new('RGBA',(iw,ih),(255,255,255,75))
        bg=Image.alpha_composite(bg,veil)
        patch.alpha_composite(bg)
    else:
        for j in range(ih):
            q=int(248-j*.014)
            pd.line((0,j,iw,j),fill=(q,q+1 if q<255 else 255,252,255))
        pd.polygon([(0,int(ih*.76)),(iw,int(ih*.65)),(iw,ih),(0,ih)],fill=(230,235,241,255))
    if img is not None:
        iw2,ih2=iw-20,ih-24
        # Image with transparent background: fit. Opaque photo: fit into inset to preserve equipment
        fg=ImageOps.contain(img,(iw2,ih2),method=Image.Resampling.LANCZOS)
        ax=(iw-fg.width)//2
        ay=(ih-fg.height)//2
        if preserve and img.getextrema()[3][0]==255:
            # make ordinary photos more integrated while retaining every pixel of the source image
            fd=Image.new('RGBA',(fg.width+12,fg.height+12),(255,255,255,255))
            fd.alpha_composite(fg,(6,6));fg=fd;ax-=6;ay-=6
        patch.alpha_composite(fg,(max(0,ax),max(0,ay)))
    else:
        # intentional empty state only, avoids fabricated equipment
        label(pd,'ФОТО ТЕХНИКИ',(iw//2,ih//2-12),34,'#8B96A5',True,anchor='mm')
    # rounded corners mask
    mask=Image.new('L',(iw,ih),0);ImageDraw.Draw(mask).rounded_rectangle((0,0,iw-1,ih-1),radius=20,fill=255)
    im.paste(patch,(ix,iy),mask)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((x,y,x+w,y+h),radius=26,outline='#FFFFFF',width=5)
    if image_label:
        rounded(d,(x+22,y+h-46,x+235,y+h-12),12,fill='#2B3039')
        label(d,image_label,(x+34,y+h-39),18,'#FFFFFF',True)


def photo_inset(im,detail,box):
    """Optional original second photo as a small separate unmodified evidence inset."""
    if detail is None:return
    x,y,w,h=map(int,box)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((x-4,y-4,x+w+4,y+h+4),radius=16,fill='#FFFFFF',outline='#DCE3EB',width=3)
    fg=ImageOps.fit(detail,(w,h),method=Image.Resampling.LANCZOS,centering=(.5,.5))
    mask=Image.new('L',(w,h),0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w,h),radius=13,fill=255)
    im.paste(fg.convert('RGB'),(x,y),mask)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((x,y,x+w,y+h),radius=13,outline='#FFFFFF',width=3)


def header(im,brief,logo,accent,mobile=False):
    w,h=im.size;d=ImageDraw.Draw(im)
    if mobile:
        logo_box=(38,30,250,130)
        prefix_x=302
        cat_y=38
        mod_y=87
    else:
        logo_box=(43,30,310,116)
        prefix_x=365
        cat_y=31
        mod_y=79
    if logo is not None:
        img=ImageOps.contain(logo,(logo_box[2]-logo_box[0],logo_box[3]-logo_box[1]),Image.Resampling.LANCZOS)
        im.paste(img,(logo_box[0],logo_box[1]),img if img.mode=='RGBA' else None)
    else:
        label(d,brief.get('brand','ZUBR TRAIL').upper(),(logo_box[0],logo_box[1]+19),45 if not mobile else 35,'#22252C',True)
        d.line([(logo_box[0],logo_box[3]-8),(logo_box[2]-18,logo_box[3]-8)],fill=accent,width=9)
    d.line([(prefix_x-17,35),(prefix_x-53,118 if not mobile else 147)],fill=accent,width=5)
    fit_text(d,brief.get('category','ПОЛУПРИЦЕП-ЗЕРНОВОЗ').upper(),(prefix_x,cat_y),w-prefix_x-35,44 if not mobile else 48,size=36 if not mobile else 35,min_size=23,bold=True,max_lines=1)
    fit_text(d,brief.get('model','ZubrTrail 500'),(prefix_x,mod_y),w-prefix_x-35,75,size=70 if not mobile else 70,min_size=40,bold=True,max_lines=1)
    if mobile:
        rounded(d,(38,175,w-38,215),12,fill=accent)
        fit_text(d,brief.get('slogan','Алюминиевый зерновоз, который везёт больше'),(56,182),w-112,33,size=22,min_size=16,bold=True,color='#FFFFFF',max_lines=1)
    else:
        rounded(d,(365,144,w-42,182),10,fill=accent)
        fit_text(d,brief.get('slogan','Алюминиевый зерновоз, который везёт больше'),(390,151),w-445,30,size=22,min_size=15,bold=True,color='#FFFFFF',max_lines=1)


def max_items(items,count=8):
    return [x for x in (items or []) if isinstance(x,(list,tuple)) and len(x)>=2 and str(x[0]).strip()][:count]


def tech_table(im,brief,box,accent,mobile=False):
    x,y,w,h=box;d=ImageDraw.Draw(im)
    rounded(d,(x,y,x+w,y+h),22,'#FFFFFF')
    section_bar(im,(x,y,w,47 if not mobile else 51),'Основные ТТХ',accent)
    items=max_items(brief.get('specs',[]),8 if not mobile else 8)
    if not items: items=[('Характеристики','Уточняются')]
    top=y+(55 if not mobile else 61)
    gap=2
    rh=max(31,(h-(top-y)-20)/max(1,len(items)))
    for j,(key,val) in enumerate(items):
        ly=top+j*rh
        d.rounded_rectangle((x+13,int(ly),x+w-13,int(ly+rh-gap)),radius=8,fill='#F0F3F7' if j%2==0 else '#F7F8FA')
        if mobile:
            kw=w*.51
            fit_text(d,key,(x+26,ly+7),kw-30,rh-12,size=22,min_size=15,semi=True,max_lines=2)
            fit_text(d,val,(x+kw+10,ly+7),w-kw-40,rh-12,size=23,min_size=15,bold=True,color=accent,max_lines=2)
        else:
            kw=w*.52
            fit_text(d,key,(x+24,ly+6),kw-30,rh-10,size=22,min_size=14,semi=True,max_lines=2)
            fit_text(d,val,(x+kw+6,ly+6),w-kw-38,rh-10,size=24,min_size=14,bold=True,color=accent,max_lines=2)


def benefits(im,brief,box,accent,mobile=False):
    x,y,w,h=box;d=ImageDraw.Draw(im)
    rounded(d,(x,y,x+w,y+h),22,'#FFFFFF')
    section_bar(im,(x,y,w,47),'Почему выгоднее',accent,small=True)
    arr=[str(k).strip() for k in brief.get('benefits',[]) if str(k).strip()][:4]
    while len(arr)<4:arr.append(['Выше эффективность рейса','Меньше эксплуатационные расходы','Надёжная конструкция','Выгоднее на маршруте'][len(arr)])
    gap=12
    top=y+58
    cells_w=(w-38-gap)/2
    cells_h=(h-(top-y)-24-gap)/2
    for i,text in enumerate(arr):
        col=i%2;row=i//2
        xx=x+15+col*(cells_w+gap)
        yy=top+row*(cells_h+gap)
        rounded(d,(xx,yy,xx+cells_w,yy+cells_h),15,'#F3F5F8')
        d.ellipse((xx+13,yy+12,xx+48,yy+47),fill=accent)
        label(d,'✓',(xx+22,yy+15),22,'#FFFFFF',True)
        fit_text(d,text,(xx+56,yy+11),cells_w-66,cells_h-14,size=20 if not mobile else 23,min_size=14,bold=True,max_lines=3)


def dimensions(im,brief,drawing_img,box,accent,mobile=False):
    x,y,w,h=box;d=ImageDraw.Draw(im)
    rounded(d,(x,y,x+w,y+h),22,'#FFFFFF')
    section_bar(im,(x,y,w,44 if not mobile else 47),'Габаритные размеры, мм',accent,small=True)
    specs=max_items(brief.get('dimensions',[]),5)
    if mobile:
        ix=x+14;iy=y+57;iw=370;ih=h-69
        text_x=x+400;text_w=w-425
    else:
        ix=x+18;iy=y+54;iw=300;ih=h-62
        text_x=x+328;text_w=w-346
    if drawing_img is not None:
        dr=ImageOps.contain(drawing_img,(int(iw),int(ih)),Image.Resampling.LANCZOS)
        background=Image.new('RGBA',(int(iw),int(ih)),(243,246,249,255))
        background.alpha_composite(dr,((int(iw)-dr.width)//2,(int(ih)-dr.height)//2))
        im.paste(background,(int(ix),int(iy)))
    else:
        d.line((ix+15,iy+ih*.65,ix+iw-15,iy+ih*.65),fill='#6B7480',width=3)
        d.line((ix+25,iy+ih*.2,ix+25,iy+ih*.85),fill='#6B7480',width=3)
        d.line((ix+iw-25,iy+ih*.2,ix+iw-25,iy+ih*.85),fill='#6B7480',width=3)
        d.line((ix+25,iy+ih*.24,ix+iw-25,iy+ih*.24),fill=accent,width=3)
        for i in range(3):
            cx=ix+iw*.42+i*iw*.15
            d.ellipse((cx-10,iy+ih*.58,cx+10,iy+ih*.8),outline='#556270',width=3)
        # No artificial dimensions are drawn; this placeholder is decorative only.
    if not specs:specs=[('Длина','—'),('Ширина','—'),('Высота','—')]
    dy=(h-59)/len(specs)
    for i,(k,v) in enumerate(specs):
        yy=y+53+dy*i
        fit_text(d,k,(text_x,yy+3),text_w*.58-5,dy-3,size=18 if not mobile else 20,min_size=13,semi=True,max_lines=1)
        fit_text(d,v,(text_x+text_w*.61,yy+3),text_w*.38,dy-3,size=21 if not mobile else 22,min_size=14,bold=True,color=accent,max_lines=1)
        if i<len(specs)-1:d.line((text_x,yy+dy-2,text_x+text_w,yy+dy-2),fill='#E7EAEE',width=1)


def money(value,currency='Br'):
    try:
        n=float(str(value).replace(' ','').replace(',','.'))
        if math.isnan(n) or math.isinf(n):return '—'
        s=f'{n:,.0f}'.replace(',',' ')
        return s+' '+currency
    except Exception:return '—'


def compute_roi(brief):
    roi=brief.get('roi') or {}
    try:
        payload=float(str(roi.get('extra_payload','0')).replace(',','.'))
        km=float(str(roi.get('distance','0')).replace(',','.'))
        rate=float(str(roi.get('rate','0')).replace(',','.'))
        trips=float(str(roi.get('trips','0')).replace(',','.'))
        years=float(str(roi.get('years','5')).replace(',','.'))
        steel=float(str(roi.get('baseline_price','0')).replace(',','.'))
        current=float(str(brief.get('price','0')).replace(' ','').replace(',','.'))
        if not all(math.isfinite(x) for x in (payload,km,rate,trips,years,steel,current)) or min(payload,km,rate,trips,years,steel,current)<0:
            return None
        annual=payload*km*rate*trips
        gross=annual*years
        premium=current-steel if steel else 0
        net=gross-premium
        payback=(premium/annual) if annual>0 and premium>0 else None
        return {'annual':annual,'gross':gross,'premium':premium,'net':net,'payback':payback,'year':years,'per_trip':payload*km*rate,'trips':trips,'distance':km,'payload':payload}
    except Exception:return None


def roi_panel(im,brief,box,accent,mobile=False):
    x,y,w,h=box;d=ImageDraw.Draw(im)
    rounded(d,(x,y,x+w,y+h),20,'#FFFFFF')
    if not brief.get('show_roi',True):
        section_bar(im,(x,y,w,45),'Наши преимущества',accent,small=True)
        fit_text(d,brief.get('slogan',''),(x+27,y+58),w-60,h-68,size=28,min_size=17,bold=True,max_lines=2)
        return
    roi=compute_roi(brief)
    section_bar(im,(x,y,w,45),'Экономический эффект — расчётный сценарий',accent,small=True)
    if not roi:
        fit_text(d,'Заполните исходные данные для экономического расчёта',(x+24,y+58),w-45,h-62,size=22,min_size=15,semi=True)
        return
    if not mobile and h<110:
        cards=[('НА 1 РЕЙС',money(roi['per_trip'])),('РЕЙСОВ / ГОД',str(int(roi['trips']))),('ДОХОД В ГОД',money(roi['annual'])),('БАЛАНС '+str(int(roi['year']))+' ЛЕТ',money(roi['net']))]
        gap=11;cw=(w-36-gap*3)/4
        for i,(cap,val) in enumerate(cards):
            xx=x+18+i*(cw+gap)
            rounded(d,(xx,y+43,xx+cw,y+h-8),9,'#F2F4F7')
            label(d,cap,(xx+12,y+47),13,'#67717C',True)
            fit_text(d,val,(xx+12,y+63),cw-19,23,size=20,min_size=15,bold=True,color=accent,max_lines=1)
        return
    if mobile:
        cards=[('В ГОД',money(roi['annual'])),('ЗА '+str(int(roi['year']))+' ЛЕТ',money(roi['gross'])),('БАЛАНС',money(roi['net']))]
        gap=13;cw=(w-34-gap*2)/3
        for i,(cap,val) in enumerate(cards):
            xx=x+17+i*(cw+gap)
            rounded(d,(xx,y+57,xx+cw,y+h-13),12,'#F3F5F8')
            label(d,cap,(xx+12,y+66),16,'#6C7582',True)
            fit_text(d,val,(xx+12,y+90),cw-22,45,size=29,min_size=18,bold=True,color=accent,max_lines=1)
    else:
        cards=[('НА 1 РЕЙС',money(roi['per_trip'])),('РЕЙСОВ / ГОД',str(int(roi['trips']))),('ДОХОД В ГОД',money(roi['annual'])),('БАЛАНС '+str(int(roi['year']))+' ЛЕТ',money(roi['net']))]
        gap=14;cw=(w-36-gap*3)/4
        for i,(cap,val) in enumerate(cards):
            xx=x+18+i*(cw+gap)
            rounded(d,(xx,y+56,xx+cw,y+h-12),12,'#F2F4F7')
            label(d,cap,(xx+12,y+65),16,'#67717C',True)
            fit_text(d,val,(xx+12,y+91),cw-18,39,size=28,min_size=16,bold=True,color=accent,max_lines=1)


def price_footer(im,brief,accent,mobile=False):
    w,h=im.size;d=ImageDraw.Draw(im)
    y=h-(197 if mobile else 129)
    price=str(brief.get('price','')).strip()
    currency=str(brief.get('currency','Br')).strip() or 'Br'
    if price:
        d.polygon([(45,y+4),(w-43,y+4),(w-15,y+23),(w-61,y+90),(23,y+90),(12,y+72)],fill=accent)
        d.ellipse((77,y+36,117,y+68),outline='#FFFFFF',width=5)
        d.ellipse((85,y+25,125,y+57),outline='#FFFFFF',width=5)
        fit_text(d,'Цена: '+money(price,currency)+((' с НДС') if brief.get('vat',True) else ''),(160,y+25),w-205,58,size=55 if mobile else 53,min_size=28,bold=True,color='#FFFFFF',max_lines=1)
    else:
        d.polygon([(45,y+4),(w-43,y+4),(w-15,y+25),(w-61,y+90),(23,y+90),(12,y+72)],fill=accent)
        fit_text(d,'ЗАПРОСИТЕ ИНДИВИДУАЛЬНОЕ ПРЕДЛОЖЕНИЕ',(55,y+27),w-102,53,size=33,min_size=20,bold=True,color='#FFFFFF',max_lines=1)
    foot_y=h-(93 if mobile else 49)
    d.rectangle((0,foot_y,w,h),fill='#20242D')
    d.polygon([(0,foot_y),(130,foot_y),(101,h),(0,h)],fill=accent)
    phones=[str(x).strip() for x in brief.get('phones',[]) if str(x).strip()][:2]
    if mobile:
        label(d,'СВЯЗАТЬСЯ С НАМИ',(155,foot_y+8),25,'#FFFFFF',True)
        contact='     •     '.join(phones) if phones else 'Контакты — по запросу'
        fit_text(d,contact,(160,foot_y+46),w-190,42,size=26,min_size=19,bold=True,color='#FFFFFF',max_lines=1)
    else:
        label(d,'СВЯЖИТЕСЬ С НАМИ',(154,foot_y+10),25,'#FFFFFF',True)
        contact='  /  '.join(phones) if phones else 'Контакты — по запросу'
        fit_text(d,contact,(514,foot_y+10),w-550,37,size=24,min_size=17,bold=True,color='#FFFFFF',max_lines=1)


def render_poster(brief:dict,format_key:str,hero:Optional[Image.Image]=None,detail:Optional[Image.Image]=None,logo:Optional[Image.Image]=None,drawing:Optional[Image.Image]=None,backdrop:Optional[Image.Image]=None,ai_product=False):
    if format_key=='4x3':
        im=gradient_bg((1440,1080),brief.get('style','industrial'),valid_hex(brief.get('accent','#E31B26')))
        accent=valid_hex(brief.get('accent','#E31B26'))
        header(im,brief,logo,accent,mobile=False)
        photo_box(im,hero,(37,199,887,309),accent,backdrop,image_label='AI-ВИЗУАЛИЗАЦИЯ' if ai_product else None)
        photo_inset(im,detail,(708,380,192,111))
        d=ImageDraw.Draw(im)
        # right hero benefits
        for i,text in enumerate([str(x) for x in brief.get('hero_claims',[])][:4]):
            xx,yy=938,199+i*79
            d.polygon([(xx+22,yy),(1403,yy),(1380,yy+70),(xx,yy+70)],fill='#FFFFFF')
            d.polygon([(xx+12,yy+6),(xx+98,yy+6),(xx+77,yy+64),(xx-10,yy+64)],fill=accent)
            label(d,['✓','+','✓','↗'][i],(xx+30,yy+19),32,'#FFFFFF',True)
            fit_text(d,text,(xx+110,yy+14),345,55,size=27,min_size=17,bold=True,max_lines=2)
        tech_table(im,brief,(37,524,572,327),accent)
        benefits(im,brief,(625,524,778,179),accent)
        dimensions(im,brief,drawing,(625,716,778,135),accent)
        roi_panel(im,brief,(37,862,1366,86),accent)
        price_footer(im,brief,accent)
        return im
    if format_key=='9x16':
        im=gradient_bg((1080,1920),brief.get('style','industrial'),valid_hex(brief.get('accent','#E31B26')))
        accent=valid_hex(brief.get('accent','#E31B26'))
        header(im,brief,logo,accent,mobile=True)
        photo_box(im,hero,(38,230,1004,550),accent,backdrop,image_label='AI-ВИЗУАЛИЗАЦИЯ' if ai_product else None)
        photo_inset(im,detail,(797,620,220,133))
        # claims line, 4 mini cards in top of benefits section for visual hierarchy
        d=ImageDraw.Draw(im)
        claims=[str(k) for k in brief.get('hero_claims',[])][:4]
        for i,text in enumerate(claims):
            xx=42+(i%2)*510; yy=794+(i//2)*72
            rounded(d,(xx,yy,xx+494,yy+64),16,'#FFFFFF')
            rounded(d,(xx+8,yy+8,xx+65,yy+56),13,accent)
            label(d,['✓','+','✓','↗'][i],(xx+24,yy+14),27,'#FFFFFF',True)
            fit_text(d,text,(xx+82,yy+13),398,50,size=24,min_size=16,bold=True,max_lines=2)
        tech_table(im,brief,(38,943,1004,335),accent,mobile=True)
        benefits(im,brief,(38,1292,1004,211),accent,mobile=True)
        dimensions(im,brief,drawing,(38,1515,1004,140),accent,mobile=True)
        # compact ROI ribbon before price, do not overlap it
        roi=compute_roi(brief)
        if brief.get('show_roi',True) and roi:
            rounded(d,(38,1662,1042,1714),13,'#22262F')
            fit_text(d,f"РАСЧЁТ ЗА {int(roi['year'])} ЛЕТ: {money(roi['gross'])}  •  БАЛАНС: {money(roi['net'])}",(58,1675),970,29,size=21,min_size=14,bold=True,color='#FFFFFF',max_lines=1)
        price_footer(im,brief,accent,mobile=True)
        return im
    raise ValueError('Unsupported format')


def image_bytes(im,format='PNG'):
    stream=io.BytesIO();im.convert('RGB').save(stream,format=format,optimize=True);return stream.getvalue()


def default_brief():
    return {
        'brand':'ZUBR TRAIL','category':'ПОЛУПРИЦЕП-ЗЕРНОВОЗ','model':'ZubrTrail 500',
        'slogan':'Алюминиевый зерновоз, который везёт больше в каждом рейсе',
        'style':'industrial','accent':'#E31B26','design_notes':'Красно-бело-чёрная промышленная инфографика, контрастные плашки','design_actions':'',
        'hero_claims':['Легче на 2,5 т','Больше полезной нагрузки','Устойчив к коррозии','Выше доходность рейсов'],
        'specs':[['Грузоподъёмность','44 т'],['Полная масса','52,5 т'],['Собственный вес','8,3 т'],['Объём кузова','55 м³'],['Кузов','Алюминиевый сплав'],['Оси','4 оси SAF'],['Тормоза','Дисковые, WABCO'],['Колёса','Легкосплавные']],
        'benefits':['Меньше собственный вес','Больше груз за один рейс','Защита от коррозии','Экономия на перевозках'],
        'dimensions':[['Длина','12 360'],['Ширина','2 550'],['Высота','до 3 650']],
        'price':'229998','currency':'Br','vat':True,'phones':['+375 (225) 72-01-03','+375 (29) 652-00-45'],
        'show_roi':True,'roi':{'extra_payload':2.5,'distance':300,'rate':0.19,'trips':240,'years':5,'baseline_price':149499},
    }
