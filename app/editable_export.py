"""One editable SVG scene per aspect; PNG/JPEG are rendered from this SAME scene.

CorelDRAW imports vector shapes, editable text, named groups, and independent
embedded bitmaps. Pixels INSIDE a photo or AI-generated bitmap are not vectors.
No external SVG resources, SVG scripts or untrusted user-provided SVG accepted.
"""
from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageFont

NS="http://www.w3.org/2000/svg"
XLINK="http://www.w3.org/1999/xlink"
INK="http://www.inkscape.org/namespaces/inkscape"
ET.register_namespace("",NS)
ET.register_namespace("xlink",XLINK)
ET.register_namespace("inkscape",INK)
SIZES={"4x3":(1440,1080),"9x16":(1080,1920)}
STYLES={
    "industrial":"светлая индустриальная инфографика, акцентные плашки, чистый фон",
    "graphite":"премиальный графитовый промышленный дизайн, чистая типографика",
    "minimal":"воздушный минималистичный дизайн с выразительными заголовками",
}


def build_promo_prompt(brief:dict)->str:
    """Free deterministic prompt from the exact validated brief, reviewable by user."""
    name=str(brief.get("model","")).strip()
    if not name:raise ValueError("Сначала укажите модель товара.")
    def field(key,limit=500):
        return " ".join(str(brief.get(key) or "").split())[:limit] or "не указано"
    def rows(key):
        result=[]
        for p in (brief.get(key) or [])[:12]:
            if isinstance(p,(tuple,list)) and len(p)>1 and str(p[0]).strip():
                result.append(str(p[0])[:90]+": "+str(p[1])[:160])
        return "; ".join(result) or "не указаны"
    def items(key,limit=8):
        return "; ".join(str(v)[:160] for v in (brief.get(key) or [])[:limit]) or "не указаны"
    lines=[
        "ЗАДАНИЕ: профессиональный рекламный макет промышленного товара для B2B-клиентов.",
        f"Товар: {field('model',80)}. Бренд: {field('brand',70)}. Категория: {field('category',100)}.",
        f"Основной рекламный тезис: {field('slogan',250)}.",
        f"Ключевые утверждения: {items('hero_claims',4)}.",
        f"Преимущества (публиковать только данные формы): {items('benefits')}.",
        f"Технические характеристики (дословно): {rows('specs')}.",
        f"Габариты (дословно): {rows('dimensions')}.",
        f"Цена: {field('price',30)} {field('currency',12)}. НДС: {'да' if brief.get('vat',True) else 'нет'}.",
        f"Контакты: {items('phones',2)}.",
        f"Стиль: {STYLES.get(brief.get('style'),STYLES['industrial'])}. Акцент: {field('accent',7)}.",
        f"Пожелания: {field('design_notes',1200)}.",
        f"Дополнительные действия с дизайном: {field('design_actions',1200)}.",
        "Горизонтальный макет: 1440×1080 (4:3). Вертикальный: 1080×1920 (9:16).",
        "Обязательные независимые элементы: фон; фото товара; логотип; "
        "заголовки; тезисы; ТТХ; графика; габариты; цена; контакты.",
        "Не придумывать характеристики, факты, цены, телефоны, лицензии и брендовые знаки.",
        "Оригинальные фотографии и логотипы должны остаться неизменными.",
        "При OpenAI генерировать ТОЛЬКО фото-сцену/атмосферу без надписей и логотипов. "
        "Весь подтверждённый текст набирается отдельными объектами.",
        "Экспорт: для каждого размера PNG, JPEG и редактируемый SVG для CorelDRAW.",
    ]
    return "\n".join(lines)[:8000]


def _safe_color(color):
    return color.upper() if isinstance(color,str) and re.fullmatch(r"#[A-Fa-f0-9]{6}",color) else "#E31B26"


def _font(size,bold=False):
    candidates=[
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:return ImageFont.truetype(path,int(size))
        except OSError:pass
    return ImageFont.load_default()


def _wrap(text,width,size,bold):
    f=_font(size,bold)
    result=[]
    for paragraph in str(text).replace("\r","").split("\n"):
        words=paragraph.split()
        line=""
        for word in words:
            candidate=(line+" "+word).strip()
            if line and f.getlength(candidate)>width:
                result.append(line)
                line=word
            else:line=candidate
            while line and f.getlength(line)>width:
                n=len(line)
                while n>1 and f.getlength(line[:n]+"…")>width:n-=1
                result.append(line[:n]+"…")
                line=line[n:]
        if line:result.append(line)
    return result or [" "]


class Scene:
    def __init__(self,key,accent,style):
        if key not in SIZES:raise ValueError("Неизвестное соотношение сторон.")
        self.w,self.h=SIZES[key]
        self.accent=_safe_color(accent)
        self.i=0
        self.root=ET.Element(f"{{{NS}}}svg",{
            "version":"1.1","width":f"{self.w}px","height":f"{self.h}px",
            "viewBox":f"0 0 {self.w} {self.h}"})
        defs=ET.SubElement(self.root,f"{{{NS}}}defs")
        grad=ET.SubElement(defs,f"{{{NS}}}linearGradient",{
            "id":"promo-gradient","x1":"0","x2":"0","y1":"0","y2":"1"})
        top,end=("#edf1f6","#dce5ee") if style=="graphite" else ("#fafbfd","#e2e9f1")
        ET.SubElement(grad,f"{{{NS}}}stop",{"offset":"0%","stop-color":top})
        ET.SubElement(grad,f"{{{NS}}}stop",{"offset":"100%","stop-color":end})
        self.groups={}
        titles={
            "background":"01 Фон","decor":"02 Декор и формы","photos":"03 Изображения",
            "logo":"04 Логотип","heading":"05 Заголовки","claims":"06 Тезисы",
            "specs":"07 Технические характеристики","benefits":"08 Преимущества",
            "dimensions":"09 Габариты и чертёж","roi":"10 Экономика",
            "price":"11 Цена","contacts":"12 Контакты",
        }
        for name,title in titles.items():
            self.groups[name]=ET.SubElement(self.root,f"{{{NS}}}g",{
                "id":name,f"{{{INK}}}groupmode":"layer",f"{{{INK}}}label":title})
        self.rect("background",0,0,self.w,self.h,"url(#promo-gradient)",ident="base")
        self.polygon("decor",[(self.w*.85,0),(self.w,0),(self.w*.66,self.h*.22)],"#ffffff",opacity=".55")
        self.polygon("decor",[(0,180),(85,0),(145,0),(0,400)],"#ffffff",opacity=".38")

    def id(self,label):
        self.i+=1
        return f"{label}-{self.i:03d}"

    def el(self,group,tag,ident,attrs):
        return ET.SubElement(self.groups[group],f"{{{NS}}}{tag}",{
            "id":self.id(ident),**{k:str(round(v,2)) if isinstance(v,float) else str(v)
                                  for k,v in attrs.items() if v is not None}})

    def rect(self,g,x,y,w,h,fill,rad=None,ident="shape",opacity=None):
        return self.el(g,"rect",ident,{"x":x,"y":y,"width":max(1,w),"height":max(1,h),
                       "rx":rad,"fill":fill,"opacity":opacity})

    def polygon(self,g,points,fill,ident="shape",opacity=None):
        pts=" ".join(f"{round(x,2)},{round(y,2)}" for x,y in points)
        return self.el(g,"polygon",ident,{"points":pts,"fill":fill,"opacity":opacity})

    def text(self,g,content,x,y,w,h,size=24,minimum=13,color="#253040",bold=False,
             ident="text",max_lines=2):
        if not content:return None
        content="".join(c for c in str(content) if ord(c)>=32 or c in "\n\t")
        w=max(10,int(w))
        size=int(size)
        for fs in range(size,int(minimum)-1,-1):
            lines=_wrap(content,w,fs,bold)
            if len(lines)<=max_lines and len(lines)*fs*1.25<=h:break
        if len(lines)>max_lines:
            lines=lines[:max_lines]
            f=_font(fs,bold)
            final=lines[-1]
            while final and f.getlength(final+"…")>w:final=final[:-1]
            lines[-1]=final.rstrip()+"…"
        el=self.el(g,"text",ident,{
            "x":x,"y":y+fs,"fill":color,"font-family":"DejaVu Sans, Arial, sans-serif",
            "font-size":fs,"font-weight":"700" if bold else "400","xml:space":"preserve"})
        for idx,line in enumerate(lines):
            span=ET.SubElement(el,f"{{{NS}}}tspan",{
                "x":str(round(x,2)),"dy":"0" if idx==0 else str(round(fs*1.25,2))})
            span.text=line
        return el

    def bitmap(self,g,image,x,y,w,h,name):
        if image is None:return
        im=image.convert("RGBA")
        if im.width*im.height>4_000_000:im.thumbnail((2000,2000),Image.Resampling.LANCZOS)
        buf=io.BytesIO()
        im.save(buf,format="PNG")
        href="data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode("ascii")
        return self.el(g,"image",name,{"x":x,"y":y,"width":w,"height":h,
                       "preserveAspectRatio":"xMidYMid meet",f"{{{XLINK}}}href":href})

    def bar(self,g,x,y,w,title,accent,h=46):
        self.rect(g,x,y,w,h,"#29303b",rad=13,ident="bar")
        self.polygon(g,[(x,y),(x+80,y),(x+63,y+h),(x,y+h)],accent,ident="bar-slash")
        self.text(g,title,x+95,y+3,w-110,h-4,24,16,"#ffffff",True,"section-name",1)

    def panel(self,g,x,y,w,h,title,accent):
        self.rect(g,x,y,w,h,"#ffffff",rad=16,ident="panel")
        self.bar(g,x,y,w,title,accent)

    def export(self):
        return ET.tostring(self.root,encoding="utf-8",xml_declaration=True)


def create_editable_svg(brief,key,hero=None,detail=None,logo=None,drawing=None,
                        backdrop=None,ai_product=False):
    """Return fully embedded SVG. Raster assets are independent replaceable objects."""
    s=Scene(key,brief.get("accent"),brief.get("style"))
    v=key=="9x16"
    w,h=s.w,s.h
    a=s.accent
    brand=str(brief.get("brand") or "PROMO").upper()
    category=str(brief.get("category") or "ПРОМЫШЛЕННОЕ ОБОРУДОВАНИЕ").upper()
    model=str(brief.get("model") or "Товар")
    slogan=str(brief.get("slogan") or "Проверенное решение для вашего бизнеса")
    if logo is not None:s.bitmap("logo",logo,40,27,230,107,"original-logo")
    else:
        s.text("logo",brand,42,42,270,75,42,24,"#222832",True,"brand",1)
        s.rect("logo",42,120,225,7,a,ident="brand-underline")
    tx=322 if v else 340
    s.polygon("decor",[(tx-20,35),(tx-12,35),(tx-48,133),(tx-56,133)],a,ident="header-slash")
    s.text("heading",category,tx,29,w-tx-28,48,34,20,"#2f3846",True,"category",1)
    s.text("heading",model,tx,76,w-tx-27,89,68,34,"#1e2a39",True,"model",1)
    if v:
        s.rect("heading",38,176,w-76,43,a,rad=10,ident="slogan-ribbon")
        s.text("heading",slogan,52,181,w-105,36,24,14,"#ffffff",True,"slogan",1)
        hx,hy,hw,hh=38,237,1004,532
        claims=[(39+(i%2)*510,784+(i//2)*77,498,70) for i in range(4)]
        spec=(38,954,1004,320)
        ben=(38,1285,1004,173)
        dim=(38,1467,1004,163)
        roi=(38,1644,1004,98)
        price=(35,1759,1010,77)
        footer_y=1846
    else:
        s.rect("heading",340,149,w-375,45,a,rad=10,ident="slogan-ribbon")
        s.text("heading",slogan,355,155,w-404,37,24,15,"#ffffff",True,"slogan",1)
        hx,hy,hw,hh=37,211,888,310
        claims=[(943,217+i*76,461,69) for i in range(4)]
        spec=(37,534,605,311)
        ben=(657,534,748,158)
        dim=(657,703,748,143)
        roi=(37,855,1368,76)
        price=(35,947,1370,76)
        footer_y=1030
    s.rect("photos",hx+3,hy+6,hw,hh,"#c8d3de",rad=23,ident="photo-shadow")
    s.rect("photos",hx,hy,hw,hh,"#f8fafc",rad=23,ident="photo-frame")
    if backdrop is not None and not ai_product:
        s.bitmap("photos",backdrop,hx+10,hy+10,hw-20,hh-20,"ai-scene")
        s.rect("photos",hx+10,hy+10,hw-20,hh-20,"#ffffff",rad=14,opacity=".16",ident="soft-light")
    else:
        s.rect("photos",hx+10,hy+10,hw-20,hh-20,"#eaf0f6",rad=15,ident="photo-background")
        s.polygon("photos",[(hx+10,hy+hh*.73),(hx+hw-10,hy+hh*.64),
                            (hx+hw-10,hy+hh-10),(hx+10,hy+hh-10)],"#dce5ee",ident="photo-floor")
    source=backdrop if ai_product else hero
    if source is not None:
        s.bitmap("photos",source,hx+23,hy+17,hw-46,hh-34,
                 "ai-product-bitmap" if ai_product else "original-product-photo")
        if ai_product:
            s.rect("claims",hx+20,hy+hh-49,247,34,"#27303b",rad=8,ident="ai-disclosure-bg")
            s.text("claims","AI-ВИЗУАЛИЗАЦИЯ",hx+32,hy+hh-46,223,29,16,13,"#ffffff",True,"ai-disclosure",1)
    else:
        s.text("photos","ФОТО ТОВАРА",hx+100,hy+hh*.43,hw-200,76,35,19,"#8993a3",True,"photo-placeholder",1)
    if detail is not None:
        dx=hx+hw-218
        dy=hy+hh-144
        s.rect("photos",dx-6,dy-6,220,143,"#ffffff",rad=12,ident="detail-frame")
        s.bitmap("photos",detail,dx,dy,209,131,"detail-photo")
    for i,value in enumerate((brief.get("hero_claims") or [])[:4]):
        x,y,cw,ch=claims[i]
        s.rect("claims",x,y,cw,ch,"#ffffff",rad=12,ident=f"claim-panel-{i}")
        s.rect("claims",x+8,y+8,53,ch-16,a,rad=9,ident=f"claim-number-bg-{i}")
        s.text("claims",str(i+1),x+22,y+11,35,46,27,18,"#ffffff",True,f"claim-index-{i}",1)
        s.text("claims",str(value),x+74,y+9,cw-90,ch-15,24,14,"#27313e",True,f"claim-{i}",2)
    x,y,ww,hh2=spec
    s.panel("specs",x,y,ww,hh2,"Основные ТТХ",a)
    items=[(str(p[0]),str(p[1])) for p in (brief.get("specs") or [])[:8]
           if isinstance(p,(list,tuple)) and len(p)>1 and str(p[0]).strip()]
    if not items:items=[("Характеристики","Уточняются")]
    rh=(hh2-58)/len(items)
    for i,(name,value) in enumerate(items):
        yy=y+52+i*rh
        s.rect("specs",x+12,yy,ww-24,rh-3,"#f0f3f8" if i%2==0 else "#f7f9fb",rad=7,ident=f"spec-row-{i}")
        split=ww*.52
        s.text("specs",name,x+25,yy+3,split-32,rh-7,21,13,"#34404d",False,f"spec-label-{i}",2)
        s.text("specs",value,x+split+9,yy+3,ww-split-33,rh-7,22,13,a,True,f"spec-value-{i}",2)
    x,y,ww,hh2=ben
    s.panel("benefits",x,y,ww,hh2,"Почему выгоднее",a)
    benefits=[str(z) for z in (brief.get("benefits") or []) if str(z).strip()][:4]
    while len(benefits)<4:benefits.append(["Выше эффективность","Меньше расходы","Надёжная конструкция","Для вашего бизнеса"][len(benefits)])
    gap=14
    cw=(ww-gap*3)/2
    ch=(hh2-60-gap*2)/2
    for i,benefit in enumerate(benefits):
        bx=x+gap+(i%2)*(cw+gap)
        by=y+53+gap+(i//2)*(ch+gap)
        s.rect("benefits",bx,by,cw,ch,"#f2f5f9",rad=9,ident=f"benefit-panel-{i}")
        s.rect("benefits",bx+8,by+8,29,29,a,rad=9,ident=f"benefit-dot-{i}")
        s.text("benefits","✓",bx+14,by+7,22,30,18,13,"#ffffff",True,f"check-{i}",1)
        s.text("benefits",benefit,bx+45,by+7,cw-53,ch-8,19,13,"#2b3441",True,f"benefit-copy-{i}",2)
    x,y,ww,hh2=dim
    s.panel("dimensions",x,y,ww,hh2,"Габаритные размеры, мм",a)
    dw=345 if v else 280
    if drawing is not None:s.bitmap("dimensions",drawing,x+16,y+55,dw,hh2-65,"original-drawing")
    else:
        s.rect("dimensions",x+16,y+55,dw,hh2-66,"#edf2f6",rad=6,ident="drawing-placeholder")
        s.el("dimensions","line","drawing-axis",{
            "x1":x+35,"y1":y+94,"x2":x+dw-18,"y2":y+94,
            "stroke":"#8290a1","stroke-width":3})
    dimensions=[(str(p[0]),str(p[1])) for p in (brief.get("dimensions") or [])[:4]
                if isinstance(p,(list,tuple)) and len(p)>1 and str(p[0]).strip()]
    if not dimensions:dimensions=[("Длина","—"),("Ширина","—"),("Высота","—")]
    dr=(hh2-55)/len(dimensions)
    for i,(name,value) in enumerate(dimensions):
        yy=y+52+i*dr
        s.text("dimensions",name,x+dw+35,yy,ww-dw-184,dr-3,19,12,"#29394b",False,f"dimension-label-{i}",1)
        s.text("dimensions",value,x+ww-155,yy,136,dr-3,21,12,a,True,f"dimension-value-{i}",1)
    x,y,ww,hh2=roi
    s.rect("roi",x,y,ww,hh2,"#ffffff",rad=13,ident="roi-panel")
    if brief.get("show_roi",False):
        from .render import compute_roi
        data=compute_roi(brief)
        if data:
            cards=[("ЗА РЕЙС",f"{data['per_trip']:,.0f}"),("РЕЙСОВ / ГОД",str(int(data['trips']))),
                   ("ВЫРУЧКА / ГОД",f"{data['annual']:,.0f}"),("БАЛАНС",f"{data['net']:,.0f}")]
            cw=(ww-28)/4
            for i,(caption,value) in enumerate(cards):
                bx=x+8+i*cw
                s.rect("roi",bx,y+8,cw-7,hh2-16,"#f0f3f7",rad=8,ident=f"roi-tile-{i}")
                s.text("roi",caption,bx+10,y+8,cw-20,26,15,11,"#5a6678",True,f"roi-caption-{i}",1)
                s.text("roi",value.replace(","," "),bx+10,y+32,cw-20,hh2-39,26,14,a,True,f"roi-value-{i}",1)
        else:s.text("roi","Проверьте данные для расчёта",x+25,y+17,ww-50,hh2-18,24,15,"#2d3948",True,"roi-error",2)
    else:s.text("roi",slogan,x+23,y+17,ww-44,hh2-18,25,14,"#293647",True,"roi-text",2)
    x,y,ww,hh2=price
    s.polygon("price",[(x+10,y),(x+ww-22,y),(x+ww,y+18),(x+ww-45,y+hh2),(x,y+hh2-8)],a,"price-banner")
    cost=str(brief.get("price") or "").strip()
    copy=("Цена: "+cost+" "+str(brief.get("currency") or "Br")+(" с НДС" if brief.get("vat",True) else "")) if cost else "ЗАПРОСИТЕ КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ"
    s.text("price",copy,x+35,y+7,ww-66,hh2-12,42,20,"#ffffff",True,"price-text",1)
    s.rect("contacts",0,footer_y,w,h-footer_y,"#242b35",ident="footer-background")
    s.polygon("contacts",[(0,footer_y),(121,footer_y),(94,h),(0,h)],a,"footer-accent")
    phones="   /   ".join(str(t) for t in (brief.get("phones") or [])[:2] if str(t).strip()) or "Контакты — по запросу"
    if v:
        s.text("contacts","СВЯЗАТЬСЯ С НАМИ",145,footer_y+4,w-175,36,25,16,"#ffffff",True,"contact-caption",1)
        s.text("contacts",phones,145,footer_y+43,w-180,41,24,15,"#ffffff",True,"contact-values",1)
    else:
        s.text("contacts","СВЯЖИТЕСЬ С НАМИ",145,footer_y+2,365,37,23,16,"#ffffff",True,"contact-caption",1)
        s.text("contacts",phones,526,footer_y+2,w-546,37,23,16,"#ffffff",True,"contact-values",1)
    return s.export()


def rasterize_svg(svg:bytes)->tuple[bytes,bytes]:
    """Identical design for PNG/JPEG and CorelDRAW SVG."""
    import cairosvg
    png=cairosvg.svg2png(bytestring=svg)
    with Image.open(io.BytesIO(png)) as image:
        buf=io.BytesIO()
        image.convert("RGB").save(buf,format="JPEG",quality=91,subsampling=0)
    return png,buf.getvalue()
