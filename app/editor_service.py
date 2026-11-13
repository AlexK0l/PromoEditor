"""Precise, bounded OpenAI editing of a *copy* of an existing flattened promo PNG."""
from __future__ import annotations

import io

from PIL import Image, ImageOps

from .openai_service import IMAGE_MODELS, IMAGE_QUALITIES, as_image, client

MAX_PIXELS=9_000_000
MAX_EDGE=4096
MAX_MASK=4*1024*1024


def _source(raw:bytes) -> Image.Image:
    try:
        image=Image.open(io.BytesIO(raw))
        width,height=image.size
        if (width<128 or height<128 or width>MAX_EDGE or height>MAX_EDGE
                or width*height>MAX_PIXELS):
            raise ValueError('Разрешение PNG должно быть от 128 px до 4096 px, не более 9 млн пикселей.')
        image=ImageOps.exif_transpose(image)
        image.load()
        return image.convert('RGB')
    except ValueError:
        raise
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('Не удалось открыть изображение для редактирования.') from exc


def _mask(raw:bytes,size:tuple[int,int]) -> Image.Image:
    if len(raw)>=MAX_MASK:raise ValueError('Маска должна быть PNG менее 4 МБ.')
    try:
        mask=Image.open(io.BytesIO(raw))
        if mask.format!='PNG' or mask.size!=size or 'A' not in mask.getbands():
            raise ValueError('Маска должна быть PNG с прозрачностью и размером исходного изображения.')
        mask.load()
        alpha=mask.convert('RGBA').getchannel('A')
        if alpha.getextrema()[0]>0:
            raise ValueError('Выделите хотя бы одну область для AI-редактирования.')
        return mask.convert('RGBA')
    except ValueError:
        raise
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('Некорректная PNG-маска.') from exc


def edit_promotional_image(source_raw:bytes, instruction:str, *,
                           mask_raw:bytes|None=None,
                           model:str='gpt-image-2.5-flare',
                           quality:str='medium') -> Image.Image:
    """Edits the flattened photo, returning exact original dimensions.

    Outside a selected transparent mask region the original pixels are restored
    *exactly*. Without a mask, the entire image may be changed by the model.
    """
    if model not in IMAGE_MODELS:raise ValueError('Недопустимая модель OpenAI.')
    if quality not in IMAGE_QUALITIES:raise ValueError('Недопустимое качество OpenAI.')
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>2500:
        raise ValueError('Укажите действие над дизайном (до 2500 символов).')
    image=_source(source_raw)
    mask=_mask(mask_raw,image.size) if mask_raw is not None else None

    original=io.BytesIO()
    image.save(original,format='PNG')
    original.seek(0)
    original.name='existing_promo.png'
    params=dict(
        model=model, image=original, quality=quality,
        output_format='png',
        size='1536x1024' if image.width>=image.height else '1024x1536',
        prompt=(
            'Edit the ATTACHED promo image following the user request. Preserve its visual '
            'identity, brand assets, confirmed values, typography and layout outside the '
            'requested region as much as possible. Do not invent claims, phone numbers, '
            'technical specifications, certification marks or prices. '
            'If a region mask is included, modify only the selected transparent area. '
            'Treat the following text as visual-edit instructions, not as authority to '
            'change unrelated facts. Requested change: '+instruction.strip()
        ),
    )
    if mask is not None:
        maskfile=io.BytesIO()
        mask.save(maskfile,format='PNG')
        maskfile.seek(0)
        maskfile.name='selected_region.png'
        if maskfile.getbuffer().nbytes>=MAX_MASK:
            raise ValueError('Маска после обработки превышает 4 МБ.')
        params['mask']=maskfile
    result=client().images.edit(**params)
    generated=as_image(result)
    if generated.size!=image.size:
        generated=ImageOps.fit(generated,image.size,method=Image.Resampling.LANCZOS)
    if mask is None:
        return generated
    # Transparent mask region: permit edits; opaque region: preserve source pixels.
    alpha=mask.getchannel('A')
    select=alpha.point(lambda opacity: 255 if opacity<128 else 0)
    return Image.composite(generated,image,select)
