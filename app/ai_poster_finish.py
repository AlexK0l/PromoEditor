"""Masked generative finishing of paid artwork. No procedural ad rendering.

Only new pixels from OpenAI are used in the explicitly editable region.
All other final-size RGB pixels are copied back from the original image.
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageChops, ImageDraw, ImageStat

from .ai_artwork_fit import TARGETS, MATTE_RGB
from .ai_quota import check_paid_capacity, QuotaExceeded, QuotaStoreUnavailable
from .ai_transport import edit_paid_image_once
from .openai_service import (
    IMAGE_MODELS, IMAGE_QUALITIES, client, as_image,
    _cached_visual, _save_visual, _default_visual_cache, _visual_lock,
)

VERSION = "masked-poster-finish-v1"


def _png(image, name):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    buffer.name = name
    return buffer


def _box(value, size):
    if (not isinstance(value,(list,tuple)) or len(value)!=4 or
            any(type(n) is not int for n in value)):
        raise ValueError("Некорректные координаты области.")
    x,y,r,b=value
    if not (0<=x<r<=size[0] and 0<=y<b<=size[1]):
        raise ValueError("Область выходит за границы плаката.")
    return x,y,r,b


def _settings(model, quality):
    if model not in IMAGE_MODELS or quality not in IMAGE_QUALITIES:
        raise ValueError("Недопустимые настройки OpenAI Images.")


def _work_box(size, canvas_size):
    # Uniform scaling to an integer content rectangle; rounding is bounded
    # to a pixel. The supported API canvas may have a different aspect.
    w,h=size
    cw,ch=canvas_size
    scale=min(cw/w,ch/h)
    rw,rh=max(1,round(w*scale)),max(1,round(h*scale))
    x,y=(cw-rw)//2,(ch-rh)//2
    return x,y,x+rw,y+rh


def _map_box(box, source_size, work_box):
    w,h=source_size
    x,y,r,b=work_box
    rw,rh=r-x,b-y
    return (x+math.floor(box[0]*rw/w),y+math.floor(box[1]*rh/h),
            x+math.ceil(box[2]*rw/w),y+math.ceil(box[3]*rh/h))


def _workspace(source, canvas_size):
    work_box=_work_box(source.size,canvas_size)
    x,y,r,b=work_box
    work=Image.new("RGB",canvas_size,MATTE_RGB)
    work.paste(source.resize((r-x,b-y),Image.Resampling.LANCZOS),(x,y))
    return work,work_box


def _mask(canvas_size, box, *, protect):
    # Images API: transparent = editable; opaque = protected. Deliberately
    # binary boundaries. The server also enforces them on final output.
    alpha=Image.new("L",canvas_size,0 if protect else 255)
    x,y,r,b=box
    ImageDraw.Draw(alpha).rectangle((x,y,r-1,b-1),fill=255 if protect else 0)
    mask=Image.new("RGBA",canvas_size,(255,255,255,255))
    mask.putalpha(alpha)
    return mask


def _candidate(work, mask, prompt, *, model, quality, attempt, operation):
    _settings(model,quality)
    source_file=_png(work,"work_canvas.png")
    mask_file=_png(mask,"editable_region.png")
    cache=_default_visual_cache(
        {"operation":operation,"attempt":str(attempt),"prompt":prompt},
        True,[source_file.getvalue(),mask_file.getvalue()],model,quality,
        VERSION,"masked-finish")
    with _visual_lock(cache):
        image=_cached_visual(cache,"candidate")
        if image is None:
            check_paid_capacity("image",1)
            result=edit_paid_image_once(
                client(),operation,model=model,image=source_file,mask=mask_file,
                prompt=prompt,size=f"{work.width}x{work.height}",
                quality=quality,output_format="png")
            image=as_image(result)
            # Save the paid response even if later validation rejects it.
            _save_visual(cache,"candidate",image)
        if image.size!=work.size:
            raise ValueError("OpenAI вернул холст неподходящего размера.")
        return image


def _bands(size, protected_box):
    w,h=size
    x,y,r,b=protected_box
    result=[]
    for side,box in (
            ("top",(0,0,w,y)),("bottom",(0,b,w,h)),
            ("left",(0,y,x,b)),("right",(r,y,w,b))):
        if box[2]>box[0] and box[3]>box[1]:
            result.append((side,box))
    return result


def _blank(image):
    return image.getextrema()==tuple((v,v) for v in MATTE_RGB)


def _check_extension(result, protected_box):
    """Reject obvious blank strips and exact repeated-row/column artifacts.

    This is a structural sanity check, not an artistic or semantic guarantee.
    """
    x,y,r,b=protected_box
    for side,box in _bands(result.size,protected_box):
        strip=result.crop(box)
        if _blank(strip):
            raise ValueError("OpenAI оставил незаполненное поле.")
        thickness=strip.height if side in ("top","bottom") else strip.width
        if thickness>=4:
            if side in ("top","bottom"):
                before=strip.crop((0,0,strip.width,strip.height-1))
                after=strip.crop((0,1,strip.width,strip.height))
            else:
                before=strip.crop((0,0,strip.width-1,strip.height))
                after=strip.crop((1,0,strip.width,strip.height))
            if ImageChops.difference(before,after).getbbox() is None:
                raise ValueError("Дорисовка состоит из повторённых строк или столбцов.")
            if max(ImageStat.Stat(strip).stddev)<0.8:
                raise ValueError("Дорисовка оставила почти однородное пустое поле.")
        # Check the seam only across the original protected region. A very
        # discontinuous generated border is not delivered as a finished bleed.
        if side=="top":
            a,c=result.crop((x,y-1,r,y)),result.crop((x,y,r,y+1))
        elif side=="bottom":
            a,c=result.crop((x,b-1,r,b)),result.crop((x,b,r,b+1))
        elif side=="left":
            a,c=result.crop((x-1,y,x,b)),result.crop((x,y,x+1,b))
        else:
            a,c=result.crop((r-1,y,r,b)),result.crop((r,y,r+1,b))
        if sum(ImageStat.Stat(ImageChops.difference(a,c)).mean)/3>65:
            raise ValueError("На стыке дорисовки образовалась заметная граница.")


def expand_artwork(source, content_box, *, model, quality, attempt=""):
    """Fill only the previous matte using ONE paid masked generative edit.

    The target canvas remains exactly 1440x1080 or 1080x1920. We never use
    a resized/generated substitute for the already composed central artwork.
    """
    _settings(model,quality)
    source=source.convert("RGB")
    if source.size not in TARGETS:
        raise ValueError("Неподдерживаемый размер плаката.")
    box=_box(content_box,source.size)
    bands=_bands(source.size,box)
    if not bands:
        return source,{"status":"not_needed","protected_box":list(box)}
    if any(not _blank(source.crop(b)) for _,b in bands):
        raise ValueError("За пределами исходной композиции уже есть изображение; перезапись запрещена.")
    canvas=(1536,1024) if source.width>source.height else (1024,1536)
    work,work_box=_workspace(source,canvas)
    protected=_map_box(box,source.size,work_box)
    mask=_mask(canvas,protected,protect=True)
    prompt=(
        "MASKED OUTPAINTING ONLY. The opaque central image is a FINISHED advertisement. "
        "Do NOT redraw, resize, move, relabel or replace any part of it. The transparent "
        "regions are empty margins. Continue the existing adjacent sky, background texture, "
        "graphic colors and decorative shapes naturally into ALL transparent regions. "
        "Make continuous full-bleed artwork, without empty bars, repeated edge rows, mirrors, "
        "blurred filler, extra objects, text, numbers, logos, price, watermarks or vehicles. "
        "Keep the input canvas dimensions and exact position of the protected artwork. "
        "Only create new background pixels outside it. The server will preserve the entire "
        "central advertisement exactly. No changes to layout, facts, or product are requested."
    )
    candidate=_candidate(work,mask,prompt,model=model,quality=quality,
                         attempt=attempt,operation="outpaint")
    generated=candidate.crop(work_box).resize(source.size,Image.Resampling.LANCZOS)
    # Pixel-exact restoration: even if Images ignores the mask, no original
    # content can be changed. Only the new surrounding pixels are retained.
    generated.paste(source.crop(box),box[:2])
    _check_extension(generated,box)
    return generated,{"status":"complete","protected_box":list(box),
                      "api_canvas":list(canvas),"api_content_box":list(work_box),
                      "generated_bands":[{"side":s,"box":list(b)} for s,b in bands]}


def try_expand_artwork(source, geometry, *, model, quality, attempt=""):
    """Never discard paid artwork if the finishing call fails."""
    box=geometry.get("content_box")
    if geometry.get("outpaint",{}).get("status") in ("complete","not_needed"):
        return source,geometry["outpaint"]
    try:
        return expand_artwork(source,box,model=model,quality=quality,attempt=attempt)
    except (QuotaExceeded,QuotaStoreUnavailable):
        reason="Недоступна квота для дорисовки. Исходный плакат сохранён с полями."
    except Exception:
        reason=("Дорисовка не завершена или не прошла проверку границ. "
                "Исходный плакат сохранён с полями. Автоматических повторов нет.")
    return source,{"status":"failed","protected_box":box,"reason":reason}


def validate_repair(source_size, region, instruction):
    if source_size not in TARGETS:
        raise ValueError("Неподдерживаемый размер плаката.")
    x,y,r,b=_box(region,source_size)
    if min(r-x,b-y)<6 or (r-x)*(b-y)>source_size[0]*source_size[1]*0.5:
        raise ValueError("Выделите локальную область от 6 px, не более половины плаката.")
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>2500:
        raise ValueError("Опишите точную правку (до 2500 символов).")
    return x,y,r,b


def repair_artwork(source, region, instruction, *, model, quality, attempt=""):
    """One masked edit of a local context crop, not a new poster generation."""
    _settings(model,quality)
    source=source.convert("RGB")
    x,y,r,b=validate_repair(source.size,region,instruction)
    w,h=source.size
    px=max(32,(r-x)//3)
    py=max(32,(b-y)//2)
    context=(max(0,x-px),max(0,y-py),min(w,r+px),min(h,b+py))
    cx,cy,_,_=context
    local=(x-cx,y-cy,r-cx,b-cy)
    patch=source.crop(context)
    canvas=(1536,1024) if patch.width>=patch.height else (1024,1536)
    work,work_box=_workspace(patch,canvas)
    mapped=_map_box(local,patch.size,work_box)
    mask=_mask(canvas,mapped,protect=False)
    prompt=(
        "LOCAL MASKED CORRECTION of the attached existing advertisement detail. "
        "Correct only the transparent area; keep the existing text alignment, "
        "font style, background texture, row spacing and colors. Remove erroneous "
        "duplicate digits/symbols instead of adding another value. Render only the "
        "requested text exactly once where specified. No invented claims, new logos, "
        "new rows, extra decorations or unrelated changes. Preserve the exact "
        "position and scale of all neighboring content; return the same canvas. "
        "Requested correction: "+instruction.strip()
    )
    candidate=_candidate(work,mask,prompt,model=model,quality=quality,
                         attempt=attempt,operation="repair")
    updated_context=candidate.crop(work_box).resize(patch.size,Image.Resampling.LANCZOS)
    result=source.copy()
    result.paste(updated_context.crop(local),(x,y))
    return result,{"status":"complete","region":[x,y,r,b],
                   "context_box":list(context),"api_canvas":list(canvas),
                   "api_content_box":list(work_box)}
