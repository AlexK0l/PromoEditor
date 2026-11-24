"""Non-destructive final-size export of a completed OpenAI raster."""
from PIL import Image

MATTE_RGB = (245, 245, 245)
TARGETS = ((1440, 1080), (1080, 1920))


def artwork_geometry(source: tuple[int, int], target: tuple[int, int]) -> dict:
    """Integer content rectangle: uniform contain, never crop or stretch."""
    if target not in TARGETS:
        raise ValueError("Invalid poster dimensions")
    w, h = source
    tw, th = target
    if min(w, h) < 1:
        raise ValueError("Invalid source dimensions")
    if tw * h <= th * w:
        rw, rh = tw, max(1, round(h * tw / w))
    else:
        rw, rh = max(1, round(w * th / h)), th
    x, y = (tw - rw) // 2, (th - rh) // 2
    return {"source_size": [w, h], "target_size": [tw, th],
            "content_box": [x, y, x + rw, y + rh],
            "fit": "contain", "crop": False, "matte_rgb": list(MATTE_RGB)}


def fit_complete_artwork(image: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Keep every original region, using only flat neutral matte if needed."""
    box = artwork_geometry(image.size, target)["content_box"]
    x, y, right, bottom = box
    rgb = image.convert("RGB")
    scaled = rgb.resize((right - x, bottom - y), Image.Resampling.LANCZOS)
    result = Image.new("RGB", target, MATTE_RGB)
    result.paste(scaled, (x, y))
    return result
