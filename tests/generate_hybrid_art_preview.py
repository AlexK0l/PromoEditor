"""Synthetic, no-cost screenshots of the cinematic hybrid SVG renderer.

NOT a real OpenAI Images result. The mock trailer, logo, technical drawing,
and industrial backdrop are generated in-memory strictly for CI verification.
The output uses the actual production SVG composer with approved facts.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.ai_concept_renderer import render_ai_concept_svg
from app.ai_layout import _safe_layout, validate_concept, validate_renderability
from app.approved_presets import approved_zubrtrail_500
from app.editable_export import rasterize_svg


def synthetic_materials():
    product=Image.new("RGBA", (1100, 630), (0, 0, 0, 0))
    draw=ImageDraw.Draw(product)
    draw.polygon([(140,152),(785,104),(995,149),(981,430),(255,448)],
                 fill=(239,181,25,255),outline=(146,102,10,255),width=6)
    draw.rectangle((210,425,998,462), fill=(34,39,47,255))
    for cx in (655,765,890):
        draw.ellipse((cx-49,427,cx+49,532),fill=(37,41,48,255))
        draw.ellipse((cx-30,449,cx+30,509),fill=(160,174,190,255))
    draw.line((232,155,240,421),fill=(30,40,49,255),width=9)
    draw.line((286,147,292,430),fill=(30,40,49,255),width=7)
    for y in range(191,423,47):
        draw.line((232,y,293,y),fill=(30,40,49,255),width=6)

    drawing=Image.new("RGB",(1120,470),"white")
    pen=ImageDraw.Draw(drawing)
    pen.rectangle((35,60,1060,340),outline="#2E3139",width=4)
    for x in range(55,1030,39):
        pen.line((x,63,x+8,337),fill="#9AA2AC",width=2)
    for x in (620,735,850,965):
        pen.ellipse((x-44,330,x+44,415),outline="#353B43",width=5)
        pen.ellipse((x-24,350,x+24,395),outline="#768391",width=3)

    logo=Image.new("RGBA",(330,155),(255,255,255,0))
    ink=ImageDraw.Draw(logo)
    ink.rectangle((8,15,315,137),outline=(195,19,32,255),width=5)
    ink.text((50,58),"ZUBR TRAIL",fill=(195,19,32,255),
             stroke_width=1,stroke_fill=(195,19,32,255))

    scene=Image.new("RGB",(1440,1080),(177,202,226))
    paint=ImageDraw.Draw(scene)
    paint.rectangle((0,610,1440,1080),fill="#7A7775")
    paint.rectangle((0,730,1440,1080),fill="#868486")
    for x in (95,260,1120,1290):
        paint.rectangle((x,245,x+105,728),fill="#84909A")
        paint.polygon([(x-10,245),(x+115,245),(x+90,190),(x+19,190)],
                      fill="#6B737A")
    paint.line((0,690,1440,580),fill="#BBB5AE",width=14)
    return product,drawing,logo,scene


def main():
    output=Path("/tmp/promo-hybrid-art-preview")
    output.mkdir(parents=True,exist_ok=True)
    brief=approved_zubrtrail_500()
    hero,drawing,logo,background=synthetic_materials()
    proposal={
        "id":"hybrid_sales",
        "name":"Кинематографичный B2B",
        "rationale":"Товар доминирует, точные данные набраны векторным текстом.",
        "scene_prompt":"Premium industrial background only, no vehicle or text",
        "palette":{"background":"#DCE3EC","foreground":"#172235","accent":"#E31B26"},
        "layouts":{fmt:_safe_layout(fmt,0) for fmt in ("4x3","9x16")},
    }
    validate_concept({k:v for k,v in proposal.items() if k!="id"})
    for fmt in ("4x3","9x16"):
        validate_renderability(proposal,brief,fmt,has_drawing=True)
        svg=render_ai_concept_svg(
            brief,fmt,proposal,hero=hero,logo=logo,
            drawing=drawing,backdrop=background)
        png,_=rasterize_svg(svg)
        (output / f"synthetic_hybrid_{fmt}.svg").write_bytes(svg)
        (output / f"synthetic_hybrid_{fmt}.png").write_bytes(png)
        assert b"ZubrTrail 500" in svg and b"original-product-photo" in svg
    (output / "README.txt").write_text(
        "ВНИМАНИЕ: это структурный тест нового арт-директора, НЕ платный "
        "ответ OpenAI Images. Техника, логотип, чертёж и фон являются "
        "синтетическими изображениями. Цена 6 527 000 ₽, телефоны и ТТХ "
        "взяты из утверждённого пресета. Фактическая художественная сцена "
        "после реального OpenAI вызова будет иной.\n",
        encoding="utf-8",
    )
    print("Synthetic 4:3 and 9:16 hybrid SVG/PNG saved at",output)


if __name__=="__main__":
    main()
