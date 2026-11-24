"""Art-direction and factual payload for a FULL Images-rendered advertisement.

This is NOT an SVG template or a deterministic content grid. OpenAI Images
owns every visible poster element: photograph composition, lettering,
pictograms, engineering drawing placement, the ROI story, CTA and hierarchy.
Our Python code may validate the submitted facts and package originals, but
must not paint boxes/cards/text over the generated art in this mode.
"""
from __future__ import annotations

import re

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


def approved_axle_count(approved: dict) -> int | None:
    """Derive axle count only from explicit approved axle specifications."""
    counts = set()
    for label, value in approved.get("technical_specifications") or []:
        if not re.fullmatch(r"(?:оси|ось|количество осей|число осей|axles?|axle count|number of axles)", label.strip(), re.I):
            continue
        match = re.match(r"^\s*(\d{1,2})\s*(?:оси|осей|ось|axles?)\b", value, re.I)
        if match is None:
            match = re.fullmatch(r"\s*(\d{1,2})\s*", value)
        if match is None:
            return None
        count = int(match.group(1))
        if not 1 <= count <= 30:
            return None
        counts.add(count)
    return next(iter(counts)) if len(counts) == 1 else None


ROI_DISPLAY_LABELS = {
    "additional_revenue_per_trip": "Доп. выручка за рейс",
    "trips_per_year": "Рейсов в год",
    "annual_additional_revenue": "Доп. выручка за год",
    "scenario_years": "Срок расчёта, лет",
    "total_additional_revenue": "Доп. выручка за весь срок",
    "difference_in_purchase_price": "Разница в цене покупки",
    "net_economic_effect": "Итоговый эффект",
    "payback_years": "Окупаемость, лет",
}


def mandatory_copy_direction(approved: dict) -> str:
    """Explicit visible-copy checklist, not an algorithmic page layout."""
    lines = [
        "MANDATORY VISIBLE COPY IN THIS INDIVIDUAL POSTER, not just on the vehicle.",
        "Give the model its own legible headline text and display the category separately.",
    ]
    for key, label in (("brand","Бренд"),("model","Модель"),("category","Категория")):
        if approved.get(key):
            lines.append(label + ": " + approved[key])
    for key, title in (("selling_claims","EVERY APPROVED SELLING CLAIM"),
                       ("customer_benefits","EVERY APPROVED CUSTOMER BENEFIT")):
        values=approved.get(key) or []
        if values:
            lines.append(title+" — all "+str(len(values))+
                         " items as distinct readable text, preserving exact wording. "
                         "Do not merge claims with benefits, shorten into generic slogans, "
                         "substitute unrelated features, or omit an item for lack of space.")
            lines.extend(f"{i+1}. {value}" for i,value in enumerate(values))
    proofs=approved.get("approved_proofs") or []
    if proofs:
        lines.append("All approved comparison and proof facts must be visible. "
                     "The same precise fact in the technical/finance table can satisfy a "
                     "proof; do not gratuitously repeat the same numeric result.")
        lines.extend(proofs)
    roi = approved.get("verified_economic_scenario")
    if roi:
        lines.append("Print a complete readable finance table, one distinct labelled row "
                     "per non-null result below. Neither the total nor a proof-point "
                     "summary substitutes for individual rows. Reduce ornamental "
                     "illustration before dropping data.")
        for key, label in ROI_DISPLAY_LABELS.items():
            if roi.get(key) is not None:
                lines.append(label + ": " + str(roi[key]))
    lines.append("Price/VAT must appear accurately, once, without malformed repeated tax text. "
                 "Use exactly ONE sale-price block and ONE VAT qualifier if supplied, "
                 "with no separate duplicate VAT tag, extra currency sign, repeated digits "
                 "or contradictory price. If the source has no VAT qualifier do not add one. "
                 "Every technical or benefit pictogram must depict the meaning of its own "
                 "adjacent label. Never reuse a generic trailer/weight icon for unrelated "
                 "facts. Use a clean typographic row without an icon whenever unsure. "
                 "For technical and dimension lists, readable text is preferable to "
                 "irrelevant, repeated, invented or confusing icons. "
                 "Reserve sufficient space for ALL supplied claims AND benefits before "
                 "decorative graphics; reduce photo area or ornamental elements as needed. "
                 "Before returning the image verify EVERY required row, model, category, "
                 "claim, benefit and both supplied phone numbers. Never sacrifice them "
                 "to enlarge photography.")
    return "\n".join(lines)


def reference_style_direction(fmt: str) -> str:
    """Independent premium art direction; external examples are optional.

    These are artistic cues, NOT pixel coordinates or source facts. Never
    infer brand, product color, construction or section counts from a style.
    """
    common=(
        "INDEPENDENT PREMIUM INDUSTRIAL B2B ART DIRECTION: sophisticated "
        "light or dramatic backgrounds chosen for the actual product, "
        "expressive Russian editorial typography, tasteful brand-color "
        "graphic accents, accurate textual engineering dimension list, "
        "professional product photography, strong hierarchy, restrained "
        "iconography and coherent visual identity. Preserve the exact "
        "vehicle type, color, axle count, construction and branding shown "
        "in the source photograph. The visual language should match a "
        "premium print sales campaign, NOT a web dashboard, spreadsheet, "
        "empty card grid, or a few simplistic blocks pasted onto a photo. "
        "Distinguish all provided specs, engineering dimensions, benefits, "
        "comparison claims, calculated ROI (only when supplied), price "
        "and customer phones. Omit unavailable sections rather than invent "
        "facts or force empty placeholders. Every component "
        "must feel designed together by ONE experienced graphic designer. "
        "Prioritize a LARGE photographic hero with natural light, cinematic "
        "depth, grounded scale, an expressive angled brand masthead and "
        "a recognizably original advertising IDEA. The entire image must "
        "look like a commissioned commercial campaign photographed and "
        "art-directed by humans, not an auto-filled report. Keep factual "
        "tables compact and truly typographic; do NOT turn each feature "
        "into an identical rectangle, card, app widget, generic pictogram "
        "tile or repeated two-column grid. Favor asymmetric professional "
        "editorial rhythm, overlapping photography/background materials "
        "when legible, purposeful brand-color accents and optical "
        "balance. Preserve ALL client facts, but the ONLY constrained "
        "layout constraint is readable framing inside the full native canvas. Create ALL "
        "headings, typography, diagonal motifs, illustrated elements "
        "and picture framing AS PART OF THE FINAL IMAGE. "
        "No subsequent programmatic text renderer exists in this mode. "
    )
    if fmt=="4x3":
        return common+(
            "LANDSCAPE 4:3: design a balanced, high-information AGENCY "
            "PRINT POSTER: striking masthead and slogan when supplied; "
            "one large real product hero in the selected original camera "
            "view; no second product inset; attractive callouts for supplied "
            "claims; carefully typeset full TTH table and every approved "
            "dimension as exact text, actual proof points "
            "and advantages; coherent finance section only if verified; "
            "dominant price/contact CTA if provided. Make the photo and "
            "message command attention FIRST, with the complete credible "
            "technical detail as supporting typographic information. "
            "Use flexible elegant art direction, editorial typography "
            "and expert optical spacing, NOT repetitive black boxes, "
            "equal rectangular cards or a hardcoded coordinate layout. "
            "Photographic story, an appropriate real industrial environment and all "
            "customer material must look integrated. All parts visible. "
        )
    if fmt=="9x16":
        return common+(
            "PORTRAIT 9:16: create a BRAND NEW naturally vertical print "
            "composition; NEVER reflow, crop or squeeze the landscape "
            "poster. Present a cohesive masthead, full actual product "
            "hero and engaging illustrated units for supplied claims. Use "
            "exactly one product depiction in the selected rebranded camera "
            "view; no second visual inset or invented angle. Then design the complete specification "
            "table and exact textual dimensions as polished "
            "portrait information, followed by provided comparison "
            "arguments, advantages, verified economic story, "
            "price and easy-to-read phone CTA only where supplied. "
            "Compose the poster as a deliberate tall vertical visual "
            "narrative: the complete trailer is visually dramatic and "
            "strongly lit, while the technical copy is beautifully "
            "typeset rather than mechanically tiled. Professional "
            "coherent brand-aware editorial print design with negative "
            "space where it improves hierarchy. The final 9:16's "
            "BOTTOM region must be complete designed photographic "
            "and graphic content, NOT a stretched red/gray row or "
            "decorative edge filler. Every element from top to bottom "
            "belongs to ONE unified campaign, not separate UI panels. "
        )
    raise ValueError("Неподдерживаемый формат AI-плаката.")



def combine_style_references(
    exemplar: bytes | None, references: list[bytes] | None,
) -> bytes | None:
    """Make one STYLE-ONLY contact sheet from up to TWO customer examples.

    Two different example formats (landscape and portrait) are visual
    evidence, not sources of numbers/price/customer contact data. User
    uploaded originals are not modified or published. Only the transient
    downsized board is transmitted as an image input to the model.
    """
    import io
    from PIL import Image, ImageOps

    examples=([exemplar] if exemplar else []) + list(references or [])
    if not examples:
        return None
    if len(examples)==1:
        return examples[0]
    chosen=examples[:2]
    # Each source is decoded/resized alone to cap memory on the shared VPS.
    board=Image.new("RGB",(1500,960),"#F4F5F7")
    boxes=((8,10,835,940),(851,10,1492,940))
    for raw,box in zip(chosen,boxes):
        with Image.open(io.BytesIO(raw)) as source:
            source.draft("RGB",(850,920))
            source.thumbnail((850,920),Image.Resampling.LANCZOS)
            rgb=ImageOps.contain(source.convert("RGB"),
                                 (box[2]-box[0],box[3]-box[1]),
                                 method=Image.Resampling.LANCZOS)
        x=box[0]+(box[2]-box[0]-rgb.width)//2
        y=box[1]+(box[3]-box[1]-rgb.height)//2
        board.paste(rgb,(x,y))
    out=io.BytesIO()
    board.save(out,format="JPEG",quality=88,optimize=False)
    return out.getvalue()
