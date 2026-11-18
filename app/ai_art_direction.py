"""Editable, product-faithful visual systems for three AI PRO concepts.

The art director still chooses the palette and seven layout regions. Server
variants give those regions different graphic languages: a dynamic sales
poster, a technical blueprint, and a premium minimalist editorial.

All decoration is pure SVG geometry. Nothing here fabricates a product or
changes factual copy, original photography, or engineering drawings.
"""
from __future__ import annotations
import re


def direction_of(concept):
    ident = concept.get("id") if isinstance(concept, dict) else None
    match = re.fullmatch(r"concept_([012])", ident) if isinstance(ident,str) else None
    return ("sales","engineering","editorial")[int(match.group(1))] if match else "sales"


def line(scene, group, a, b, c, d, color, width, ident, opacity=None):
    return scene.el(group,"line",ident,{"x1":a,"y1":b,"x2":c,"y2":d,
        "stroke":color,"stroke-width":width,"opacity":opacity})


def direction_mark(scene, system, accent):
    scene.rect("decor",0,0,2,scene.h,accent,ident=f"ai-art-system-{system}")


def hero_stage(scene, rect, colors, system):
    """Neutral stage BEHIND the original product; no invented scenery."""
    x,y,w,h=rect
    a=colors["accent"]
    if system=="engineering":
        scene.rect("photos",x,y,w,h,"#213A50",ident="ai-engineering-stage")
        for i in range(1,9):
            line(scene,"photos",x+w*i/9,y,x+w*i/9,y+h,
                 "#B5C9D7",1,f"ai-blueprint-vertical-{i}",".20")
        for i in range(1,6):
            line(scene,"photos",x,y+h*i/6,x+w,y+h*i/6,
                 "#B5C9D7",1,f"ai-blueprint-horizontal-{i}",".20")
        scene.polygon("photos",[(x,y+h*.76),(x+w,y+h*.60),
                      (x+w,y+h),(x,y+h)],"#152C40",
                      ident="ai-blueprint-ground")
        scene.rect("photos",x,y,7,h,a,ident="ai-engineering-photo-rail")
    elif system=="editorial":
        scene.rect("photos",x,y,w,h,"#F5F3EE",ident="ai-editorial-stage")
        scene.el("photos","ellipse","ai-editorial-halo",{
            "cx":x+w*.55,"cy":y+h*.46,
            "rx":w*.36,"ry":h*.49,"fill":"#E5E1D7","opacity":".9"})
        scene.polygon("photos",[(x,y+h*.89),(x+w,y+h*.74),
                      (x+w,y+h),(x,y+h)],"#EDE9E1",
                      ident="ai-editorial-floor")
        line(scene,"photos",x+24,y+19,x+w*.24,y+19,a,3,
             "ai-editorial-top-line")
    else:
        scene.rect("photos",x,y,w,h,"#E9EEF3",ident="ai-sales-stage")
        scene.polygon("photos",[(x,y),(x+w*.52,y),
                      (x+w*.17,y+h),(x,y+h)],"#F9FAFC",
                      ident="ai-sales-light")
        scene.polygon("photos",[(x+w*.74,y),(x+w,y),
                      (x+w*.62,y+h),(x+w*.40,y+h)],a,
                      ident="ai-sales-speed-wedge",opacity=".10")
        scene.polygon("photos",[(x,y+h*.78),(x+w,y+h*.59),
                      (x+w,y+h),(x,y+h)],"#CCD8E1",
                      ident="ai-sales-floor")
        scene.rect("photos",x,y,10,h*.74,a,ident="ai-sales-photo-spine")


def hero_frame(scene, rect, colors, system):
    """Visible edge accents, not overlays obscuring the original product."""
    x,y,w,h=rect
    a=colors["accent"]
    if system=="engineering":
        for i,(px,py,sign) in enumerate(((x+12,y+12,1),(x+w-12,y+h-12,-1))):
            line(scene,"photos",px,py,px+sign*24,py,"#FFFFFF",2.2,
                 f"ai-engineering-corner-h-{i}",".8")
            line(scene,"photos",px,py,px,py+sign*24,"#FFFFFF",2.2,
                 f"ai-engineering-corner-v-{i}",".8")
    elif system=="editorial":
        scene.el("photos","rect","ai-editorial-photo-outline",{
            "x":x+7,"y":y+7,"width":max(2,w-14),"height":max(2,h-14),
            "fill":"none","stroke":"#CCD0CF","stroke-width":1.4})
        scene.rect("photos",x+w-30,y+7,23,5,a,ident="ai-editorial-corner")
    else:
        scene.polygon("photos",[(x+w*.70,y+h-7),(x+w,y+h-7),
                      (x+w,y+h),(x+w*.69,y+h)],a,
                      ident="ai-sales-bottom-slash")


def panel_detail(scene, layer, rect, system, accent):
    x,y,w,h=rect
    if system=="engineering":
        scene.rect(layer,x+w-4,y+4,2,max(2,h-8),accent,
                   ident=f"ai-blueprint-{layer}-edge")
    elif system=="editorial":
        scene.rect(layer,x+6,y+h-3,max(2,w-12),1,"#D5D5D0",
                   ident=f"ai-editorial-{layer}-rule")
    else:
        scene.polygon(layer,[(x+w-28,y),(x+w,y),
                      (x+w,y+11),(x+w-36,y+11)],accent,
                      ident=f"ai-sales-{layer}-flag",opacity=".72")
