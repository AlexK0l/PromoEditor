"""AI art director for the ordinary hybrid workflow.

An OpenAI Responses design call chooses layouts, palette and scene mood,
but cannot author any text or alter customer assets. The existing validated
SVG compositor then typesets facts from the approved user brief.

The private content-addressed plan cache prevents billing for a repeated
layout request when a later paid Images call or the final ZIP export fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from .ai_layout import generate_concepts, validate_concept, validate_renderability
from .openai_service import _visual_lock

VERSION = "hybrid-art-director-v2"


def _folder(brief: dict, hero: bytes, reference: bytes | None) -> Path:
    payload = {
        "version": VERSION,
        "brief": brief,
        "hero_sha256": hashlib.sha256(hero).hexdigest(),
        "reference_sha256": hashlib.sha256(reference).hexdigest() if reference else None,
        "layout_model": os.getenv("OPENAI_LAYOUT_MODEL", "gpt-4.1-mini"),
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    root = Path(os.getenv(
        "PROMO_DATA_DIR",
        str(Path(__file__).resolve().parent.parent / "instance" / "jobs"),
    )) / ".hybrid_art_plans"
    return root / digest


def _check(concept: dict, brief: dict) -> dict:
    """Trust only complete, independently renderable layouts and safe metadata."""
    if not isinstance(concept, dict):
        raise ValueError("Некорректный план дизайна.")
    bare = {key: value for key, value in concept.items()
            if key not in ("id", "layout_repair")}
    validate_concept(bare)
    for fmt in ("4x3", "9x16"):
        validate_renderability(concept, brief, fmt)
    return concept


def _pick_sales_concept(concepts: list[dict], brief: dict) -> dict:
    """Choose largest useful product stage, not a tiny tech-spec layout."""
    valid = [_check(concept, brief) for concept in concepts]
    if not valid:
        raise ValueError("OpenAI не предложил читаемую композицию.")

    def score(item: dict) -> int:
        wide = item["layouts"]["4x3"]["hero"]
        tall = item["layouts"]["9x16"]["hero"]
        # An expressive product shot is crucial; preserve the portrait view.
        return (wide["w"] * wide["h"] * 2 + tall["w"] * tall["h"])

    chosen = dict(max(valid, key=score))
    # All normal hybrid posters use the energetic cinematic artwork, even if
    # the most generous layout came from another of the three candidates.
    chosen["id"] = "hybrid_sales"
    # The original customer-approved brand accent always overrides AI colors.
    accent = str(brief.get("accent") or "")
    if (len(accent) == 7 and accent[0] == "#" and
            all(ch in "0123456789abcdefABCDEF" for ch in accent[1:])):
        chosen["palette"] = {**chosen["palette"], "accent": accent}
    return _check(chosen, brief)


def art_directed_layout(brief: dict, hero: bytes, reference: bytes | None = None) -> dict:
    """Return a single OpenAI-designed layout for both dimensions.

    At most one paid Responses call for an identical plan within TTL. No
    automatic paid retry and no fallback that pretends to be art-directed.
    """
    if not hero:
        raise ValueError("Для AI-дизайна необходимо оригинальное фото товара.")
    folder = _folder(brief, hero, reference)
    ttl = max(300, int(os.getenv("PROMO_JOB_TTL_SECONDS", "7200")))
    with _visual_lock(folder):
        path = folder / "plan.json"
        if path.is_file():
            try:
                if time.time() - path.stat().st_mtime < ttl:
                    return _check(json.loads(path.read_text(encoding="utf-8")), brief)
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
                pass
        proposals = generate_concepts(
            brief, hero=hero, reference=reference,
            style="bold", goal="sales",
        )
        chosen = _pick_sales_concept(proposals, brief)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = folder / f".plan-{secrets.token_hex(8)}.tmp"
        try:
            temporary.write_text(json.dumps(chosen, ensure_ascii=False),
                                 encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return chosen
