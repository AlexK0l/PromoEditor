"""High-impact industrial campaign layout inspired by a supplied visual reference.

All visible claims, specifications, prices and contacts come ONLY from the
validated form. Missing facts DO NOT become synthetic marketing statements.
All texts and shapes are editable SVG elements; photos, optional AI scene,
drawings and logo remain independent, replaceable bitmap elements.

This module imports Scene only when its public renderer is invoked, avoiding
circular import with editable_export.create_editable_svg.
"""
from __future__ import annotations

import math
import re
from PIL import Image, ImageChops, ImageOps


def _lines(brief,key,limit=7):
    """Only explicitly supplied, nonempty fact rows."""
    out=[]
    for item in (brief.get(key) or [])[:limit]:
        if isinstance(item,(list,tuple)) and len(item)>=2:
            left=str(item[0]).strip()[:90]
            right=str(item[1]).strip()[:160]
            if left and right:out.append((left,right))
    return out


def _benefits(brief):
    """Never invent advantages just to fill a template."""
    result=[]
    for value in (brief.get('benefits') or [])+(brief.get('hero_claims') or []):
        text=str(value).strip()[:150]
        if text and text.casefold() not in {x.casefold() for x in result}:
            result.append(text)
        if len(result)>=6:break
    return result


def _trim_outer_whitespace(source):
    """Conservatively trim empty white/transparent photographic borders.

    Cropping is presentation-only: the resulting PNG is still one editable
    bitmap in CorelDRAW. Do not remove interior white product paint or run
    an unreviewed object segmentation model.
    """
    image=ImageOps.exif_transpose(source).copy()
    if image.mode in ('RGBA','LA') and image.getextrema()[-1][0]<250:
        alpha=image.getchannel('A')
        bbox=alpha.point(lambda px:255 if px>10 else 0).getbbox()
        if bbox and bbox!=(0,0,image.width,image.height):
            margin=max(3,round(min(image.size)*.025))
            x0,y0,x1,y1=bbox
            image=image.crop((max(0,x0-margin),max(0,y0-margin),
                              min(image.width,x1+margin),min(image.height,y1+margin)))
        return image
    if min(image.size)<70:return image
    thumb=image.convert('RGB')
    thumb.thumbnail((660,660),Image.Resampling.LANCZOS)
    w,h=thumb.size
    samples=[thumb.getpixel((x,y)) for x,y in (
        (0,0),(w//2,0),(w-1,0),(0,h//2),(w-1,h//2),
        (0,h-1),(w//2,h-1),(w-1,h-1))]
    # A real photo or dark logo with a meaningful backdrop must not be cropped.
    if sum(all(channel>=239 for channel in px) for px in samples)<6:
        return image
    diff=ImageChops.difference(thumb,Image.new('RGB',thumb.size,'white')).convert('L')
    mask=diff.point(lambda px:255 if px>31 else 0)
    box=mask.getbbox()
    if not box:return image
    x0,y0,x1,y1=box
    if (x1-x0)>w*.96 and (y1-y0)>h*.96:return image
    if (x1-x0)<w*.16 or (y1-y0)<h*.13:return image
    # Scale crop bounds back to source pixels. Retain safe margins.
    sx=image.width/w;sy=image.height/h
    margin=max(6,int(min(image.size)*.028))
    area=(max(0,int(x0*sx)-margin),max(0,int(y0*sy)-margin),
          min(image.width,int(math.ceil(x1*sx))+margin),
          min(image.height,int(math.ceil(y1*sy))+margin))
    return image.crop(area)


def _photo(scene,photo,x,y,w,h,label,layer='photos',trim=False,cover=False):
    if photo is None:return None
    img=_trim_outer_whitespace(photo) if trim else photo
    node=scene.bitmap(layer,img,x,y,w,h,label)
    if node is not None and cover:
        node.set('preserveAspectRatio','xMidYMid slice')
    return node


def _rule(scene,layer,x1,y1,x2,y2,color,width=3,ident='accent-rule'):
    return scene.el(layer,'line',ident,{
        'x1':x1,'y1':y1,'x2':x2,'y2':y2,
        'stroke':color,'stroke-width':width,'stroke-linecap':'round'
    })


def _check(scene,layer,x,y,size,color,ident):
    scene.el(layer,'path',ident,{
        'd':f'M {x} {y+size*.46} L {x+size*.34} {y+size*.82} '
            f'L {x+size} {y+size*.08}',
        'fill':'none','stroke':color,'stroke-width':max(2.5,size*.14),
        'stroke-linecap':'round','stroke-linejoin':'round'
    })


def _spec_symbol(scene,x,y,index,accent):
    """Seven generic editorial pictograms: none claims specific certification."""
    cx=x+29;cy=y+29;layer='specs'
    scene.rect(layer,x,y,60,60,accent,rad=9,ident=f'spec-icon-badge-{index}')
    white='#FFFFFF'
    symbol=index%7
    if symbol==0:
        scene.rect(layer,cx-15,cy-13,30,26,'none',rad=2,ident='symbol-box')
        scene.el(layer,'rect','symbol-outline',{'x':cx-15,'y':cy-13,'width':30,'height':26,
                 'fill':'none','stroke':white,'stroke-width':3})
        _rule(scene,layer,cx,cy-13,cx,cy+13,white,2,'symbol-center')
    elif symbol==1:
        scene.el(layer,'circle','symbol-ring',{'cx':cx,'cy':cy,'r':17,
                 'fill':'none','stroke':white,'stroke-width':3})
        scene.text(layer,'KG',cx-13,cy-10,27,23,14,12,white,True,'symbol-kg',1)
    elif symbol==2:
        scene.el(layer,'path','symbol-truck',{'d':f'M {cx-21} {cy-9} h 29 v 22 h -29 z '
                 f'M {cx+8} {cy-3} h 10 l 6 8 v 8 h -16 z','fill':'none',
                 'stroke':white,'stroke-width':3,'stroke-linejoin':'round'})
        for dx in (-12,14):
            scene.el(layer,'circle','symbol-wheel',{'cx':cx+dx,'cy':cy+15,'r':4,'fill':white})
    elif symbol==3:
        scene.el(layer,'circle','symbol-disc',{'cx':cx,'cy':cy+3,'r':16,
                 'fill':'none','stroke':white,'stroke-width':3})
        _rule(scene,layer,cx-15,cy-14,cx+15,cy-14,white,3,'symbol-handle')
        _rule(scene,layer,cx-12,cy+3,cx+12,cy+3,white,3,'symbol-axis')
    elif symbol==4:
        _rule(scene,layer,cx-22,cy+1,cx+22,cy+1,white,4,'symbol-axle')
        for dx in (-15,0,15):
            scene.el(layer,'circle','symbol-axle-wheel',{'cx':cx+dx,'cy':cy+1,'r':5,
                    'fill':'none','stroke':white,'stroke-width':3})
    elif symbol==5:
        scene.el(layer,'circle','symbol-gear-outer',{'cx':cx,'cy':cy,'r':18,
                 'fill':'none','stroke':white,'stroke-width':3})
        scene.el(layer,'circle','symbol-gear-core',{'cx':cx,'cy':cy,'r':6,
                 'fill':'none','stroke':white,'stroke-width':3})
        for dx,dy in ((0,-24),(0,24),(-24,0),(24,0)):
            _rule(scene,layer,cx+dx*.67,cy+dy*.67,cx+dx,cy+dy,white,3,'symbol-gear-spoke')
    else:
        scene.el(layer,'path','symbol-shield',{'d':f'M {cx} {cy-23} L {cx+19} {cy-15} '
                 f'L {cx+15} {cy+8} L {cx} {cy+21} L {cx-15} {cy+8} '
                 f'L {cx-19} {cy-15} Z','fill':'none','stroke':white,'stroke-width':3})
        _check(scene,layer,cx-10,cy-6,20,white,'symbol-shield-check')


def _header(scene,brief,logo,accent,portrait):
    w=scene.w
    hh=265 if portrait else 180
    scene.rect('decor',0,0,w,hh,accent,ident='campaign-header')
    scene.polygon('decor',[(w*.78,0),(w*.83,0),(w*.73,hh),
                           (w*.68,hh)],'#FFFFFF',ident='header-diagonal',opacity='.18')
    scene.polygon('decor',[(w*.91,0),(w*.93,0),(w*.83,hh),
                           (w*.81,hh)],'#FFFFFF',ident='header-stripe')
    scene.polygon('decor',[(w*.95,0),(w*.97,0),(w*.87,hh),
                           (w*.85,hh)],'#FFFFFF',ident='header-stripe-2')
    if logo is not None:
        box=(34,28,180,128) if portrait else (35,20,195,115)
        x,y,bw,bh=box
        scene.rect('logo',x,y,bw,bh,'#FFFFFF',rad=17,ident='logo-contrast-card')
        _photo(scene,logo,x+9,y+9,bw-18,bh-18,'original-logo',layer='logo',trim=True)
    elif str(brief.get('brand') or '').strip():
        scene.text('logo',str(brief['brand']).strip().upper(),35,40,
                   210 if portrait else 225,115,35,18,'#FFFFFF',True,'brand',2)
    sx=246 if portrait else 266
    _rule(scene,'heading',sx,34,sx-37,145 if portrait else 135,'#FFFFFF',6,'header-divider')
    cat=str(brief.get('category') or 'ПРОМЫШЛЕННОЕ ОБОРУДОВАНИЕ').strip().upper()
    model=str(brief.get('model') or 'Товар').strip()
    scene.text('heading',cat,sx+25,25,w-sx-95,47,31 if portrait else 36,
               21,'#FFFFFF',True,'category',1)
    scene.text('heading',model,sx+24,70,w-sx-72,112 if portrait else 98,
               79 if portrait else 93,34,'#FFFFFF',True,'model',1)
    slogan=str(brief.get('slogan') or '').strip()
    if slogan:
        y=202 if portrait else 151
        scene.rect('heading',sx+8,y,w-sx-55,49,'#FFFFFF',rad=10,ident='slogan-banner')
        scene.text('heading',slogan,sx+26,y+4,w-sx-90,42,27 if portrait else 29,
                   16,accent,True,'slogan',1)
    return hh


def _hero(scene,hero,detail,backdrop,ai_product,accent,x,y,w,h,claims):
    # A single large original product image leads the layout.
    scene.rect('photos',x,y,w,h,'#F1F4F7',rad=16,ident='hero-stage')
    scene.polygon('photos',[(x,y+h*.58),(x+w,y+h*.41),(x+w,y+h),
                            (x,y+h)],'#E4E8ED',ident='hero-floor')
    scene.polygon('photos',[(x+w*.84,y),(x+w,y),
                            (x+w*.56,y+h)],'#FFFFFF',opacity='.48',ident='hero-light-beam')
    if backdrop is not None and not ai_product:
        _photo(scene,backdrop,x+2,y+2,w-4,h-4,'ai-scene',cover=True)
        # Soft readability wash on top of an AI atmosphere.
        scene.rect('photos',x+2,y+2,w-4,h-4,'#FFFFFF',
                   opacity='.12',ident='ai-scene-wash')
    source=backdrop if ai_product else hero
    if source is not None:
        _photo(scene,source,x+10,y+12,w-20,h-24,
               'ai-product-bitmap' if ai_product else 'original-product-photo',
               trim=not ai_product)
        if ai_product:
            scene.rect('claims',x+23,y+h-49,238,34,'#27303B',rad=7,ident='ai-disclosure-bg')
            scene.text('claims','AI-ВИЗУАЛИЗАЦИЯ',x+34,y+h-46,215,29,
                       17,14,'#FFFFFF',True,'ai-disclosure',1)
    # A second real image becomes a deliberately smaller, separated photo.
    if detail is not None:
        tw=min(290,w*.37)
        th=min(163,h*.36)
        px=x+19;py=y+h-th-23
        scene.rect('photos',px-6,py-6,tw+12,th+12,'#FFFFFF',rad=14,
                   ident='secondary-photo-card')
        _photo(scene,detail,px,py,tw,th,'detail-photo',trim=True)
        _rule(scene,'claims',px,py+th+5,px+tw,py+th+5,accent,5,'detail-photo-accent')
    else:
        visible=[str(v).strip() for v in claims if str(v).strip()][:2]
        for i,value in enumerate(visible):
            # Claims are user-supplied, not generated. Keep clear of the center.
            py=y+h-55-i*59
            if py<y+14:break
            scene.rect('claims',x+20,py,min(w-40,440),49,'#FFFFFF',rad=9,
                       ident=f'claim-card-{i}',opacity='.94')
            scene.rect('claims',x+20,py,8,49,accent,ident=f'claim-accent-{i}')
            scene.text('claims',value,x+42,py+5,min(w-70,401),38,23,15,
                       '#223044',True,f'claim-{i}',1)


def _stat_row(scene,x,y,w,h,title,value,index,accent):
    scene.rect('specs',x,y,w,h,'#FFFFFF',rad=12,ident=f'spec-row-{index}')
    scene.el('specs','rect',f'spec-row-outline-{index}',{
        'x':x+.8,'y':y+.8,'width':w-1.6,'height':h-1.6,
        'rx':12,'fill':'none','stroke':accent,'stroke-width':1.8})
    # Dense fact lists need scalable SVG icons; never overlap adjacent rows.
    before=len(scene.groups['specs'])
    icon_left=x+7
    icon_top=y+6
    _spec_symbol(scene,icon_left,icon_top,index,accent)
    scale=min(1.0,max(.4,(h-12)/60))
    if scale<.999:
        # Preserve each icon's editable paths while scaling the group as a unit.
        transform=f'translate({round(icon_left*(1-scale),3)} {round(icon_top*(1-scale),3)}) scale({round(scale,4)})'
        for icon_part in list(scene.groups['specs'])[before:]:
            icon_part.set('transform',transform)
    else:
        dy=max(0,(h-72)/2)
        if dy:
            for icon_part in list(scene.groups['specs'])[before:]:
                icon_part.set('transform',f'translate(0 {round(dy,2)})')
    vx=x+w*.65  # reserve space for short fact values on a single line
    _rule(scene,'specs',vx-10,y+12,vx-10,y+h-12,'#E7EAF0',2,f'spec-separator-{index}')
    scene.text('specs',title,x+78,y+8,vx-x-95,h-15,
               23,13,'#17212F',True,f'spec-label-{index}',2)
    scene.text('specs',value,vx,y+7,w-(vx-x)-13,h-13,
               31,16,accent,True,f'spec-value-{index}',2)


def _specs(scene,specs,x,y,w,h,accent,portrait):
    if not specs:return
    n=len(specs)
    columns=2 if portrait and n>=2 else 1
    rows=math.ceil(n/columns)
    gap=8
    cw=(w-(columns-1)*gap)/columns
    ch=(h-(rows-1)*gap)/rows
    for index,(name,value) in enumerate(specs):
        col=index%columns;row=index//columns
        xx=x+col*(cw+gap);yy=y+row*(ch+gap)
        _stat_row(scene,xx,yy,cw,ch,name,value,index,accent)


def _dimensions(scene,dimensions,drawing,x,y,w,h,accent,portrait):
    if not dimensions and drawing is None:return
    scene.rect('dimensions',x,y,w,h,'#FFFFFF',rad=13,ident='dimension-panel')
    scene.polygon('dimensions',[(x,y),(x+min(w*.64,480),y),
                                (x+min(w*.64,480)-24,y+42),(x,y+42)],
                  accent,ident='dimension-title-ribbon')
    scene.text('dimensions','ГАБАРИТЫ И ЧЕРТЁЖ' if drawing is not None else 'ГАБАРИТНЫЕ РАЗМЕРЫ',
               x+17,y+5,min(w*.63,470)-42,35,24,14,'#FFFFFF',
               True,'dimensions-title',1)
    content_y=y+47
    if drawing is not None:
        dw=(w*.47 if portrait else w*.37)
        _photo(scene,drawing,x+12,content_y+4,dw-16,h-56,
               'original-drawing',layer='dimensions',trim=False)
        start=x+dw+12
        available=w-dw-26
    else:
        start=x+18;available=w-36
    if not dimensions:return
    n=len(dimensions)
    gap=4
    row_h=(h-55-(n-1)*gap)/n
    for index,(name,value) in enumerate(dimensions):
        row_y=content_y+index*(row_h+gap)
        if index%2==0:
            scene.rect('dimensions',start,row_y,available,row_h,'#F1F4F8',
                       rad=6,ident=f'dimension-row-{index}')
        scene.text('dimensions',name,start+8,row_y+3,available*.5-13,
                   row_h-4,21,13,'#283546',False,f'dimension-label-{index}',2)
        scene.text('dimensions',value,start+available*.52,row_y+3,
                   available*.46,row_h-4,23,13,accent,True,
                   f'dimension-value-{index}',2)


def _benefit_strip(scene,benefits,x,y,w,h,accent,portrait):
    if not benefits:return
    scene.rect('benefits',x,y,w,h,'#FFFFFF',rad=12,ident='benefits-panel')
    caption_h=36 if not portrait else 43
    caption_w=min(w*.55,530)
    scene.polygon('benefits',[(x,y),(x+caption_w,y),
                              (x+caption_w-24,y+caption_h),(x,y+caption_h)],
                  accent,ident='benefits-ribbon')
    scene.text('benefits','ПРЕИМУЩЕСТВА',x+19,y+4,caption_w-46,
               caption_h-4,24 if not portrait else 28,16,'#FFFFFF',True,
               'benefits-title',1)
    count=len(benefits)
    cols=min(3,count) if portrait else count
    rows=math.ceil(count/cols)
    usable=h-caption_h-9
    gap=5
    cw=(w-14-(cols-1)*gap)/cols
    ch=(usable-(rows-1)*gap)/rows
    for i,value in enumerate(benefits):
        cx=x+7+(i%cols)*(cw+gap)
        cy=y+caption_h+6+(i//cols)*(ch+gap)
        if i%cols:
            _rule(scene,'benefits',cx-2,cy+4,cx-2,cy+ch-4,accent,1.8,'benefit-divider')
        # An editable tick pictogram, not an unsupported factual claim.
        scene.el('benefits','circle',f'benefit-icon-{i}',{
            'cx':cx+18,'cy':cy+21,'r':13,'fill':'none',
            'stroke':accent,'stroke-width':2.5})
        _check(scene,'benefits',cx+11,cy+13,14,accent,f'benefit-check-{i}')
        scene.text('benefits',value,cx+39,cy+5,cw-42,ch-5,
                   21 if not portrait else 25,13,
                   '#17212F',True,f'benefit-copy-{i}',2)


def _roi_panel(scene,brief,x,y,w,h,accent,portrait):
    if not brief.get('show_roi'):return
    from .render import compute_roi
    data=compute_roi(brief)
    if not data:return
    metrics=[
        ('ЗА РЕЙС',f"{data['per_trip']:,.0f}".replace(',',' ')),
        ('РЕЙСОВ В ГОД',str(int(data['trips']))),
        ('ЗА ГОД',f"{data['annual']:,.0f}".replace(',',' ')),
        ('БАЛАНС',f"{data['net']:,.0f}".replace(',',' ')),
    ]
    scene.rect('roi',x,y,w,h,'#FFF4F4',rad=9,ident='roi-panel')
    cw=w/len(metrics)
    for i,(label,value) in enumerate(metrics):
        bx=x+i*cw
        if i:_rule(scene,'roi',bx,y+8,bx,y+h-8,'#F1CAD0',2,'roi-separator')
        scene.text('roi',label,bx+12,y+2,cw-23,h*.39,17,12,
                   '#5B2C31',True,f'roi-caption-{i}',1)
        scene.text('roi',value,bx+12,y+h*.39,cw-23,h*.59,26,15,
                   accent,True,f'roi-value-{i}',1)


def _format_price(text):
    value=str(text or '').strip()
    if re.fullmatch(r'[0-9 ]{1,18}',value):
        try:return f'{int(value.replace(" ","")):,}'.replace(',',' ')
        except ValueError:pass
    return value


def _cta(scene,brief,x,y,w,h,accent,portrait):
    scene.rect('contacts',x,y,w,h,accent,ident='campaign-cta')
    scene.polygon('contacts',[(w*.80,y),(w*.83,y),
                              (w*.73,y+h),(w*.70,y+h)],'#FFFFFF',
                  opacity='.12',ident='cta-slash')
    scene.polygon('contacts',[(w*.91,y),(w*.94,y),
                              (w*.84,y+h),(w*.81,y+h)],'#FFFFFF',
                  opacity='.19',ident='cta-slash-2')
    value=_format_price(brief.get('price'))
    currency=str(brief.get('currency') or '').strip()
    vat=bool(brief.get('vat',True))
    copy=(value+' '+currency+(' с НДС' if vat else '')) if value else 'ЗАПРОСИТЕ КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ'
    phones=[str(p).strip() for p in (brief.get('phones') or [])[:2] if str(p).strip()]
    if portrait:
        scene.text('price',copy,x+36,y+10,w-72,67,
                   49 if value else 35,22,'#FFFFFF',True,'price-text',2)
        if phones:
            _rule(scene,'contacts',x+35,y+89,x+w-35,y+89,'#FFFFFF',1.9,'cta-divider')
            scene.text('contacts','СВЯЖИТЕСЬ С НАМИ',x+36,y+96,355,43,
                       25,17,'#FFFFFF',True,'contact-caption',1)
            scene.text('contacts','  /  '.join(phones),x+382,y+96,w-414,48,
                       24,13,'#FFFFFF',True,'contact-values',2)
        else:
            scene.text('contacts','ПОДРОБНОСТИ ПО ЗАПРОСУ',x+36,y+102,w-70,38,
                       23,16,'#FFFFFF',True,'cta-note',1)
    else:
        available=(w*.54 if phones else w-74)
        scene.text('price',copy,x+42,y+28,available-30,h-38,
                   52 if value else 35,20,'#FFFFFF',True,'price-text',2)
        if phones:
            divider_x=x+w*.57
            _rule(scene,'contacts',divider_x,y+18,divider_x,y+h-17,
                  '#FFFFFF',2.4,'cta-divider')
            scene.text('contacts','СВЯЖИТЕСЬ С НАМИ',divider_x+23,y+17,
                       w*.40-32,35,22,15,'#FFFFFF',True,'contact-caption',1)
            for j,phone in enumerate(phones):
                scene.text('contacts',phone,divider_x+23,y+51+j*32,
                           w*.40-35,31,25,15,'#FFFFFF',True,
                           f'contact-phone-{j}',1)


def create_campaign_svg(brief,key,hero=None,detail=None,logo=None,drawing=None,
                        backdrop=None,ai_product=False):
    """Campaign-ready, source-grounded, highly editable SVG for both formats."""
    from .editable_export import Scene, _safe_color
    scene=Scene(key,brief.get('accent'),brief.get('style'))
    w,h=scene.w,scene.h
    portrait=(key=='9x16')
    accent=_safe_color(brief.get('accent'))
    # No borrowed brand logo, specs or price from a style reference.
    specs=_lines(brief,'specs',7 if not portrait else 8)
    dimensions=_lines(brief,'dimensions',4)
    benefits=_benefits(brief)
    _header(scene,brief,logo,accent,portrait)
    scene.rect('decor',0,265 if portrait else 180,w,
               h-(265 if portrait else 180),'#F6F8FC',ident='campaign-paper')
    scene.polygon('decor',[(0,h*.35),(w,h*.24),(w,h*.58),(0,h*.78)],
                  '#E9EDF4',opacity='.72',ident='campaign-ambient-band')

    bottom=1760 if portrait else 960
    content_y=282 if portrait else 202
    side=31 if portrait else 28
    gap=11
    parts=[]
    if portrait and specs:
        parts.append(('specs',420 if len(specs)>=5 else 285))
    if dimensions or drawing is not None:
        parts.append(('dimensions',198 if portrait else 136))
    if benefits:
        bh=183 if portrait and len(benefits)>3 else 151 if portrait else 126
        parts.append(('benefits',bh))
    roi_data=None
    if brief.get('show_roi'):
        from .render import compute_roi
        roi_data=compute_roi(brief)
    if roi_data:
        parts.append(('roi',93 if portrait else 72))
    reserved=sum(part_h for _,part_h in parts)+len(parts)*gap
    hero_end=bottom-reserved-12
    hero_h=hero_end-content_y
    if portrait:
        hero_x=31;hero_w=w-62
        _hero(scene,hero,detail,backdrop,ai_product,accent,hero_x,content_y,
              hero_w,hero_h,brief.get('hero_claims') or [])
    else:
        has_stats=bool(specs)
        hero_x=28
        hero_w=900 if has_stats else w-56
        _hero(scene,hero,detail,backdrop,ai_product,accent,hero_x,content_y,
              hero_w,hero_h,brief.get('hero_claims') or [])
        if has_stats:
            _specs(scene,specs,hero_x+hero_w+15,content_y,
                   w-hero_x-hero_w-42,hero_h,accent,False)
    cursor=hero_end+gap
    for kind,part_h in parts:
        if kind=='specs':
            _specs(scene,specs,side,cursor,w-2*side,part_h,accent,True)
        elif kind=='dimensions':
            _dimensions(scene,dimensions,drawing,side,cursor,w-2*side,
                        part_h,accent,portrait)
        elif kind=='benefits':
            _benefit_strip(scene,benefits,side,cursor,w-2*side,part_h,
                           accent,portrait)
        elif kind=='roi':
            _roi_panel(scene,brief,side,cursor,w-2*side,part_h,accent,portrait)
        cursor+=part_h+gap
    _cta(scene,brief,0,bottom,w,h-bottom,accent,portrait)
    return scene.export()
