"""Generate review-only PRO v2 PNGs with explicitly synthetic photo placeholders.

No OpenAI calls and no customer assets. Outputs are for visual regression
inspection, NOT for publishing a product claim.
"""
from pathlib import Path

from PIL import Image, ImageDraw

from app.editable_export import create_editable_svg, rasterize_svg
from app.render import default_brief


def placeholder():
    canvas = Image.new("RGBA", (1400, 800), (255, 255, 255, 0))
    pen = ImageDraw.Draw(canvas)
    pen.polygon([(125, 250), (1000, 190), (1100, 530), (220, 560)],
                fill="#F0B529", outline="#B47A0B", width=8)
    pen.polygon([(200, 540), (1060, 512), (1150, 563), (250, 600)],
                fill="#282E38")
    for x in (790, 910, 1030):
        pen.ellipse((x, 520, x+110, 655), fill="#1E2126",
                    outline="#77808B", width=14)
    pen.rectangle((125, 275, 152, 520), fill="#292F37")
    pen.rectangle((220, 270, 239, 540), fill="#292F37")
    pen.text((400, 355), "DEMO ONLY / NOT A PRODUCT PHOTO", fill="#552F10")
    return canvas


def main():
    output = Path("/tmp/promo-pro-v2")
    output.mkdir(parents=True, exist_ok=True)
    data = default_brief()
    data["style"] = "reference_pro"
    data["proof_points"] = [
        "Демонстрационный тезис 1", "Демонстрационный тезис 2"
    ]
    image = placeholder()
    for key in ("4x3", "9x16"):
        svg = create_editable_svg(data, key, hero=image)
        png, _ = rasterize_svg(svg)
        (output / f"pro_v2_{key}.png").write_bytes(png)
        (output / f"pro_v2_{key}.svg").write_bytes(svg)
    print("PRO v2 preview files:", sorted(str(p) for p in output.iterdir()))


if __name__ == "__main__":
    main()
