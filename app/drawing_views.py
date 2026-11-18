"""Conservative presentation crops of a user-supplied engineering drawing.

Never invent engineering geometry or overwrite the original image. The
resulting bitmap is used only in poster layouts; source files stay intact in
promo_kit.zip and the presentation crop remains replaceable in CorelDRAW SVG.
"""
from __future__ import annotations

from PIL import Image, ImageOps, ImageFilter


def _side_elevation(drawing):
    """Choose the side view from a two-projection engineering sheet.

    The raw technical drawing is never changed. Only when measured line
    coverage strongly indicates a wide side elevation above a narrow rear
    view do we crop a copy for the compact advert. Other diagrams are kept
    intact rather than blindly cutting their technical annotations.
    """
    if drawing is None or not isinstance(drawing, Image.Image):
        return drawing, False
    w,h = drawing.size
    if w < 400 or h < 400 or not 1.12 <= w/h <= 1.90:
        return drawing, False
    thumb = ImageOps.grayscale(drawing)
    thumb.thumbnail((440, 440), Image.Resampling.BILINEAR)
    tw,th = thumb.size
    pixels=thumb.load()
    def coverage(start,stop):
        ys=range(max(0,int(th*start)),min(th,int(th*stop)),3)
        if not ys:return 0.0
        active=0
        for col in range(3,tw-3):
            dark=0
            for row in ys:
                if pixels[col,row] < 175:
                    dark += 1
                    if dark >= 2:
                        active+=1
                        break
        return active/max(1,tw-6)
    upper=coverage(.12,.32)
    lower=coverage(.60,.88)
    if not (upper >= .27 and upper >= max(.01,lower)*1.85 and lower < .45):
        return drawing, False

    # Extract only the genuine source upper projection, including the
    # trailer's wheels. This is an advertising crop, NOT a new drawing.
    x0=int(w*.025)
    x1=int(w*.975)
    y1=int(h*.36)
    profile=drawing.crop((x0,0,x1,y1)).convert("L")
    # Slightly strengthen the original black technical strokes so that
    # their 1-pixel source lines survive a much smaller print-sized inset.
    profile=ImageOps.autocontrast(profile)
    profile=profile.filter(ImageFilter.MinFilter(3))
    return profile.convert("RGB"), True
