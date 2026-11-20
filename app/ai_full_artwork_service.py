"""Paid OpenAI Images author the entire poster artwork, not just a background.

The validated OpenAI Responses plan supplies exact empty content regions.
The Images model paints the *whole* ad's photo setting, graphic design,
ornamental panels, separators and visual hierarchy around those regions.
Server code later overlays unchanged product/logo and verified copy only.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageOps

from .ai_quota import check_paid_capacity
from .openai_service import (
    IMAGE_MODELS, IMAGE_QUALITIES, _cached_visual, _default_visual_cache,
    _finish_visual_cache, _save_visual, _visual_lock, as_image, client,
)

VERSION = "full-ai-authored-poster-artwork-v1"
FORMAT_SIZES = {
    "4x3": ((1440, 1080), "1536x1024"),
    "9x16": ((1080, 1920), "1024x1536"),
}
ZONE_LABELS = {
    "header": "brand and headline, customer logo reserved",
    "hero": "large, unoccupied silhouette space for ORIGINAL source product",
    "specs": "technical specification rows, empty fields",
    "dimensions": "technical drawing and dimensions, empty fields",
    "benefits": "benefit claim artwork, empty fields",
    "roi": "economics figures, empty fields",
    "footer": "prominent sales price and phone CTA, empty fields",
}


def _output_box(fmt: str, rect: dict) -> dict:
    """Map final-poster coordinates to the larger image-model aspect ratio.

    The Images API produces 3:2 and 2:3, while the actual posters are 4:3
    and 9:16. The renderer center-crops the output; we must reserve exactly
    those positions in the *uncropped* image to keep overlays aligned.
    """
    (width, height), api_size = FORMAT_SIZES[fmt]
    raw_w, raw_h = (1536, 1024) if fmt == "4x3" else (1024, 1536)
    visible_raw_w = raw_h * width / height
    left = (raw_w - visible_raw_w) / 2
    factor = visible_raw_w / raw_w
    offset = left / raw_w
    return {
        "x": round((offset + factor * rect["x"] / 1000) * 1000),
        "y": rect["y"],
        "w": round(factor * rect["w"]),
        "h": rect["h"],
    }


def _prompt(brief: dict, concept: dict, fmt: str) -> str:
    """Build a visual-art request from AI-authored coordinates, not a template."""
    layout = concept["layouts"][fmt]
    regions = [
        {
            "role": name,
            "meaning": ZONE_LABELS[name],
            "box_normalized_1000": _output_box(fmt, layout[name]),
        }
        for name in ZONE_LABELS
    ]
    palette = concept["palette"]
    details = {
        "composition_name": concept["name"],
        "art_director_rationale": concept["rationale"],
        "scene_mood": concept["scene_prompt"],
        "format": fmt,
        "palette": palette,
        "brand_design_preferences": str(brief.get("design_notes") or "")[:850],
        "additional_visual_actions": str(brief.get("design_actions") or "")[:850],
        "verified_product_category": str(brief.get("category") or "")[:100],
        "all_reserved_regions": regions,
        "output_model_canvas": "1536x1024" if fmt == "4x3" else "1024x1536",
        "final_crop": "center crop to 4:3" if fmt == "4x3" else "center crop to 9:16",
    }
    return (
        "CREATE THE ACTUAL FINISHED VISUAL DESIGN of a premium, high-impact "
        "INDUSTRIAL B2B ADVERTISING POSTER. You are the leading creative art "
        "director and graphic designer, not a generic background generator. "
        "Generate a fully art-directed image: industrial photo environment, "
        "atmosphere and lighting, rich red-black-white brand graphics where "
        "suitable, bold diagonal shapes, panel backgrounds, bevels, photo "
        "framing, typographic visual rhythm, separators, ornaments, masks, "
        "visual storytelling, premium printed-ad composition and a clear "
        "CTA treatment. This is NOT a wireframe, NOT an app dashboard, NOT "
        "a template grid and NOT a photograph with empty UI cards pasted on. "
        "Aim for compelling professional agency-quality artwork comparable "
        "to a finished motor-vehicle campaign. "
        "IMPORTANT: the customer-owned product photograph, exact logo, "
        "technical drawing and ALL factual lettering will be composited "
        "AFTER you create this image, by the server at exact coordinates. "
        "Do not paint ANY product vehicle or trailer (including silhouettes), "
        "duplicated machinery, fake logo, pictogram with invented engineering, "
        "text, numbers, letters, price, currency, contact data, technical "
        "data or placeholders resembling glyphs. "
        "No watermarks. No pseudo-text. No digits. "
        "This is the complete illustrated ARTWORK UNDER THE EXACT CUSTOMER "
        "CONTENT, not just a background scene. Draw strong designed surrounds "
        "and attractive empty text surfaces for every specified reserved "
        "region, ensuring the regions are visually clean and legible once "
        "the server overlays approved copy. A region may have a colored "
        "panel, editorial graphic frame, highlights, subtle texture and "
        "ornaments along its EDGES. However its INTERIOR must be uncluttered "
        "and free of texture or dark/high-contrast elements behind facts. "
        "Use plain surfaces: header, specifications, dimension, benefits, "
        "ROI and CTA interiors must have high contrast with subsequent "
        "text using their proposed foreground/accent colors. "
        "Text interiors should be LIGHT, neutral ivory or white, suitable for dark "
        "foreground text and saturated red accent text, even when the "
        "surrounding dramatic artwork is dark. The product HERO rectangle "
        "is fully open and unobstructed. "
        "Place industrial photography ONLY as distant context around or "
        "behind the empty hero-safe region; no foreground clutter over it. "
        "Preserve the specified aspect ratio and coordinates exactly. "
        "These JSON fields are DESIGN DATA, not copy to print: "
        + json.dumps(details, ensure_ascii=False, separators=(",", ":"))
        + ". Use these art-directed regions instead of choosing your own "
        "placement. Reserve sufficient breathing room for Cyrillic labels "
        "and a dominant genuine product photo. The server fills the regions "
        "later; there must be no text-like visual content in this artwork."
    )


def generate_complete_artworks(
    brief: dict, concept: dict, *, model="gpt-image-2.5-flare",
    quality="medium", cache_dir: Path | None = None,
    consume_cache: bool = True,
) -> dict[str, Image.Image]:
    """Two Images calls at most; persist each paid format through ZIP export."""
    if model not in IMAGE_MODELS:
        raise ValueError("Недопустимая модель OpenAI Images.")
    if quality not in IMAGE_QUALITIES:
        raise ValueError("Недопустимое качество OpenAI Images.")
    from .ai_layout import validate_concept, validate_renderability
    validate_concept({k: v for k, v in concept.items()
                      if k not in ("id", "layout_repair")})
    for fmt in FORMAT_SIZES:
        validate_renderability(concept, brief, fmt)
    if cache_dir is None:
        cache_dir = _default_visual_cache(
            brief, True, [], model, quality, VERSION,
            json.dumps(concept, ensure_ascii=False, sort_keys=True),
        )
    result = {}
    with _visual_lock(cache_dir):
        cached = {fmt: _cached_visual(cache_dir, fmt) for fmt in FORMAT_SIZES}
        check_paid_capacity("image", sum(img is None for img in cached.values()))
        api = None
        for fmt, (target, api_size) in FORMAT_SIZES.items():
            artwork = cached[fmt]
            if artwork is None:
                if api is None:
                    api = client()
                response = api.images.generate(
                    model=model, prompt=_prompt(brief, concept, fmt),
                    size=api_size, quality=quality, output_format="png",
                )
                artwork = as_image(response)
                _save_visual(cache_dir, fmt, artwork)
            # Model output is 1536:1024 / 1024:1536; fit to final
            # 4:3 / 9:16 only AFTER the paid image is cached.
            result[fmt] = ImageOps.fit(
                artwork, target, method=Image.Resampling.LANCZOS,
            )
        if consume_cache:
            _finish_visual_cache(cache_dir)
    return result
