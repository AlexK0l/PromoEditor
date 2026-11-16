"""Bounded, in-memory previews for analysing uploaded photographs.

Source bytes are never rewritten. Selection, SHA256 identity and rendering
continue to use the original upload, not this disposable analysis preview.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

MIN_IMAGE_EDGE = 32
MAX_IMAGE_EDGE = 10_000
# The source stays byte-for-byte intact; the renderer uses a bounded working
# image. Keep a conservative hard safety cap for untrusted decompression.
# 8840x6614 (58.47 MP) photographs must be accepted without manual resizing.
MAX_SOURCE_PIXELS = 80_000_000
ANALYSIS_RESIZE_THRESHOLD = 20_000_000
MAX_RENDER_EDGE = 3_200

# Align Pillow decompression-bomb detection with our stricter explicit
# validation; values above the limit are rejected before pixel decoding.
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


def validate_image_dimensions(width: int, height: int) -> None:
    """Reject unsafe originals before decoding their pixel payload."""
    if min(width, height) < MIN_IMAGE_EDGE:
        raise ValueError(
            f"Изображение {width}×{height} px слишком маленькое "
            f"(минимум {MIN_IMAGE_EDGE} px по каждой стороне)."
        )
    if max(width, height) > MAX_IMAGE_EDGE or width * height > MAX_SOURCE_PIXELS:
        raise ValueError(
            f"Изображение {width}×{height} px слишком большое для исходника. "
            f"Допустимо не более {MAX_IMAGE_EDGE} px по стороне и "
            f"{MAX_SOURCE_PIXELS // 1_000_000} млн пикселей. "
            "Уменьшите его перед загрузкой."
        )


def analysis_preview(raw: bytes, *, max_edge: int = 512) -> tuple[Image.Image, tuple[int, int]]:
    """Return a small oriented preview and the ORIGINAL dimensions.

    Decode JPEGs at a reduced scale where supported (Image.draft), then
    normalize EXIF orientation and thumbnail. PNG/WebP preserve alpha.
    All returned images are independent of the source stream; raw bytes stay
    untouched and are never replaced in the asset record.
    """
    if not 1 <= max_edge <= MAX_RENDER_EDGE:
        raise ValueError("Некорректный размер превью.")
    with Image.open(io.BytesIO(raw)) as source:
        original_size = source.size
        validate_image_dimensions(*original_size)
        if source.format == "JPEG":
            source.draft("RGB", (max_edge * 2, max_edge * 2))
        preview = ImageOps.exif_transpose(source)
        preview.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        preview.load()
        return preview, original_size


def rendering_copy(raw: bytes, *, max_edge: int = MAX_RENDER_EDGE) -> Image.Image:
    """High-quality bounded copy for a poster; original bytes are archived.

    The final SVG embeds raster layers at up to 2000 px, so a 3200 px working
    copy has extra detail for layout/cropping without fully decoding 58 MP JPEGs.
    """
    preview, _ = analysis_preview(raw, max_edge=max_edge)
    return preview.convert("RGBA")
