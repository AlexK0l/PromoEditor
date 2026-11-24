"""Editable exact-copy technical companion sheet for the two AI ad posters.

The customer's original engineering drawing is embedded as an independent
raster layer. All approved specs and dimensions remain selectable SVG text.
No OpenAI call, hallucination, bitmap OCR, truncation or hidden omitted facts.
"""
from __future__ import annotations

import base64
import io
import xml.etree.ElementTree as ET

from PIL import Image

from .ai_exact_copy_render import _size_and_lines, verified_copy
from .editable_export import NS, XLINK, Scene

FONT = "DejaVu Sans Condensed"


def _exact_text(scene: Scene, role: str, content: str, *,
                x: float, y: float, w: float, h: float,
                size: int = 25, minimum: int = 15,
                color: str = "#182230", bold: bool = False) -> None:
    """Create editable SVG with the entire exact customer string, or fail."""
    if not content:
        return
    fs, rows = _size_and_lines(
        [content], w, h, FONT, bold, size, minimum,
    )
    group = "dimensions" if role == "dimensions" else (
        "specs" if role == "specs" else
        "contacts" if role == "phones" else
        "price" if role == "price" else "heading"
    )
    el = scene.el(group, "text", "technical-"+role, {
        "x":x, "y":y+fs, "fill":color,
        "font-family":FONT, "font-size":fs,
        "font-weight":"700" if bold else "400",
        "xml:space":"preserve", "data-verified-role":role,
        "data-exact-copy":content,
    })
    for i, text in enumerate(rows):
        tspan = ET.SubElement(el, f"{{{NS}}}tspan", {
            "x":str(round(x,2)),
            "dy":"0" if i == 0 else str(round(fs*1.24,2)),
        })
        tspan.text = text


def _drawing(scene: Scene, raw: bytes) -> None:
    """JPEG decode scaling BEFORE RGBA conversion; do not allocate 8K RGBA."""
    with Image.open(io.BytesIO(raw)) as source:
        source.draft("RGB", (1300,900))
        source.thumbnail((1500,1150),Image.Resampling.LANCZOS)
        jpeg = io.BytesIO()
        source.convert("RGB").save(
            jpeg,format="JPEG",quality=87,subsampling=0,
        )
    scene.el("dimensions","image","uploaded-engineering-drawing",{
        "x":70, "y":244, "width":940, "height":435,
        "preserveAspectRatio":"xMidYMid meet",
        "data-source":"original-customer-drawing",
        f"{{{XLINK}}}href":"data:image/jpeg;base64,"
        +base64.b64encode(jpeg.getvalue()).decode("ascii"),
    })


def render_technical_sheet(brief: dict, drawing: bytes | None) -> bytes:
    """One 1080x1920 technical page alongside the two finished hero adverts.

    All customer-provided specs and dimensions, not just highlights, are
    included. The drawing is the uploaded original preview, not an AI redraw.
    """
    copy = verified_copy(brief)
    scene = Scene("9x16", brief.get("accent"), brief.get("style"))
    scene.groups["background"].clear()
    scene.groups["decor"].clear()
    scene.rect("background",0,0,1080,1920,"#F4F6F9",ident="technical-bg")
    scene.rect("decor",0,0,1080,152,"#111923",ident="technical-header")
    scene.rect("decor",0,0,11,152,scene.accent,ident="technical-accent")
    scene.text("heading","ТЕХНИЧЕСКИЙ ЛИСТ",48,16,960,56,
               38,32,"#FFFFFF",True,"technical-title",1)
    title = " · ".join((copy["brand"]+copy["model"])[:2])
    if title:
        _exact_text(scene,"model",title,
                    x=51,y=86,w=966,h=50,size=30,minimum=18,
                    color="#FFFFFF",bold=True)

    scene.rect("decor",42,176,996,538,"#FFFFFF",
               rad=20,ident="original-drawing-paper")
    scene.text("heading","ИСХОДНЫЙ ИНЖЕНЕРНЫЙ ЧЕРТЁЖ",64,188,915,46,
               25,19,"#3A4858",True,"drawing-label",1)
    if drawing:
        _drawing(scene,drawing)
    else:
        scene.text("heading","Чертёж не приложен",86,423,890,75,
                   28,20,"#738399",False,"no-drawing",1)

    scene.rect("decor",42,730,996,988,"#FFFFFF",
               rad=19,ident="technical-facts-paper")
    scene.rect("decor",42,730,996,10,scene.accent,
               ident="technical-facts-accent")
    scene.text("heading","ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ",
               62,760,560,52,28,20,"#13283D",True,"specs-label",1)
    scene.text("heading","ГАБАРИТЫ",652,760,350,52,28,20,
               "#13283D",True,"dims-label",1)
    scene.rect("decor",623,813,2,857,"#DEE4EB",ident="column-divider")
    left = copy["specs"]
    right = copy["dimensions"]
    top = 827
    # Every submitted line is printed; more values get tighter, but never
    # disappear and never contain invented ellipsis characters.
    for role,values,x,w,maximum in (
        ("specs",left,64,530,12),
        ("dimensions",right,652,350,8),
    ):
        if len(values)>maximum:
            raise ValueError(
                f"Технический лист получил больше допустимых строк {role}."
            )
        if not values:
            continue
        row_h = min(80, int(835/len(values)))
        for index,line in enumerate(values):
            y=top+index*row_h
            _exact_text(
                scene,role,line,x=x,y=y,w=w,h=row_h-9,
                size=22,minimum=14,color="#1D2C3D",
            )
            scene.rect("decor",x,y+row_h-3,w,1,"#EBEFF4",
                       ident="row-divider")

    scene.rect("decor",42,1740,996,148,"#152232",
               rad=17,ident="technical-contact-strip")
    if copy["price"]:
        _exact_text(scene,"price",copy["price"][0],
                    x=63,y=1768,w=502,h=89,
                    size=35,minimum=23,color="#FFFFFF",bold=True)
    for index,value in enumerate(copy["phones"][:2]):
        _exact_text(scene,"phones",value,
                    x=594,y=1753+index*58,w=409,h=55,
                    size=24,minimum=19,color="#FFFFFF",bold=True)
    return scene.export()
