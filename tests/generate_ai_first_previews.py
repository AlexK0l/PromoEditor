"""Offline visual QA of the new AI-plan renderer. NO paid API calls.

Art is a deliberately synthetic placeholder: validates geometry, exact SVG
layers and typography, NOT OpenAI image quality or source-photo fidelity.
"""
from pathlib import Path

from PIL import Image, ImageDraw

from app.ai_director import render_ai_poster, validate_plan
from app.editable_export import rasterize_svg
from app.render import default_brief


def main():
    out=Path("/tmp/promo-ai-first-previews")
    out.mkdir(parents=True,exist_ok=True)
    plan={
        "concept":"Editorial grain logistics advertisement",
        "scene_prompt":"Premium industrial terminal, open landscape",
        "ink":"#141923","surface":"#FFFFFF","support":"#E9EFF4",
        "layouts":{
            "4x3":{
                "header":[0,0,1000,150],
                "hero":[0,150,645,410],
                "specs":[650,150,350,410],
                "drawing":[0,560,1000,170],
                "benefits":[0,730,1000,85],
                "finance":[0,815,1000,80],
                "footer":[0,895,1000,105],
            },
            "9x16":{
                "header":[0,0,1000,125],
                "hero":[0,125,1000,270],
                "specs":[0,395,1000,185],
                "drawing":[0,580,1000,135],
                "benefits":[0,715,1000,100],
                "finance":[0,815,1000,90],
                "footer":[0,905,1000,95],
            },
        },
    }
    brief=default_brief()
    brief["style"]="reference_pro"
    product=Image.new("RGBA",(1200,750),(0,0,0,0))
    p=ImageDraw.Draw(product)
    p.polygon([(120,240),(1015,185),(1040,525),(160,545)],
              fill="#F6BE29",outline="#C68A17",width=7)
    p.rectangle((115,257,207,500),fill="#343A44")
    for xx in (565,730,890):
        p.ellipse((xx,504,xx+94,611),fill="#1E2834",
                  outline="#747B83",width=7)
    logo=Image.new("RGBA",(380,220),"white")
    ImageDraw.Draw(logo).text((48,65),"ZUBR TRAIL",fill="#C31726")
    technical=Image.new("RGB",(1200,900),"white")
    d=ImageDraw.Draw(technical)
    d.rectangle((38,25,1170,340),outline="#333333",width=3)
    for xx in range(80,1120,26):
        d.line((xx,45,xx,325),fill="#444444",width=2)
    d.rectangle((485,560,710,842),outline="#333333",width=3)
    validate_plan(plan,{**brief,"_has_drawing":True})
    for key in ("4x3","9x16"):
        # Synthetic art plate with distant silos, NOT the result of AI.
        backdrop=Image.new("RGB",(1400,1600),"#DDE7EC")
        art=ImageDraw.Draw(backdrop)
        for i in range(4):
            x=70+i*165
            art.rectangle((x,220,x+105,550),fill="#C9D4DC",
                          outline="#AABCC9",width=2)
            art.polygon([(x-7,220),(x+52,162),(x+112,220)],
                        fill="#B1C3CE")
        art.rectangle((0,560,1400,1600),fill="#E9EEF1")
        svg=render_ai_poster(brief,key,plan,backdrop,
                             hero=product,drawing=technical,logo=logo)
        png,_=rasterize_svg(svg)
        (out/f"ai_first_{key}.png").write_bytes(png)
        (out/f"ai_first_{key}.svg").write_bytes(svg)
        print(key,len(png),len(svg))
    (out/"README.txt").write_text(
        "These samples use OFFLINE synthetic artwork and a synthetic "
        "trailer/drawing. They verify editability, layout and type only. "
        "Real AI image generation is validated with mocked API calls; "
        "no user photo or production key is stored in this artifact.\n",
        encoding="utf-8",
    )


if __name__=="__main__":
    main()
