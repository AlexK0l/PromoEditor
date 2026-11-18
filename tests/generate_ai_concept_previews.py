"""Produce original, source-driven AI layout samples for visual QA in CI.

No paid OpenAI request or third-party artwork. Uses a representative valid
geometry returned by the model schema, and the same editable production SVG
compositor that AI PRO invokes after selection.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

from app.ai_concept_renderer import render_ai_concept_svg
from app.editable_export import rasterize_svg
from app.render import default_brief


def box(x,y,w,h):
    return {"x":x,"y":y,"w":w,"h":h}


def layouts():
    return {
        "4x3": {
            "header":box(0,0,1000,130),
            "hero":box(0,140,610,430),
            "specs":box(620,140,380,430),
            "dimensions":box(0,580,610,165),
            "benefits":box(620,580,380,165),
            "roi":box(0,755,1000,105),
            "footer":box(0,870,1000,130),
        },
        "9x16": {
            "header":box(0,0,1000,120),
            "hero":box(0,130,1000,270),
            "specs":box(0,410,1000,230),
            "dimensions":box(0,650,1000,140),
            "benefits":box(0,795,650,95),
            "roi":box(660,795,340,95),
            "footer":box(0,900,1000,100),
        },
    }


def sources():
    hero=Image.new("RGBA",(1150,620),(0,0,0,0))
    painter=ImageDraw.Draw(hero)
    painter.polygon([(145,150),(850,115),(1010,165),(1000,442),
                     (240,466)],fill="#F3BB19",outline="#B6810A",width=6)
    painter.rectangle((160,420,995,451),fill="#2B2D33")
    for x in (655,775,900):
        painter.ellipse((x-56,417,x+56,529),fill="#2F343C")
        painter.ellipse((x-36,436,x+36,509),fill="#9EABB9")
    drawing=Image.new("RGB",(1200,900),"white")
    pen=ImageDraw.Draw(drawing)
    pen.rectangle((42,22,1140,340),outline="#242424",width=3)
    for x in range(65,1125,28):
        pen.line((x,40,x,338),fill="#313131",width=2)
    for y in (123,173,223,273):
        pen.line((42,y,1140,y),fill="#373737",width=2)
    pen.rectangle((490,550,715,845),outline="#333333",width=3)
    logo=Image.new("RGBA",(320,170),(255,255,255,0))
    ink=ImageDraw.Draw(logo)
    ink.rectangle((18,13,304,155),outline="#A41227",width=5)
    ink.text((32,65),"ZUBR TRAIL",fill="#A41227")
    return hero,drawing,logo


def main():
    target=Path("/tmp/promo-ai-concepts")
    target.mkdir(parents=True,exist_ok=True)
    brief=default_brief()
    brief["style"]="reference_pro"
    hero,drawing,logo=sources()
    proposal={
        "id":"concept_0",
        "name":"Техно-премиум",
        "rationale":"Продукт и чертёж остаются центральными.",
        "scene_prompt":"Bright grain terminal background without vehicles or words",
        "palette":{
            "background":"#F6F7F9",
            "foreground":"#172235",
            "accent":"#E31B26",
        },
        "layouts":layouts(),
    }
    # Same customer facts and SAME rectangles isolate the effect of actual
    # visual direction: dynamic sales, blueprint, editorial minimalism.
    for index,name in enumerate(("sales","engineering","editorial")):
        design={**proposal,"id":f"concept_{index}"}
        for key in ("4x3","9x16"):
            svg=render_ai_concept_svg(brief,key,design,hero=hero,
                                      drawing=drawing,logo=logo)
            png,_=rasterize_svg(svg)
            (target/f"ai_direction_{index}_{name}_{key}.svg").write_bytes(svg)
            (target/f"ai_direction_{index}_{name}_{key}.png").write_bytes(png)
            if index==0:
                # Preserve existing CI artifact links consumed by reviewers.
                (target/f"ai_first_{key}.svg").write_bytes(svg)
                (target/f"ai_first_{key}.png").write_bytes(png)
            print(f"Art direction {name}: {key} — {len(svg)} SVG, {len(png)} PNG bytes")
    print(f"Saved six editable visual review samples to {target}")


if __name__=="__main__":
    main()
