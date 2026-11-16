"""Bounded, in-memory previews for analysing uploaded photographs.

Source bytes are never rewritten. Selection, SHA256 identity and rendering
continue to use the original upload, not this disposable analysis preview.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

MIN_IMAGE_EDGE = 32
MAX_IMAGE_EDGE = 10_000
# Rendering loads full-resolution originals. Keep a separate hard safety cap:
# the analysis limit (formerly 20 MP) is *not* a source-upload limit.
MAX_SOURCE_PIXELS = 48_000_000
ANALYSIS_RESIZE_THRESHOLD = 20_000_000


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
    if not 1 <= max_edge <= 1600:
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
