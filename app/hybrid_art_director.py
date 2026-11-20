"""AI art director for the ordinary hybrid workflow.

OpenAI Responses chooses compositions and clean data regions. OpenAI Images
paints the COMPLETE advertising artwork. The trusted SVG pass overlays only
approved source photographs, logo, technical drawing and factual copy.

The private content-addressed plan cache prevents billing for a repeated
layout request when a later paid Images call or the final ZIP export fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from pathlib import Path

from .ai_layout import generate_concepts, validate_concept, validate_renderability
from .openai_service import _visual_lock

VERSION = "hybrid-art-director-v3"


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
    # The AI-selected concept and its own creative language remain intact.
    # No fixed server style is imposed; only reserve a stable primary mode id.
    chosen["id"] = "hybrid_sales"
    # The original customer-approved brand accent always overrides AI colors.
    accent = str(brief.get("accent") or "")
    if (len(accent) == 7 and accent[0] == "#" and
            all(ch in "0123456789abcdefABCDEF" for ch in accent[1:])):
        chosen["palette"] = {**chosen["palette"], "accent": accent}
    return _check(chosen, brief)


def _prune_expired(root: Path, ttl: int) -> None:
    """Remove stale, hashed private plans; never touch jobs or source uploads."""
    if not root.is_dir():
        return
    cutoff=time.time()-ttl
    for entry in root.iterdir():
        try:
            if (entry.is_dir() and len(entry.name)==64 and
                    all(ch in "0123456789abcdef" for ch in entry.name) and
                    entry.stat().st_mtime<cutoff):
                shutil.rmtree(entry,ignore_errors=True)
        except OSError:
            pass


def art_directed_layout(brief: dict, hero: bytes, reference: bytes | None = None) -> dict:
    """Return a single OpenAI-designed layout for both dimensions.

    At most one paid Responses call for an identical plan within TTL. No
    automatic paid retry and no fallback that pretends to be art-directed.
    """
    if not hero:
        raise ValueError("Для AI-дизайна необходимо оригинальное фото товара.")
    folder = _folder(brief, hero, reference)
    ttl = max(300, int(os.getenv("PROMO_JOB_TTL_SECONDS", "7200")))
    _prune_expired(folder.parent,ttl)
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
            style="bold", goal="sales", cinematic_hybrid=True,
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
