"""Low-RAM staging limits embedded raster working copies, never originals."""
import io
from PIL import Image, ImageDraw

from app.render import load_image


def _product_png():
    source = Image.new("RGBA", (2400, 1200), (0, 0, 0, 0))
    art = ImageDraw.Draw(source)
    art.rectangle((100, 200, 2200, 900), fill=(241, 184, 12, 255))
    art.ellipse((1700, 860, 1930, 1080), fill=(44, 51, 66, 255))
    output = io.BytesIO()
    source.save(output, format="PNG")
    return output.getvalue()


def test_preview_scales_only_disposable_copy_preserving_transparency(monkeypatch):
    original = _product_png()
    monkeypatch.setenv("PROMO_RENDER_MAX_EDGE", "1600")
    prepared = load_image(original)
    assert prepared.mode == "RGBA"
    assert prepared.size == (1600, 800)
    assert prepared.getpixel((0, 0))[3] == 0
    assert prepared.getpixel((600, 400))[3] == 255
    with Image.open(io.BytesIO(original)) as uploaded:
        assert uploaded.size == (2400, 1200)
        assert uploaded.getpixel((0, 0))[3] == 0


def test_default_resolution_and_invalid_override_are_safe(monkeypatch):
    original = _product_png()
    monkeypatch.delenv("PROMO_RENDER_MAX_EDGE", raising=False)
    assert load_image(original).size == (2400, 1200)
    monkeypatch.setenv("PROMO_RENDER_MAX_EDGE", "garbled")
    assert load_image(original).size == (2400, 1200)
    monkeypatch.setenv("PROMO_RENDER_MAX_EDGE", "9999999")
    assert load_image(original).size == (2400, 1200)
    monkeypatch.setenv("PROMO_RENDER_MAX_EDGE", "-2")
    assert load_image(original).size == (960, 480)
