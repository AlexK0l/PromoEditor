"""Art-direction and factual payload for a FULL Images-rendered advertisement.

This is NOT an SVG template or a deterministic content grid. OpenAI Images
owns every visible poster element: photograph composition, lettering,
pictograms, engineering drawing placement, the ROI story, CTA and hierarchy.
Our Python code may validate the submitted facts and package originals, but
must not paint boxes/cards/text over the generated art in this mode.
"""
from __future__ import annotations

from .ai_exact_copy_render import _format_money
from .render import compute_roi


def approved_full_copy(brief: dict) -> dict:
    """Preserve the COMPLETE submitted facts, no historical 8+4 truncation."""
    def value(key: str, maximum: int = 350) -> str:
        return str(brief.get(key) or "").strip()[:maximum]
    def texts(key: str, count: int) -> list[str]:
        return [str(v).strip()[:220] for v in (brief.get(key) or [])[:count]
                if str(v).strip()]
    def facts(key: str) -> list[list[str]]:
        return [
            [str(v[0]).strip()[:120],str(v[1]).strip()[:200]]
            for v in (brief.get(key) or [])[:20]
            if isinstance(v,(tuple,list)) and len(v)>=2
            and str(v[0]).strip() and str(v[1]).strip()
        ]
    currency=value("currency",12)
    price=value("price",50)
    approved={
        "brand":value("brand",80),
        "model":value("model",90),
        "category":value("category",130),
        "slogan":value("slogan",250),
        "technical_specifications":facts("specs"),
        "engineering_dimensions":facts("dimensions"),
        "selling_claims":texts("hero_claims",8),
        "customer_benefits":texts("benefits",10),
        "approved_proofs":texts("proof_points",8),
        "price":(
            (_format_money(price)+" "+currency
             +(" с НДС" if brief.get("vat",True) else "")).strip()
            if price else ""
        ),
        "phone_numbers":texts("phones",2),
        "verified_economic_scenario":None,
    }
    if brief.get("show_roi") and isinstance(brief.get("roi"),dict):
        roi=compute_roi(brief)
        if roi and roi.get("annual",0)>0 and roi.get("year",0)>0:
            inputs=brief["roi"]
            source={
                key:str(inputs[key]).strip()
                for key in ("extra_payload","distance","rate","trips",
                            "years","baseline_price")
                if key in inputs and str(inputs[key]).strip()
            }
            money=lambda amount: _format_money(amount)+" "+currency
            approved["verified_economic_scenario"]={
                "source_inputs":source,
                "additional_revenue_per_trip":money(roi["per_trip"]),
                "trips_per_year":_format_money(roi["trips"]),
                "annual_additional_revenue":money(roi["annual"]),
                "scenario_years":_format_money(roi["year"]),
                "total_additional_revenue":money(roi["gross"]),
                "difference_in_purchase_price":money(roi["premium"]),
                "net_economic_effect":money(roi["net"]),
                "payback_years":(
                    f'{roi["payback"]:.2f}'.replace(".",",")
                    if roi["payback"] is not None else None
                ),
            }
    return approved


def reference_style_direction(fmt: str) -> str:
    """Customer-supplied picture references expressed as an art brief.

    These are ART-DIRECTION cues, NOT literal pixel coordinates or source
    facts. The customer may also supply reference images separately.
    """
    common=(
        "CUSTOMER VISUAL REFERENCE: exceptional professional grain-trailer "
        "B2B advertising. Ultra-clean warm silver-white/light gray backdrop, "
        "deep-black bold italic Russian editorial typography, vivid "
        "customer-red angled trapezoidal ribbons, restrained wheat detail, "
        "crisp technical illustration, professional product photography, "
        "strong hierarchy, restrained iconography and coherent brand "
        "identity. The yellow accurate four-axle semi-trailer remains "
        "prominent, complete and customer-branded. The visual language "
        "should match a premium Russian print sales campaign, NOT a "
        "web dashboard, spreadsheet, empty card grid, or a few simplistic "
        "blocks pasted onto a photo. Distinguish exact specs, engineering "
        "dimensions, six customer benefits, approved comparison claims, "
        "calculated ROI (only when supplied), bold red price and both "
        "customer phones within the same advertisement. Every component "
        "must feel designed together by ONE experienced graphic designer. "
        "Create ALL headings, typography, diagonal motifs, illustrated "
        "elements and picture framing AS PART OF THE FINAL IMAGE. "
        "No subsequent programmatic text renderer exists in this mode. "
    )
    if fmt=="4x3":
        return common+(
            "LANDSCAPE 4:3: design a balanced, high-information AGENCY "
            "PRINT POSTER: striking masthead and red slogan bar; large "
            "three-quarter real trailer photo and meaningfully different "
            "secondary photo if supplied; four attractive icon/claim "
            "callouts; below them carefully typeset full TTH table, "
            "actual engineering blueprint with every dimension, proof "
            "points and advantages; coherent finance section with a "
            "large highlighted net-effect number if verified; dominant "
            "full-width red price and contact band. Use flexible elegant "
            "art direction and expert optical spacing, not rigid cards "
            "or a fixed coordinate layout. All parts fully visible. "
        )
    if fmt=="9x16":
        return common+(
            "PORTRAIT 9:16: create a BRAND NEW naturally vertical print "
            "composition; NEVER reflow, crop or squeeze the landscape "
            "poster. Present a cohesive masthead, full yellow trailer "
            "hero and four engaging illustrated claim units. If the "
            "customer supplied an authentic secondary photo, create "
            "a second visual inset; otherwise do not manufacture a "
            "false camera angle. Then design the complete specification "
            "table and authentic blueprint/dimensions as polished "
            "parallel portrait information, followed by real comparison "
            "arguments, six advantages, factual economic story, "
            "large red price strip and easy-to-read phone CTA. "
            "Red/white/black editorial design, readable type and "
            "graceful densely packed information from top to bottom. "
        )
    raise ValueError("Неподдерживаемый формат AI-плаката.")
