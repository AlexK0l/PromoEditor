"""Promo Studio web application: local-first, server-side OpenAI integration."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from PIL import Image, ImageDraw

from .documents import ALLOWED_DOCS, extract_text, heuristics, pdf_first_page_png
from .openai_service import (analyze_documents, generate_visuals,
                             _cached_visual, _default_visual_cache,
                             _finish_visual_cache)
from .ai_poster_service import (generate_full_posters, WARNING as AI_POSTER_WARNING,
                                VERSION as AI_POSTER_VERSION)
from . import ai_job_queue
from .product_rebrand_service import (
    rebrand_selected_photo, cache_dir as rebrand_cache_dir,
    cached_photo as cached_rebrand_photo, REBRAND_WARNING,
)
from .ai_exact_copy_template import (
    generate_exact_typography_posters, consume_paid_template_cache,
    AI_WARNING as EXACT_COPY_WARNING,
    _rasterize_in_worker,
)
from .ai_technical_sheet import render_technical_sheet
from .ai_transport import OpenAIImageConnectionFailure
from .ai_quota import QuotaExceeded, QuotaStoreUnavailable, check_paid_capacity
from .editor_service import edit_promotional_image
from .render import default_brief, image_bytes, load_image, render_poster, valid_hex
from .image_analysis import validate_image_dimensions
from .editable_export import build_promo_prompt, create_editable_svg, rasterize_svg
from .ai_layout import generate_concepts, STYLES, GOALS
from .ai_concept_renderer import render_ai_concept_svg
from .approved_presets import approved_zubrtrail_500
from .hybrid_art_director import art_directed_layout
from .ai_full_artwork_service import generate_complete_artworks, VERSION as FULL_ARTWORK_VERSION
from .ai_full_poster import render_ai_full_poster_svg
from .asset_selection import analyze_project, chosen_bytes
from .auth import enabled as auth_enabled, guard as password_guard, login_get, login_post, logout_post, issue_form_token

BASE=Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE/'.env')
except ImportError:
    pass
STATIC=BASE/'app'/'static'
STORAGE=Path(os.getenv('PROMO_DATA_DIR',str(BASE/'instance'/'jobs')))
STORAGE.mkdir(parents=True,exist_ok=True)

MAX_FILE=20*1024*1024
MAX_ALL=68*1024*1024
MAX_FILES=16  # Across photos, documents, logos, references and drawings
TTL_SECONDS=int(os.getenv('PROMO_JOB_TTL_SECONDS','7200'))
LIMIT=int(os.getenv('PROMO_REQUESTS_PER_HOUR','20'))
RATE=defaultdict(list)
LOCK=threading.Lock()
RENDER_LOG=logging.getLogger('uvicorn.error')

class PartialPosterFailure(RuntimeError):
    """A paid generation failed but its already created images were preserved."""

    def __init__(self, recovery_zip: str, cause: Exception):
        super().__init__("Partially generated artwork was preserved")
        self.recovery_zip = recovery_zip
        self.cause_type = type(cause).__name__
        # Only expose fixed, allowlisted network explanations, never raw
        # SDK exception strings, customer prompts, file paths or headers.
        self.public_reason = (cause.public_reason if isinstance(
            cause, OpenAIImageConnectionFailure) else None)

# Bound 6-preview renders inside a worker, especially on the 2-GB VPS.
CONCEPT_RENDER_SLOTS=threading.BoundedSemaphore(1)
# One expensive paid image workflow at a time on an 800 MiB VPS.
MAIN_AI_GENERATION_SLOT=threading.BoundedSemaphore(1)
ALLOWED_IMAGES={'.png','.jpg','.jpeg','.webp'}
FILES={'poster_4x3.png','poster_9x16.png','poster_4x3.jpg','poster_9x16.jpg',
       'corel_4x3.svg','corel_9x16.svg','promo_prompt.txt','promo_kit.zip','brief.json','asset_selection.json','layout_spec.json','edit.png'}
FILES.update({f'concept_{i}_{fmt}.png' for i in range(3) for fmt in ('4x3','9x16')})
FILES.update({f'ai_poster_{fmt}.{ext}' for fmt in ('4x3','9x16') for ext in ('png','jpg')})
FILES.update({'ai_posters.zip','ai_failed_generation.zip','rebranded_product.png',
              'technical_sheet.svg','technical_sheet.png','technical_sheet.jpg',
              'ai_typographic_posters.zip','typography_layout.json',
              'typography_style.json','verified_copy.json','poster_copy.json','selected_photo.json'})
FILES.update({f'ai_template_{fmt}.png' for fmt in ('4x3','9x16')})
JOB_ID=re.compile(r'^[a-f0-9]{32}$')

app=FastAPI(title='Promo Studio',description='Генератор рекламной инфографики 4:3 и 9:16 на основе OpenAI API',version='1.0.0')
app.mount('/static',StaticFiles(directory=str(STATIC)),name='static')

@app.middleware('http')
async def password_auth_middleware(request:Request,call_next):
    return await password_guard(request,call_next)

@app.get('/theme.js')
def public_theme_script():
    # A single harmless UI asset is available on the login page before auth.
    # Other /static resources and ALL APIs remain private.
    return FileResponse(STATIC/'theme.js',media_type='text/javascript',headers={'Cache-Control':'public, max-age=3600'})

@app.get('/login')
async def password_login_page(request:Request):
    return await login_get(request)

@app.post('/login')
async def password_login_submit(request:Request):
    return await login_post(request)

@app.post('/logout')
async def password_logout(request:Request):
    return await logout_post(request)



# Some clients display an entirely unstyled document even while the VPS
# returns HTTP 200 for the external .css files. Serve the exact same CSS
# inline as an independent, same-response fallback so the browser does not
# depend on a second round trip to render a usable interface. The four
# original stylesheet files remain canonical; no duplicated CSS to drift.
@lru_cache(maxsize=1)
def _home_html() -> str:
    html = (STATIC/'index.html').read_text(encoding='utf-8')
    marker = '<!-- PROMOEDITOR_EMBEDDED_STYLES -->'
    if html.count(marker) != 1:
        raise RuntimeError('Missing unique embedded stylesheet marker')
    names = ('app.css','editor.css','theme.css','assets.css')
    pieces = [(STATIC/name).read_text(encoding='utf-8') for name in names]
    if any('</style' in piece.lower() for piece in pieces):
        raise RuntimeError('Unexpected HTML tag in local stylesheet')
    css = '\n'.join(pieces)
    return html.replace(
        marker,
        '<style id="promoeditor-embedded-styles">\n'+css+'\n</style>',
    )


@app.get('/')
def home():
    # Never serve stale HTML pointing to an older JS/CSS set after a release.
    return HTMLResponse(_home_html(),headers={'Cache-Control':'no-store'})


@app.get('/api/config')
def config():
    return {'openai_ready':bool(os.getenv('OPENAI_API_KEY')),
            'auth_enabled':auth_enabled(),
            'logout_csrf_token':issue_form_token('logout') if auth_enabled() else None,
            'image_models':['gpt-image-2.5-flare','gpt-image-2.5-sunburst'],
            'max_file_mb':20,'max_files':MAX_FILES,'multi_assets':True,'asset_analysis':True,'formats':[{'id':'4x3','size':[1440,1080]},{'id':'9x16','size':[1080,1920]}],
            'preview':True,'generation_modes':['hybrid','ai_pro','template'],'ai_concepts':3,'reference_required':False,
            'export_formats':['png','jpeg','svg'],'editable_format':'svg'}


@app.get('/api/demo')
def demo():
    return {'brief':default_brief(),
            'reference_4x3':'/static/demo_4x3.svg',
            'reference_9x16':'/static/demo_9x16.svg',
            'sample_hero':'/static/demo_4x3.svg'}


@app.get('/api/presets/zubrtrail-500')
def approved_zubrtrail_preset():
    return {'brief':approved_zubrtrail_500(),
            'source':'Утверждённый рекламный эталон ZubrTrail 500 от 18.11.2026',
            'notice':'Загрузите оригинальные фотографии, логотип и чертёж самостоятельно.'}


def _clean_jobs():
    now=time.time()
    for path in STORAGE.iterdir():
        try:
            if path.is_dir() and JOB_ID.fullmatch(path.name) and now-path.stat().st_mtime>TTL_SECONDS:
                shutil.rmtree(path,ignore_errors=True)
        except OSError:
            pass


def _guard_rate(request:Request):
    ip=request.client.host if request.client else 'local'
    now=time.monotonic()
    with LOCK:
        recent=[x for x in RATE[ip] if now-x<3600]
        if len(recent)>=LIMIT:
            raise HTTPException(429,detail='Превышен лимит запросов на создание материалов. Попробуйте позднее.')
        recent.append(now);RATE[ip]=recent


def _validate_uploaded_image(name: str, raw: bytes) -> None:
    """Verify Pillow image dimensions and integrity in a worker thread."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            validate_image_dimensions(*img.size)
            img.verify()
    except ValueError as exc:
        raise HTTPException(400,detail=f'{name}: {exc}') from exc
    except Exception as exc:
        raise HTTPException(400,detail=f'{name}: файл не является корректным изображением') from exc


async def _files(form,field,extensions,collection=False):
    items=form.getlist(field) if collection else [form.get(field)]
    out=[]
    for up in items:
        if up is None or not isinstance(up,UploadFile) or not up.filename:continue
        name=Path(up.filename).name[:160]
        extension=Path(name).suffix.lower()
        if extension not in extensions:raise HTTPException(400,detail=f'{name}: неподдерживаемый формат файла. Допустимые: {", ".join(sorted(extensions))}')
        raw=await up.read(MAX_FILE+1)
        if len(raw)>MAX_FILE:raise HTTPException(413,detail=f'{name}: превышен лимит 20 МБ на файл')
        if not raw:continue
        if extension in ALLOWED_IMAGES:
            await asyncio.to_thread(_validate_uploaded_image,name,raw)
        out.append((name,raw))
    return out


def _normalize(data):
    if not isinstance(data,dict):raise HTTPException(400,detail='Некорректная форма данных')
    clean={}
    for key,lim in [('brand',70),('category',100),('model',80),('slogan',250),('design_notes',1800),('design_actions',1200),('price',30),('currency',12)]:
        clean[key]=str(data.get(key,''))[:lim].strip()
    clean['accent']=valid_hex(data.get('accent','#E31B26'))
    clean['style']=str(data.get('style','industrial')) if data.get('style') in {'industrial','graphite','minimal','reference_pro'} else 'industrial'
    clean['vat']=bool(data.get('vat',True));clean['show_roi']=bool(data.get('show_roi',False))
    for key,count,lim in [('benefits',12,160),('hero_claims',4,120),('proof_points',4,160),('phones',2,48)]:
        value=data.get(key,[])
        clean[key]=[str(v).strip()[:lim] for v in value[:count] if str(v).strip()] if isinstance(value,list) else []
    for key,n in [('specs',12),('dimensions',8)]:
        values=data.get(key,[]);clean[key]=[]
        if isinstance(values,list):
            for pair in values[:n]:
                if isinstance(pair,(list,tuple)) and len(pair)>=2:
                    a=str(pair[0]).strip()[:90];b=str(pair[1]).strip()[:160]
                    if a and b:clean[key].append([a,b])
    r=data.get('roi') or {};clean['roi']={}
    for k in ['extra_payload','distance','rate','trips','years','baseline_price']:
        clean['roi'][k]=str(r.get(k,0)).strip()[:30] if isinstance(r,dict) else '0'
    return clean


async def _asset_groups(form):
    """New plural API with legacy single-file field compatibility.

    The same ID order is built in both /api/analyze-assets and /api/generate:
    photo_1... from photos/hero followed by optional detail, logo_1...,
    document_1..., reference_1..., drawing_1.
    """
    photos=await _files(form,'photos',ALLOWED_IMAGES,collection=True)
    legacy_photos=await _files(form,'hero',ALLOWED_IMAGES,collection=True)
    photos+=legacy_photos
    photos+=await _files(form,'detail',ALLOWED_IMAGES,collection=True)
    logos=await _files(form,'logos',ALLOWED_IMAGES,collection=True)
    logos+=await _files(form,'logo',ALLOWED_IMAGES,collection=True)
    docs=await _files(form,'documents',ALLOWED_DOCS,collection=True)
    refs=await _files(form,'references',ALLOWED_IMAGES,collection=True)
    drawings=await _files(form,'drawings',ALLOWED_IMAGES|{'.pdf'},collection=True)
    drawings+=await _files(form,'drawing',ALLOWED_IMAGES|{'.pdf'},collection=True)
    backgrounds=await _files(form,'background',ALLOWED_IMAGES,collection=True)
    backgrounds+=await _files(form,'backgrounds',ALLOWED_IMAGES,collection=True)
    examples=await _files(form,'reference_example',ALLOWED_IMAGES,collection=True)
    groups={'photos':photos,'logos':logos,'documents':docs,
            'references':refs,'drawings':drawings,'backgrounds':backgrounds,
            'reference_examples':examples}
    all_items=sum(groups.values(),[])
    if len(all_items)>MAX_FILES:
        raise HTTPException(400,detail=f'Не более {MAX_FILES} файлов в проекте.')
    if sum(len(raw) for _,raw in all_items)>MAX_ALL:
        raise HTTPException(413,detail='Общий объём вложений превышает лимит 68 МБ.')
    return groups


def _asset_review(form):
    preferences=form.get('asset_preferences','{}')
    cached=form.get('asset_report')
    if not isinstance(preferences,str) or len(preferences)>6000:
        raise HTTPException(400,detail='Слишком много настроек материалов.')
    if cached is not None and (not isinstance(cached,str) or len(cached)>55000):
        raise HTTPException(400,detail='Слишком большой отчёт анализа.')
    return preferences,cached


@app.post('/api/analyze-assets')
async def analyze_assets(request:Request):
    """Analyze ALL source uploads first; user reviews choices before generation."""
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Общий размер загрузки превышает 68 МБ.')
    form=await request.form()
    groups=await _asset_groups(form)
    if not any(groups.values()):
        raise HTTPException(400,detail='Добавьте хотя бы один файл для анализа.')
    prefs,cached=_asset_review(form)
    use_ai=str(form.get('use_ai','false')).lower()=='true'
    if use_ai:
        _guard_rate(request)
        if not os.getenv('OPENAI_API_KEY'):
            raise HTTPException(400,detail='Для AI-анализа необходим OPENAI_API_KEY на VPS. Бесплатная техническая оценка доступна без ключа.')
    raw=form.get('payload','{}')
    if not isinstance(raw,str) or len(raw)>48000:
        raise HTTPException(400,detail='Слишком большой бриф проекта.')
    try:brief=_normalize(json.loads(raw))
    except json.JSONDecodeError:raise HTTPException(400,detail='Некорректный JSON брифа.')
    try:
        report,_=await asyncio.to_thread(
            analyze_project,groups,prefs,cached_report=cached,use_ai=use_ai,
            requirements=brief.get('design_notes','')+' '+brief.get('design_actions',''))
        prompt=build_promo_prompt(brief,report) if brief.get('model') else ''
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc))
    except Exception as exc:
        raise HTTPException(502,detail=f'Анализ материалов не удался ({type(exc).__name__}). Проверьте входные файлы и OpenAI.')
    report['suggested_prompt']=prompt
    return report


def _demo_hero():
    """Original geometric demo trailer; contains no client artwork."""
    im=Image.new('RGBA',(1150,600),(0,0,0,0))
    d=ImageDraw.Draw(im)
    d.polygon([(160,160),(850,130),(1020,190),(1005,420),(250,458)],fill='#F4BC0F',outline='#C78F00',width=7)
    d.polygon([(850,130),(1020,190),(1005,420),(860,375)],fill='#D5A20B')
    d.line([(250,458),(1005,420)],fill='#343942',width=30)
    d.rectangle((185,400,980,444),fill='#30333B')
    d.rectangle((110,330,185,438),fill='#4C4E54')
    for x in [675,790,905]:
        d.ellipse((x-62,402,x+62,526),fill='#25272D')
        d.ellipse((x-38,426,x+38,502),fill='#A5ABB4')
        d.ellipse((x-14,450,x+14,478),fill='#3B414A')
    d.rectangle((260,440,285,528),fill='#5A6068')
    d.rectangle((360,440,385,528),fill='#5A6068')
    d.line([(300,190),(800,165)],fill='#FCE89D',width=8)
    return im


def _generate_sync(brief,hero_raw,detail_raw,logo_raw,drawing_raw,references,
                   use_demo,use_openai,model,quality,design_prompt,asset_report=None,
                   background_raw=None,concept=None,concept_set_id=None,
                   reference_example_raw=None,generation_mode='template'):
    _clean_jobs()
    job_id=secrets.token_hex(16)
    folder=STORAGE/job_id;folder.mkdir(mode=0o700)
    clock=time.monotonic()
    RENDER_LOG.info("Render started: mode=%s",generation_mode)
    try:
        hero=load_image(hero_raw)
        detail=load_image(detail_raw)
        logo=load_image(logo_raw)
        drawing=load_image(drawing_raw)
        user_backdrop=load_image(background_raw)
        RENDER_LOG.info("Input images decoded: %.1fs",time.monotonic()-clock)
        if hero is None and use_demo and not use_openai:
            hero=_demo_hero()
        if generation_mode == 'hybrid':
            # OpenAI plans the placement and graphic hierarchy for BOTH
            # formats. Technical facts are never accepted from the model.
            if not hero_raw or not use_openai:
                raise ValueError('Для AI-дизайна необходимо фото товара и OpenAI.')
            if concept is not None:
                raise ValueError('Гибридный арт-директор не принимает внешний концепт.')
            concept=art_directed_layout(
                brief, hero_raw, reference=reference_example_raw)
        visuals={}
        ai_product=False
        paid_cache=None
        scene_direction=concept['scene_prompt'] if concept else ''
        regions=concept['layouts'] if concept is not None else None
        if regions and generation_mode=='hybrid':
            # Distinct visual cache for each AI-selected spatial composition.
            scene_direction+=(' | product safe zones: '+
                              json.dumps({k:v['hero'] for k,v in regions.items()},
                                         sort_keys=True))
        if use_openai:
            if generation_mode=='hybrid':
                # AI makes the ENTIRE poster artwork, not a background.
                # The deterministic pass below overlays ONLY verified facts
                # and customer's unchanged product, logo and drawing.
                artwork_direction=json.dumps(
                    concept, ensure_ascii=False, sort_keys=True)
                paid_cache=_default_visual_cache(
                    brief, True, [], model, quality,
                    FULL_ARTWORK_VERSION, artwork_direction)
                visuals=generate_complete_artworks(
                    brief, concept, model=model, quality=quality,
                    cache_dir=paid_cache, consume_cache=False)
            else:
                # Expert AI-PRO and optional template backgrounds retain their
                # previous explicitly chosen behavior.
                scene_references=references
                paid_cache=_default_visual_cache(
                    brief, hero is not None, scene_references, model, quality,
                    design_prompt, scene_direction)
                visuals=generate_visuals(
                    brief,hero_present=(hero is not None),
                    references=scene_references,model=model,quality=quality,
                    design_prompt=design_prompt,scene_direction=scene_direction,
                    cache_dir=paid_cache,consume_cache=False,hero_regions={
                        k:v['hero'] for k,v in regions.items()
                    } if regions else None)
                ai_product=hero is None
        paths={};jpeg_paths={};corel_paths={}
        for key in ('4x3','9x16'):
            visual=visuals.get(key)
            photo=visual if ai_product else hero
            # An explicitly requested OpenAI image takes priority; otherwise
            # the customer's own licensed industrial photo is used as the
            # separate scene layer beneath the unchanged product bitmap.
            scene=None if ai_product else (visual if visual is not None else user_backdrop)
            if generation_mode=='hybrid':
                svg=render_ai_full_poster_svg(
                    brief,key,concept,artwork=visual,hero=hero,
                    detail=detail,logo=logo,drawing=drawing)
            elif concept is None:
                svg=create_editable_svg(brief,key,hero=photo,detail=detail,logo=logo,
                                        drawing=drawing,backdrop=scene,ai_product=ai_product)
            else:
                svg=render_ai_concept_svg(brief,key,concept,hero=photo,detail=detail,
                                          logo=logo,drawing=drawing,backdrop=scene,
                                          ai_product=ai_product)
            # The SVG is the master. PNG and JPEG are rendered from the SAME
            # vector scene, so opening the SVG in CorelDRAW has matching layout.
            RENDER_LOG.info("SVG %s composed: %.1fs",key,time.monotonic()-clock)
            png,jpeg=rasterize_svg(svg)
            RENDER_LOG.info("PNG/JPEG %s rasterized: %.1fs",key,time.monotonic()-clock)
            png_name=f'poster_{key}.png'
            jpg_name=f'poster_{key}.jpg'
            svg_name=f'corel_{key}.svg'
            (folder/png_name).write_bytes(png)
            (folder/jpg_name).write_bytes(jpeg)
            (folder/svg_name).write_bytes(svg)
            paths[key]=f'/files/{job_id}/{png_name}'
            jpeg_paths[key]=f'/files/{job_id}/{jpg_name}'
            corel_paths[key]=f'/files/{job_id}/{svg_name}'
        (folder/'promo_prompt.txt').write_text(design_prompt,encoding='utf-8')
        effective_mode=('hybrid' if generation_mode == 'hybrid'
                        else 'ai_pro' if concept is not None else generation_mode)
        if concept is not None:
            (folder/'layout_spec.json').write_text(
                json.dumps({'generation_mode':effective_mode,
                            'concept_set_id':concept_set_id,
                            'selected_concept':concept},ensure_ascii=False,indent=2),
                encoding='utf-8')
        (folder/'asset_selection.json').write_text(json.dumps(asset_report or {},ensure_ascii=False,indent=2),encoding='utf-8')
        briefing=dict(brief)
        briefing['_metadata']={
            'generator':('Full OpenAI-authored poster with exact SVG data overlays'
                         if generation_mode=='hybrid' else
                         'AI-directed editable SVG' if concept else 'PromoEditor SVG template'),
            'generation_mode':effective_mode,
            'art_director':('OpenAI Responses: layout and placement; OpenAI Images: complete illustrated poster artwork; server: exact facts and source assets only'
                            if generation_mode=='hybrid' else None),
            'concept_set_id':concept_set_id,
            'image_source':'OpenAI API' if use_openai else 'Исходное фото / демо',
            'ai_product_visualization':ai_product,
            'verified_specs':False,
            'design_actions_sent_to_ai':bool(use_openai and brief.get('design_actions')),
            'editable_source':'CorelDRAW-compatible SVG; exact factual text and images are separate editable objects; AI-created decorative artwork is one raster layer',
            'bitmap_limit':'Full AI artwork is one bitmap; original photos/logos/drawings are independent bitmaps; approved text remains editable SVG text.',
            'prompt_file':'promo_prompt.txt',
            'asset_selection_file':'asset_selection.json',
            'note':'Проверяйте технические данные, цены и права на иллюстрации перед публикацией.'
        }
        (folder/'brief.json').write_text(json.dumps(briefing,ensure_ascii=False,indent=2),encoding='utf-8')
        readme=(
            'PROMOEDITOR — ИСХОДНИКИ ДЛЯ CORELDRAW\n'
            'Откройте corel_4x3.svg или corel_9x16.svg в CorelDRAW через Файл → Импорт/Открыть.\n'
            'При необходимости разгруппируйте SVG-объекты. Текст, фигуры, фото и логотипы — отдельные объекты.\n'
            'Сохраните импортированный файл как CDR в самой программе CorelDRAW.\n'
            'Фотографии и AI-изображения — отдельные растровые объекты. '
            'Их внутренние детали НЕ становятся независимыми векторными объектами.\n'
            'Выбранные фотографии, JPG/PNG/WEBP чертёж и логотип в исходном '
            'качестве сохраняются в папке originals/ внутри ZIP. '
            'SVG содержит независимые облегчённые растровые объекты.\n'
            'Для соответствия типографике установите или замените DejaVu Sans.\n'
            'JPEG/PNG получены из тех же SVG, поэтому компоновка совпадает.\n'
            'Проверьте тексты и цифры перед публикацией.\n'
        )
        (folder/'CORELDRAW_README.txt').write_text(readme,encoding='utf-8')
        names=[
            'poster_4x3.png','poster_9x16.png',
            'poster_4x3.jpg','poster_9x16.jpg',
            'corel_4x3.svg','corel_9x16.svg',
            'promo_prompt.txt','brief.json','asset_selection.json',
            'CORELDRAW_README.txt'
        ]
        if concept is not None:
            names.append('layout_spec.json')

        with zipfile.ZipFile(folder/'promo_kit.zip','w',
                            compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for filename in names:
                archive.write(folder/filename,arcname=filename)
            # Preserve the *exact* selected uploaded photos alongside the
            # size-optimized raster layers in SVG. Analysis previews and
            # rendering copies never replace these original bytes.
            selected=(asset_report or {}).get('selected_assets') or {}
            originals={
                row.get('id'):row for row in
                ((asset_report or {}).get('project_assets') or [])
                if isinstance(row,dict)
            }
            for role,payload in (('primary_photo',hero_raw),
                                 ('secondary_photo',detail_raw),
                                 ('drawing',drawing_raw),
                                 ('logo',logo_raw),
                                 ('background',background_raw),
                                 ('reference_example',reference_example_raw)):
                asset=originals.get(selected.get(role))
                if not payload or not asset:continue
                extension=Path(str(asset.get('name') or '')).suffix.lower()
                if extension in ALLOWED_IMAGES:
                    archive.writestr(
                        f'originals/{role}{extension}',payload,
                        compress_type=zipfile.ZIP_STORED)
        # Consume paid copies only after both SVGs and the ZIP exist.
        if paid_cache is not None:
            try:
                _finish_visual_cache(paid_cache)
            except OSError:
                pass
        warnings=['Проверьте технические данные, цены и права на изображения перед публикацией.']
        if not brief.get('specs'):
            warnings.append('Подтверждённые ТТХ не заполнены: таблица характеристик не показана. Проверьте предложения из документов и перенесите нужные в форму.')
        if not brief.get('dimensions'):
            warnings.append('Габариты отсутствуют в форме: векторная схема размеров без данных не создавалась.')
        if not brief.get('price'):
            warnings.append('Цена не указана: вместо числа используется общий призыв запросить предложение.')
        visible_specs=8 if concept is not None else 7
        if len(brief.get('specs') or [])>visible_specs:
            warnings.append(
                f'В плакате показаны первые {visible_specs} подтверждённых ТТХ из '
                f'{len(brief.get("specs") or [])}; остальные сохранены в JSON-брифе.')
        if len(brief.get('dimensions') or [])>4:
            warnings.append('В макете используются первые 4 габарита; остальные сохранены в JSON-брифе.')
        if len(brief.get('benefits') or [])>5:
            warnings.append('В рекламной полосе показаны первые 5 преимуществ; остальные сохранены в JSON-брифе.')
        if brief.get('design_actions') and not use_openai:
            warnings.append('Дополнительные действия сохранены в промпте, но без OpenAI не применяются к AI-фону и произвольному изменению дизайна.')
        RENDER_LOG.info("Both formats and ZIP ready: %.1fs",time.monotonic()-clock)
        return {
            'job_id':job_id,'images':paths,'jpeg':jpeg_paths,'corel':corel_paths,
            'prompt_file':f'/files/{job_id}/promo_prompt.txt',
            'zip':f'/files/{job_id}/promo_kit.zip','brief':f'/files/{job_id}/brief.json',
            'asset_selection':f'/files/{job_id}/asset_selection.json',
            'layout_spec':f'/files/{job_id}/layout_spec.json',
            'generation_mode':effective_mode,
            'selected_assets':(asset_report or {}).get('selected_assets',{}),
            'ai_used':use_openai,'visualization':ai_product,'warnings':warnings
        }
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise


def _concept_fingerprint(brief:dict,report:dict)->str:
    """Tie AI-authored geometry to validated copy and the current source files."""
    assets=[(item.get('id'),item.get('sha256')) for item in
            report.get('project_assets',[]) if isinstance(item,dict)]
    blob=json.dumps({'brief':brief,'assets':assets,
                     'selected':report.get('selected_assets',{})},
                    ensure_ascii=False,sort_keys=True,
                    separators=(',',':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def _build_concept_previews_sync(brief, report, records, concepts,
                                style, goal, hero_raw, reference_raw):
    """Load sources and render all six previews with bounded worker concurrency."""
    with CONCEPT_RENDER_SLOTS:
        hero=load_image(hero_raw)
        detail=load_image(chosen_bytes(report,records,'secondary_photo'))
        logo=load_image(chosen_bytes(report,records,'logo'))
        drawing_raw=chosen_bytes(report,records,'drawing')
        drawing_id=report['selected_assets'].get('drawing')
        if drawing_raw and drawing_id and records[drawing_id]['name'].lower().endswith('.pdf'):
            drawing_raw=pdf_first_page_png(drawing_raw)
        drawing=load_image(drawing_raw)
        backdrop=load_image(chosen_bytes(report,records,'background'))
        _clean_jobs()
        job_id=secrets.token_hex(16)
        folder=STORAGE/job_id
        folder.mkdir(mode=0o700)
        try:
            saved={'version':1,'brief_hash':_concept_fingerprint(brief,report),
                   'style':style,'goal':goal,'reference_used':reference_raw is not None,
                   'concepts':concepts}
            (folder/'concepts.json').write_text(
                json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
            cards=[]
            for i,concept in enumerate(concepts):
                previews={}
                for fmt in ('4x3','9x16'):
                    svg=render_ai_concept_svg(
                        brief,fmt,concept,hero=hero,detail=detail,logo=logo,
                        drawing=drawing,backdrop=backdrop)
                    png,_=rasterize_svg(svg)
                    name=f'concept_{i}_{fmt}.png'
                    (folder/name).write_bytes(png)
                    previews[fmt]=f'/files/{job_id}/{name}'
                cards.append({'index':i,'name':concept['name'],
                              'rationale':concept['rationale'],
                              'previews':previews,'layout_spec':concept['layouts'],
                              'layout_repair':concept.get('layout_repair',{})})
        except Exception:
            shutil.rmtree(folder,ignore_errors=True)
            raise
        return {'concept_set_id':job_id,'concepts':cards,
                'reference_used':reference_raw is not None,
                'style':style,'goal':goal,
                'message':'AI разработал три композиции. Выберите одну для финальной сборки.'}




def _full_posters_sync(brief, product_raw, logo_raw, drawing_raw,
                       reference_raw, model, quality, selected_source=None):
    """Rebrand ONLY the selected photo before authoring both full AI posters.

    The original photo is immutable. The one paid rebranding edit is cached
    by original bytes/logo/brand/model. Partial paid outputs survive ZIP
    failures. Other uploaded photos never enter either model call.
    """
    rebrand_dir = rebrand_cache_dir(brief, product_raw, logo_raw, model, quality)
    rebranded_raw = cached_rebrand_photo(rebrand_dir)
    if rebranded_raw is None:
        # Fail BEFORE ANY paid Images call if capacity cannot fund all three.
        check_paid_capacity('image', 3)
    else:
        previous_sources=[rebranded_raw]+[raw for raw in
                            (logo_raw,drawing_raw,reference_raw) if raw]
        previous_posters=_default_visual_cache(
            brief,True,previous_sources,model,quality,
            AI_POSTER_VERSION,'complete-poster')
        missing=sum(_cached_visual(previous_posters,fmt) is None
                    for fmt in ('4x3','9x16'))
        check_paid_capacity('image',missing)
    if rebranded_raw is None:
        rebranded_raw = rebrand_selected_photo(
            brief, product_raw, logo=logo_raw, model=model, quality=quality,
            folder=rebrand_dir)
    # NEVER send secondary or unselected uploaded trailer photos to the
    # rebranding endpoint or to the complete poster artwork generator.
    poster_sources=[rebranded_raw]+[raw for raw in
                                  (logo_raw,drawing_raw,reference_raw) if raw]
    paid_cache=_default_visual_cache(
        brief,True,poster_sources,model,quality,
        AI_POSTER_VERSION,"complete-poster")
    posters = generate_full_posters(
        brief, rebranded_raw, logo=logo_raw, drawing=drawing_raw,
        reference=reference_raw, model=model, quality=quality,
        cache_dir=paid_cache, consume_cache=False,
        product_is_rebranded=True)
    _clean_jobs()
    job_id=secrets.token_hex(16)
    folder=STORAGE/job_id
    folder.mkdir(mode=0o700)
    try:
        (folder/'rebranded_product.png').write_bytes(rebranded_raw)
        images={};jpegs={}
        for fmt in ('4x3','9x16'):
            png=f'ai_poster_{fmt}.png'
            jpg=f'ai_poster_{fmt}.jpg'
            posters[fmt].save(folder/png,format='PNG')
            posters[fmt].save(folder/jpg,format='JPEG',
                              quality=93,subsampling=0)
            images[fmt]=f'/files/{job_id}/{png}'
            jpegs[fmt]=f'/files/{job_id}/{jpg}'
        archive=folder/'ai_posters.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for fmt in ('4x3','9x16'):
                z.write(folder/f'ai_poster_{fmt}.png',
                        arcname=f'ai_poster_{fmt}.png')
                z.write(folder/f'ai_poster_{fmt}.jpg',
                        arcname=f'ai_poster_{fmt}.jpg')
            z.write(folder/'rebranded_product.png',
                    arcname='rebranded_product.png')
            z.writestr('brief.json',
                       json.dumps(brief,ensure_ascii=False,indent=2))
            z.writestr('selected_photo.json',json.dumps({
                'selected_primary':selected_source or {},
                'rebranded_only_this_photo':True,
                'other_uploaded_photos_untouched':True,
            },ensure_ascii=False,indent=2))
            z.writestr('REVIEW_BEFORE_PUBLICATION.txt',
                       AI_POSTER_WARNING+'\n'+REBRAND_WARNING+'\n'
                       'Изменённый кадр: rebranded_product.png. '
                       'Оригинал: originals/product_photo.*. '
                       'Только выбранный главный ракурс редактировался; '
                       'проверяйте логотип и надписи. В этом режиме SVG нет.\n')
            for name,raw in (('product_photo',product_raw),
                             ('customer_logo',logo_raw),
                             ('drawing_preview',drawing_raw),
                             ('style_reference',reference_raw)):
                if not raw:
                    continue
                with Image.open(io.BytesIO(raw)) as original:
                    suffix={ 'JPEG':'.jpg','PNG':'.png','WEBP':'.webp' }.get(
                        original.format,'.bin')
                z.writestr(f'originals/{name}{suffix}',
                           raw,compress_type=zipfile.ZIP_STORED)
        try:
            _finish_visual_cache(paid_cache)
        except OSError:
            pass
        return {'job_id':job_id,'images':images,'jpeg':jpegs,
                 'zip':f'/files/{job_id}/ai_posters.zip',
                'generation_mode':'openai_full_poster',
                'ai_used':True,'raster_only':True,
                'reference_used':reference_raw is not None,
                'selected_photo':selected_source or {},
                'rebranded_photo':f'/files/{job_id}/rebranded_product.png',
                'rebranding_applied':True,
                'warnings':[AI_POSTER_WARNING,REBRAND_WARNING]}
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise


def _exact_typography_posters_sync(brief, product_raw, logo_raw,
                                   drawing_raw, reference_raw, model, quality,
                                   selected_source=None, progress=None):
    """New PRIMARY mode: full AI design -> exact SVG copy -> AI typography.

    Rebrand only the selected original trailer. The AI text finisher selects
    font/color/scale from a visual preview; it never gets to rewrite the facts.
    Old pure raster /api/ai-posters remains available for compatibility.
    """
    # Before the FIRST paid edit, preflight all three Images requests and
    # both Responses stages. On a partial-failure retry, the already paid
    # rebrand image is reused and the template module checks ONLY its truly
    # missing art/layout/typography calls, so a completed cache costs zero.
    if progress: progress('Проверяем лимиты OpenAI и кэш ранее выполненных этапов')
    rebrand_dir=rebrand_cache_dir(brief,product_raw,logo_raw,model,quality)
    chosen=cached_rebrand_photo(rebrand_dir)
    if chosen is None:
        check_paid_capacity('text',2)
        check_paid_capacity('image',3)
        if progress: progress('Наносим ваш логотип и модель только на выбранный прицеп')
        chosen=rebrand_selected_photo(
            brief,product_raw,logo=logo_raw,model=model,quality=quality,
            folder=rebrand_dir)
    # Create the private output directory BEFORE the costly render.
    # All completed AI art remains in the paid cache even if export fails.
    # Production never holds both SVG + PNG + JPEG posters as large bytes
    # in the 800 MiB Uvicorn process.
    _clean_jobs()
    job_id=secrets.token_hex(16)
    folder=STORAGE/job_id
    folder.mkdir(mode=0o700)
    try:
        technical_sheet = None
        if drawing_raw or brief.get('specs') or brief.get('dimensions'):
            # Preserve approved technical data and uploaded drawing before
            # any additional paid art generation.
            if progress:
                progress('Сохраняем исходный чертёж и все проверенные ТТХ')
            svg_path=folder/'technical_sheet.svg'
            svg_path.write_bytes(render_technical_sheet(brief,drawing_raw))
            _rasterize_in_worker(
                svg_path,folder/'technical_sheet.png',
                folder/'technical_sheet.jpg',
            )
            technical_sheet={
                'svg':f'/files/{job_id}/technical_sheet.svg',
                'png':f'/files/{job_id}/technical_sheet.png',
                'jpeg':f'/files/{job_id}/technical_sheet.jpg',
                'drawing_used':bool(drawing_raw),
            }
        if progress: progress('Подготавливаем два AI-макета и точные текстовые зоны')
        render_options={'logo':logo_raw,'drawing':drawing_raw,
                        'reference':reference_raw,'model':model,'quality':quality,
                        'output_dir':folder}
        if progress is not None:
            render_options['progress']=progress
        rendered=generate_exact_typography_posters(
            brief,chosen,**render_options)
        if progress: progress('Собираем подготовленные SVG, PNG и JPEG в ZIP')
        (folder/'rebranded_product.png').write_bytes(chosen)
        images={};jpegs={};corel={}
        for fmt in ('4x3','9x16'):
            if rendered.get('file_backed'):
                for key,name in (
                    ('png',f'ai_poster_{fmt}.png'),
                    ('jpeg',f'ai_poster_{fmt}.jpg'),
                    ('svg',f'corel_{fmt}.svg'),
                    ('artwork_paths',f'ai_template_{fmt}.png'),
                ):
                    source=Path(rendered[key][fmt])
                    target=folder/name
                    if not source.is_file():
                        raise RuntimeError('Отсутствует результат рендеринга '+name)
                    if source!=target:
                        shutil.copyfile(source,target)
            else:
                # Compatibility with already tested callers and synthetic CI
                # fakes. Real production always uses disk-backed exports.
                for name,payload in (
                    (f'ai_poster_{fmt}.png',rendered['png'][fmt]),
                    (f'ai_poster_{fmt}.jpg',rendered['jpeg'][fmt]),
                    (f'corel_{fmt}.svg',rendered['svg'][fmt]),
                ):
                    (folder/name).write_bytes(payload)
                rendered['artwork'][fmt].save(
                    folder/f'ai_template_{fmt}.png',format='PNG')
            images[fmt]=f'/files/{job_id}/ai_poster_{fmt}.png'
            jpegs[fmt]=f'/files/{job_id}/ai_poster_{fmt}.jpg'
            corel[fmt]=f'/files/{job_id}/corel_{fmt}.svg'
        metadata={
            'selected_primary':selected_source or {},
            'rebranded_only_this_photo':True,
            'other_uploaded_photos_untouched':True,
        }
        for name,obj in (
            ('typography_layout.json',rendered['layout']),
            ('typography_style.json',rendered['typography']),
            ('verified_copy.json',rendered['verified_copy']),
            ('poster_copy.json',rendered.get('poster_copy')
                                 or rendered['verified_copy']),
            ('selected_photo.json',metadata),
        ):
            (folder/name).write_text(
                json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
        with zipfile.ZipFile(
            folder/'ai_typographic_posters.zip','w',
            compression=zipfile.ZIP_DEFLATED,compresslevel=6,
        ) as archive:
            for fmt in ('4x3','9x16'):
                for name in (
                    f'ai_poster_{fmt}.png',f'ai_poster_{fmt}.jpg',
                    f'corel_{fmt}.svg',f'ai_template_{fmt}.png',
                ):
                    archive.write(folder/name,arcname=name)
            archive.write(folder/'rebranded_product.png',
                          arcname='rebranded_product.png')
            for name in ('typography_layout.json','typography_style.json',
                         'verified_copy.json','poster_copy.json','selected_photo.json'):
                archive.write(folder/name,arcname=name)
            if technical_sheet:
                for name in ('technical_sheet.svg','technical_sheet.png',
                             'technical_sheet.jpg'):
                    archive.write(folder/name,arcname=name)
            archive.writestr('brief.json',
                json.dumps(brief,ensure_ascii=False,indent=2))
            archive.writestr('REVIEW_BEFORE_PUBLICATION.txt',
                EXACT_COPY_WARNING+'\n'+REBRAND_WARNING+'\n'
                'SVG содержит редактируемые текстовые слои. '
                'AI не исправляет содержание текстов; он выбирает '
                'лишь гарнитуру и цвет. Перепроверьте визуально макеты.\n')
            for name,raw in (
                ('product_photo',product_raw),('customer_logo',logo_raw),
                ('drawing_preview',drawing_raw),
                ('style_reference',reference_raw),
            ):
                if not raw:
                    continue
                with Image.open(io.BytesIO(raw)) as im:
                    suffix={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}.get(
                        im.format,'.bin')
                archive.writestr(f'originals/{name}{suffix}',raw,
                                 compress_type=zipfile.ZIP_STORED)
        consume_paid_template_cache(rendered['cache_dir'])
        return {
            'job_id':job_id,'images':images,'jpeg':jpegs,'corel':corel,
            'zip':f'/files/{job_id}/ai_typographic_posters.zip',
            'generation_mode':'ai_template_exact_copy',
            'ai_used':True,'raster_only':False,
            'reference_used':reference_raw is not None,
            'selected_photo':selected_source or {},
            'rebranded_photo':f'/files/{job_id}/rebranded_product.png',
            'rebranding_applied':True,
            'verified_typography':True,
            'technical_sheet':technical_sheet,
            'drawing_used':bool(drawing_raw),
            'warnings':[EXACT_COPY_WARNING,REBRAND_WARNING],
        }
    except Exception as exc:
        # Preserve already paid images when a late SVG or ZIP stage fails.
        # Recovery assets are private and not valid completed adverts.
        try:
            (folder/'rebranded_product.png').write_bytes(chosen)
            allowed = (
                'rebranded_product.png',
                'technical_sheet.svg','technical_sheet.png',
                'technical_sheet.jpg',
                'ai_template_4x3.png', 'ai_template_9x16.png',
                'corel_4x3.svg', 'corel_9x16.svg',
                'ai_poster_4x3.png', 'ai_poster_9x16.png',
                'ai_poster_4x3.jpg', 'ai_poster_9x16.jpg',
                'typography_layout.json', 'typography_style.json',
                'verified_copy.json', 'poster_copy.json',
                'openai_connection_diagnostic.json',
            )
            available = [folder/name for name in allowed
                         if (folder/name).is_file()]
            if available:
                archive_path = folder/'ai_failed_generation.zip'
                with zipfile.ZipFile(
                    archive_path,'w',compression=zipfile.ZIP_STORED,
                ) as archive:
                    for source in available:
                        archive.write(source,arcname=source.name)
                    archive.writestr(
                        'READ_ME_FIRST.txt',
                        'Генерация НЕ завершена. Промежуточные материалы '
                        'не предназначены для публикации.\n'
                        'Сохранены только успешно выполненные этапы.\n'
                        'Тип ошибки: '+type(exc).__name__+'.\n'
                        + ('Безопасная диагностика: '+exc.public_reason+'\n'
                           if isinstance(exc,OpenAIImageConnectionFailure)
                           else '') +
                        'Оплаченные изображения по возможности также '
                        'хранятся в закрытом кэше сервера.\n'
                        'Если запрос был принят OpenAI, списание за него '
                        'может произойти даже без полученного ответа.\n',
                    )
                raise PartialPosterFailure(
                    f'/files/{job_id}/ai_failed_generation.zip',exc
                ) from exc
        except PartialPosterFailure:
            raise
        except (OSError, ValueError, RuntimeError):
            # A full disk can prevent even the recovery ZIP from being saved.
            # Retain the independent paid cache and report the original error.
            pass
        shutil.rmtree(folder,ignore_errors=True)
        raise


@app.post('/api/ai-posters')
async def create_full_ai_posters(request:Request):
    """One selected-photo rebrand edit plus two AI-poster edits.

    User-authored facts and photos are treated as sources, not AI claims.
    The resulting raster must be proofread prior to public distribution.
    """
    _guard_rate(request)
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(400,detail='Для AI-постеров настройте OPENAI_API_KEY.')
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Превышен общий лимит 68 МБ.')
    form=await request.form()
    raw=form.get('payload','{}')
    if not isinstance(raw,str) or len(raw)>48000:
        raise HTTPException(400,detail='Некорректный бриф.')
    try:
        brief=_normalize(json.loads(raw))
    except (ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(400,detail='Некорректные данные брифа.') from exc
    if not brief.get('model'):
        raise HTTPException(400,detail='Укажите модель товара.')
    from .openai_service import IMAGE_MODELS, IMAGE_QUALITIES
    model=str(form.get('model','gpt-image-2.5-flare'))
    quality=str(form.get('quality','medium'))
    if model not in IMAGE_MODELS or quality not in IMAGE_QUALITIES:
        raise HTTPException(400,detail='Недопустимые настройки модели OpenAI.')
    groups=await _asset_groups(form)
    prefs,cached=_asset_review(form)
    try:
        report,records=await asyncio.to_thread(
            analyze_project,groups,prefs,cached_report=cached,use_ai=False,
            rank_photos_with_ai=True,
            requirements=brief.get('design_notes',''))
        product=chosen_bytes(report,records,'primary_photo')
        if not product:
            raise HTTPException(400,detail='Загрузите и выберите главное фото техники.')
        drawing=chosen_bytes(report,records,'drawing')
        drawing_id=report['selected_assets'].get('drawing')
        if drawing and drawing_id and records[drawing_id]['name'].lower().endswith('.pdf'):
            drawing=await asyncio.to_thread(pdf_first_page_png,drawing)
        photo_id=report['selected_assets']['primary_photo']
        source={'id':photo_id,'name':records[photo_id]['name'],
                'sha256':records[photo_id]['sha256']}
        return await asyncio.to_thread(
            _full_posters_sync,brief,product,
            chosen_bytes(report,records,'logo'),drawing,
            chosen_bytes(report,records,'reference_example'),model,quality,
            selected_source=source)
    except QuotaExceeded as exc:
        raise HTTPException(429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(503,detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            502,detail=f'Не удалось создать AI-постеры ({type(exc).__name__}).') from exc


@app.post('/api/concepts')
async def create_ai_concepts(request:Request):
    """AI plans three editable concepts; reference-example upload is OPTIONAL.

    Each preview uses the existing original images, exact facts and generic
    neutral/user-supplied backgrounds. Final photorealistic scene generation
    is a separate, explicitly selected paid step.
    """
    _guard_rate(request)
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(400,detail='Для AI PRO настройте OPENAI_API_KEY. Шаблонный режим доступен без ключа.')
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Превышен общий лимит 68 МБ.')
    form=await request.form()
    raw=form.get('payload','{}')
    if not isinstance(raw,str) or len(raw)>48000:
        raise HTTPException(400,detail='Слишком большой бриф.')
    try:
        brief=_normalize(json.loads(raw))
    except (json.JSONDecodeError,ValueError) as exc:
        raise HTTPException(400,detail='Некорректный бриф.') from exc
    if not brief.get('model'):
        raise HTTPException(400,detail='Укажите модель товара.')
    style=str(form.get('design_style','premium'))
    goal=str(form.get('design_goal','sales'))
    if style not in STYLES or goal not in GOALS:
        raise HTTPException(400,detail='Недопустимый стиль или цель рекламы.')
    groups=await _asset_groups(form)
    prefs,cached=_asset_review(form)
    try:
        report,records=await asyncio.to_thread(
            analyze_project,groups,prefs,cached_report=cached,use_ai=False)
        hero_raw=chosen_bytes(report,records,'primary_photo')
        reference_raw=chosen_bytes(report,records,'reference_example')
        concepts=await asyncio.to_thread(
            generate_concepts,brief,hero=hero_raw,reference=reference_raw,
            style=style,goal=goal)
        return await asyncio.to_thread(
            _build_concept_previews_sync, brief, report, records, concepts,
            style, goal, hero_raw, reference_raw)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,detail=f'Не удалось создать AI-концепции. Проверьте OpenAI API ({type(exc).__name__}).'
        ) from exc


@app.post('/api/prompt')
async def preview_promo_prompt(request:Request):
    """Free, deterministic and inspectable intermediate step: form -> prompt."""
    if int(request.headers.get('content-length') or 0)>48000:
        raise HTTPException(413,detail='Слишком большой бриф.')
    try:
        raw=await request.body()
        if len(raw)>48000:raise HTTPException(413,detail='Слишком большой бриф.')
        original=json.loads(raw)
        brief=_normalize(original)
        report=original.get('asset_report') if isinstance(original,dict) else None
    except json.JSONDecodeError:
        raise HTTPException(400,detail='Некорректный JSON.')
    try:prompt=build_promo_prompt(brief,report)
    except ValueError as exc:raise HTTPException(400,detail=str(exc))
    return {'prompt':prompt,'formats':['4x3','9x16'],'ai_required':False,
            'notice':'Промпт сформирован из формы без платного вызова. При включённом OpenAI он передаётся для генерации сцены, а тексты и векторные элементы компонуются программно.'}


def _run_generation_task(task_id: str):
    """Detached single paid workflow; no public HTTP connection held open."""
    folder=ai_job_queue.task_folder(STORAGE,task_id)
    opened=[]
    last_stage='Проверяем исходные данные проекта'
    def stage(message):
        nonlocal last_stage
        last_stage=message
        ai_job_queue.set_status(folder,'running',stage=message)
        # Record the native process memory high-watermark at each stage,
        # without leaking file names, customer data or OpenAI responses.
        try:
            import resource
            peak_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
            RENDER_LOG.info(
                'PromoEditor AI task %s: %s (RSS peak %.1f MiB)',
                task_id,message,peak_mib)
        except (OSError,ImportError):
            RENDER_LOG.info('PromoEditor AI task %s: %s',task_id,message)
    try:
        form,opened=ai_job_queue.reopen_form(folder)
        stage('Проверяем исходные данные проекта')
        result=asyncio.run(_generate_from_form(form,progress=stage))
        # A completed task must have NO uploaded private sources left.
        # Clean them BEFORE reporting completion; the browser can download
        # its generated ZIP without the original form inputs remaining here.
        for handle in opened:
            handle.close()
        opened.clear()
        ai_job_queue.erase_uploads(folder)
        ai_job_queue.set_status(
            folder,'complete',stage='Оба макета и редактируемые SVG готовы',
            result=result)
    except Exception as exc:
        if isinstance(exc,HTTPException):
            code=int(exc.status_code)
            detail=str(exc.detail)
        elif isinstance(exc,PartialPosterFailure):
            code=502
            detail=(
                'Сборка постеров прервалась ('+exc.cause_type+'). '
                + (exc.public_reason+' ' if exc.public_reason else '')
                + 'Созданные материалы сохранены в диагностическом ZIP. '
                'Оплаченные этапы не запускаются повторно автоматически.'
            )
        elif isinstance(exc,QuotaExceeded):
            code,detail=429,str(exc)
        elif isinstance(exc,QuotaStoreUnavailable):
            code,detail=503,str(exc)
        elif isinstance(exc,ValueError):
            code,detail=400,str(exc)
        else:
            code=502
            # Do NOT expose original SDK error text (may contain
            # private customer brief, source paths or response headers).
            detail=(
                'AI-генерация завершилась ошибкой на сервере '
                f'({type(exc).__name__}). Дальнейших платных '
                'повторных запросов не отправлялось. '
                'Проверьте журнал promoeditor.'
            )
            # SDK exception strings may contain customer details. Keep
            # durable logs limited to the known stage and exception TYPE.
            RENDER_LOG.error(
                'PromoEditor AI task %s failed at %s (%s)',
                task_id,last_stage,type(exc).__name__)
        try:
            ai_job_queue.set_status(
                folder,'failed',error='Этап: '+last_stage+'. '+detail,
                http_status=code,
                recovery_zip=(exc.recovery_zip if isinstance(
                    exc,PartialPosterFailure) else None))
        except OSError:
            RENDER_LOG.exception(
                'PromoEditor AI task %s failed writing status',task_id)
    finally:
        for handle in opened:
            try: handle.close()
            except OSError: pass
        ai_job_queue.erase_uploads(folder)
        MAIN_AI_GENERATION_SLOT.release()


@app.post('/api/generate/start',status_code=202)
async def start_ai_generation(request:Request):
    """Immediate 202, followed by authenticated progress polling.

    The five paid API operations may outlive a normal reverse-proxy timeout.
    One active task per 800 MiB worker, no concurrent paid duplicate.
    """
    _guard_rate(request)
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Превышен лимит загрузки 68 МБ.')
    if not MAIN_AI_GENERATION_SLOT.acquire(blocking=False):
        raise HTTPException(409,detail=(
            'Уже выполняется AI-генерация. Не запускайте её повторно: '
            'дополнительные платные вызовы не отправлены.'))
    folder=None
    try:
        form=await request.form()
        if str(form.get('generation_mode',''))!='hybrid':
            raise HTTPException(
                400,detail='Фоновый запуск предусмотрен только для основного AI-режима.')
        if not os.getenv('OPENAI_API_KEY'):
            raise HTTPException(
                400,detail='На сервере не настроен OPENAI_API_KEY.')
        ai_job_queue.cleanup(STORAGE)
        task_id,folder=ai_job_queue.new_task(STORAGE)
        await ai_job_queue.snapshot_form(form,folder)
        ai_job_queue.set_status(
            folder,'running',stage='Задача принята; подготавливаем материалы')
        thread=threading.Thread(
            target=_run_generation_task,args=(task_id,),
            name='promoeditor-ai-generation',daemon=True)
        thread.start()
        return {'task_id':task_id,'status':'running',
                'status_url':f'/api/generate/status/{task_id}'}
    except (QuotaExceeded,QuotaStoreUnavailable):
        if folder: shutil.rmtree(folder,ignore_errors=True)
        MAIN_AI_GENERATION_SLOT.release()
        raise
    except HTTPException:
        if folder: shutil.rmtree(folder,ignore_errors=True)
        MAIN_AI_GENERATION_SLOT.release()
        raise
    except ValueError as exc:
        if folder: shutil.rmtree(folder,ignore_errors=True)
        MAIN_AI_GENERATION_SLOT.release()
        raise HTTPException(400,detail=str(exc)) from exc
    except Exception as exc:
        if folder: shutil.rmtree(folder,ignore_errors=True)
        MAIN_AI_GENERATION_SLOT.release()
        RENDER_LOG.exception('Unable to queue PromoEditor AI generation')
        raise HTTPException(503,detail=(
            'Не удалось сохранить файлы задачи генерации '
            f'({type(exc).__name__}). Проверьте место на диске.')) from exc


@app.get('/api/generate/status/{task_id}')
def status_ai_generation(task_id: str):
    if not JOB_ID.fullmatch(task_id):
        raise HTTPException(400,detail='Некорректный номер генерации.')
    state=ai_job_queue.read_status(STORAGE,task_id)
    if state is None:
        raise HTTPException(404,detail=(
            'Задача не найдена либо срок хранения результата истёк.'))
    return state


@app.post('/api/generate')
async def generate(request:Request):
    """Compatibility endpoint, including immediate/free SVG generation."""
    _guard_rate(request)
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Превышен общий лимит загрузки 68 МБ')
    form=await request.form()
    if str(form.get('generation_mode','template'))=='hybrid':
        if not MAIN_AI_GENERATION_SLOT.acquire(blocking=False):
            raise HTTPException(409,detail=(
                'На VPS уже выполняется одна AI-генерация. Дождитесь её '
                'результата; повторный платный запрос не отправлен.'))
        try:
            return await _generate_from_form(form)
        finally:
            MAIN_AI_GENERATION_SLOT.release()
    return await _generate_from_form(form)


async def _generate_from_form(form, progress=None):
    """Same validated pipeline for direct and disconnect-safe queued requests."""
    raw=form.get('payload','{}')
    if not isinstance(raw,str) or len(raw)>48000:raise HTTPException(400,detail='Некорректные данные формы')
    try:brief=_normalize(json.loads(raw))
    except json.JSONDecodeError:raise HTTPException(400,detail='Некорректный JSON')
    groups=await _asset_groups(form)
    prefs,cached=_asset_review(form)
    use_openai=str(form.get('use_openai','false')).lower()=='true'
    use_demo=str(form.get('use_demo','false')).lower()=='true'
    mode=str(form.get('generation_mode','template'))
    if mode not in ('ai_pro','template','hybrid'):
        raise HTTPException(400,detail='Неподдерживаемый режим создания.')
    if mode=='hybrid':
        from .openai_service import IMAGE_MODELS, IMAGE_QUALITIES
        if (str(form.get('model','gpt-image-2.5-flare')) not in IMAGE_MODELS
                or str(form.get('quality','medium')) not in IMAGE_QUALITIES):
            raise HTTPException(400,detail='Недопустимые настройки OpenAI Images.')
    if use_openai and not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(400,detail='Для AI-генерации укажите OPENAI_API_KEY на сервере.')
    supplied_prompt=form.get('prompt','')
    if not isinstance(supplied_prompt,str) or len(supplied_prompt)>8000:
        raise HTTPException(400,detail='Промпт не должен превышать 8000 символов.')
    try:
        if progress: progress('Проверяем загруженные фотографии и выбираем главный ракурс')
        report,records=await asyncio.to_thread(
            analyze_project,groups,prefs,cached_report=cached,use_ai=False,
            rank_photos_with_ai=(mode=='hybrid'),
            requirements=brief.get('design_notes',''))
        # Approved user edits to the prompt are kept. Asset choices are still
        # appended as non-instructional, real file-derived context.
        assets_prompt=build_promo_prompt(brief,report)
        design_prompt=supplied_prompt.strip() if supplied_prompt.strip() else assets_prompt
        if supplied_prompt.strip() and records:
            from .editable_export import asset_prompt_section
            suffix=asset_prompt_section(report)
            # /api/prompt already includes selected file details. A user
            # returning the preview text must not duplicate the same block.
            if suffix and suffix not in design_prompt:
                design_prompt=(design_prompt+'\n'+suffix)[:8000]
        if len(design_prompt)<5:raise ValueError('Добавьте описание для генерации.')
    except QuotaExceeded as exc:
        raise HTTPException(429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(503,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc))
    hero_raw=chosen_bytes(report,records,'primary_photo')
    detail_raw=chosen_bytes(report,records,'secondary_photo')
    logo_raw=chosen_bytes(report,records,'logo')
    drawing_raw=chosen_bytes(report,records,'drawing')
    background_raw=chosen_bytes(report,records,'background')
    references=chosen_bytes(report,records,'references')
    reference_example_raw=chosen_bytes(report,records,'reference_example')
    if mode=='hybrid':
        # Compatibility value for the primary checkbox. The main button must
        # use the SAME full Images poster engine as /api/ai-posters, never the
        # geometry-overlay hybrid renderer or its fallback rectangle layout.
        if not hero_raw:
            raise HTTPException(400,detail='Для полной AI-генерации выберите оригинальное фото товара.')
        if not use_openai:
            raise HTTPException(400,detail='Полная AI-генерация требует OpenAI. Для бесплатной сборки выберите шаблон.')
        if not os.getenv('OPENAI_API_KEY'):
            raise HTTPException(400,detail='Для полной AI-генерации необходим OPENAI_API_KEY.')
    concept=None
    concept_set_id=None
    if mode=='ai_pro':
        concept_set_id=str(form.get('concept_set_id',''))
        if not JOB_ID.fullmatch(concept_set_id):
            raise HTTPException(400,detail='Сначала создайте и выберите AI-концепцию.')
        path=STORAGE/concept_set_id/'concepts.json'
        if not path.is_file() or time.time()-path.stat().st_mtime>TTL_SECONDS:
            raise HTTPException(410,detail='Срок хранения AI-концепций истёк. Создайте новые.')
        try:
            stored=json.loads(path.read_text(encoding='utf-8'))
            index=int(str(form.get('concept_index','-1')))
            if index not in (0,1,2):
                raise ValueError('Выберите одну из трёх AI-концепций.')
            if stored.get('brief_hash')!=_concept_fingerprint(brief,report):
                raise HTTPException(409,detail='Материалы или данные изменились. Пересоздайте AI-концепции.')
            concept=stored['concepts'][index]
            from .ai_layout import validate_concept
            validate_concept({k:v for k,v in concept.items()
                              if k not in ('id','layout_repair')})
        except HTTPException:
            raise
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            raise HTTPException(400,detail='AI-концепция повреждена или не выбрана.') from exc
    drawing_id=report['selected_assets']['drawing']
    if drawing_raw and drawing_id and records[drawing_id]['name'].lower().endswith('.pdf'):
        try:drawing_raw=await asyncio.to_thread(pdf_first_page_png,drawing_raw)
        except ValueError as exc:raise HTTPException(400,detail=str(exc))
    try:
        if mode=='hybrid':
            # Main mode is genuine AI-designed textless artwork, not a
            # procedural template or old full-raster lettering attempt.
            # Verified facts are drawn as editable SVG AFTER the art and
            # stylistic finish only chooses typography parameters.
            selected_id=report['selected_assets']['primary_photo']
            selected_source={
                'id':selected_id,
                'name':records[selected_id]['name'],
                'sha256':records[selected_id]['sha256'],
            }
            # Keep ONLY the AI-selected trailer + optional logo/drawing/style
            # photo in RAM during the long, paid multi-stage pipeline. Other
            # uploaded photos may consume up to 68 MiB unnecessarily.
            del groups,records,report,detail_raw,background_raw,references
            import gc
            gc.collect()
            result=await asyncio.to_thread(
                _exact_typography_posters_sync,brief,hero_raw,logo_raw,drawing_raw,
                reference_example_raw,
                str(form.get('model','gpt-image-2.5-flare')),
                str(form.get('quality','medium')),
                selected_source=selected_source,
                **({'progress':progress} if progress else {}))
        else:
            image_references=([reference_example_raw] if reference_example_raw else [])+references
            result=await asyncio.to_thread(
                _generate_sync,brief,hero_raw,detail_raw,logo_raw,drawing_raw,
                image_references,use_demo,use_openai,str(form.get('model','gpt-image-2.5-flare')),
                str(form.get('quality','medium')),design_prompt,report,background_raw,
                concept,concept_set_id,reference_example_raw,mode)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except PartialPosterFailure:
        # The async runner publishes the private recovery URL in task status.
        raise
    except ValueError as exc:
        raise HTTPException(400,detail=str(exc))
    except Exception as exc:
        # Strip secrets, upstream credentials, and prompt text from server error output.
        raise HTTPException(502,detail=f'Не удалось создать изображения. Проверьте файлы и доступность OpenAI API. ({type(exc).__name__})')
    return result


@app.post('/api/edit')
async def edit_existing_promo(request: Request):
    """One paid edit of an uploaded promo. Existing generated jobs remain unchanged."""
    _guard_rate(request)
    if int(request.headers.get('content-length') or 0) > MAX_ALL:
        raise HTTPException(413, detail='Слишком большой запрос для редактирования.')
    form = await request.form()
    instruction = form.get('instruction', '')
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2500:
        raise HTTPException(400, detail='Опишите изменение (от 1 до 2500 символов).')
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(400, detail='Для AI-редактирования требуется OPENAI_API_KEY на сервере. Ручные правки работают без ключа.')
    source = await _files(form, 'image', ALLOWED_IMAGES)
    if not source:
        raise HTTPException(400, detail='Загрузите PNG, JPG или WEBP для изменения.')
    masks = await _files(form, 'mask', {'.png'})
    mask = masks[0][1] if masks else None
    if mask is not None and len(mask) >= 4 * 1024 * 1024:
        raise HTTPException(413, detail='Маска должна быть PNG менее 4 МБ.')
    try:
        edited = await asyncio.to_thread(
            edit_promotional_image, source[0][1], instruction.strip(),
            mask_raw=mask, model=str(form.get('model', 'gpt-image-2.5-flare')),
            quality=str(form.get('quality', 'medium'))
        )
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429,detail=str(exc)) from exc
    except QuotaStoreUnavailable as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(502, detail=f'AI-редактирование не удалось ({type(exc).__name__}). Проверьте доступность OpenAI.')
    _clean_jobs()
    job_id = secrets.token_hex(16)
    folder = STORAGE / job_id
    folder.mkdir(mode=0o700)
    try:
        (folder / 'edit.png').write_bytes(image_bytes(edited))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {'image': f'/files/{job_id}/edit.png', 'width': edited.width,
            'height': edited.height, 'ai_used': True,
            'warning': 'Проверьте текст, цифры, логотип и детали техники после AI-правки.'}


def _inspect_documents_sync(docs):
    """Parse documents outside the async HTTP handler."""
    warnings=[];contents=[];parsed=[]
    for name,raw in docs:
        try:
            text,issues=extract_text(name,raw)
        except ValueError as exc:
            raise HTTPException(400,detail=f'{name}: {exc}') from exc
        contents.append(f'\n----- FILE {name} -----\n'+text)
        warnings.extend([f'{name}: {msg}' for msg in issues])
        parsed.append({'file':name,'characters':len(text)})
    return warnings,parsed,'\n'.join(contents)[:35000]


@app.post('/api/inspect')
async def inspect(request:Request):
    if int(request.headers.get('content-length') or 0)>MAX_ALL:raise HTTPException(413,detail='Файлы слишком большие')
    form=await request.form()
    docs=await _files(form,'documents',ALLOWED_DOCS,collection=True)
    if not docs:raise HTTPException(400,detail='Загрузите PDF, DOCX, XLSX, CSV или TXT')
    if len(docs)>MAX_FILES:raise HTTPException(400,detail='Слишком много документов')
    warnings,parsed,joined=await asyncio.to_thread(_inspect_documents_sync,docs)
    ai=str(form.get('use_ai','false')).lower()=='true'
    result={'files':parsed,'raw_text':joined[:18000],
            'suggested_specs':heuristics(joined),'warnings':warnings,'ai_used':False,'ai_suggestions':None,
            'message':'Данные из файлов — только подсказки. Проверьте их перед переносом в макет.'}
    if ai:
        _guard_rate(request)
        if not os.getenv('OPENAI_API_KEY'):
            raise HTTPException(400,detail='Для AI-анализа установите OPENAI_API_KEY. Локальное извлечение доступно без ключа.')
        try:
            result['ai_suggestions']=await asyncio.to_thread(analyze_documents,joined,str(form.get('requirements','')))
            result['ai_used']=True
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429,detail=str(exc)) from exc
        except QuotaStoreUnavailable as exc:
            raise HTTPException(status_code=503,detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502,detail=f'Не удалось разобрать документы через OpenAI ({type(exc).__name__}).')
    return result


@app.get('/files/{job_id}/{filename}')
def get_file(job_id:str,filename:str):
    if not JOB_ID.fullmatch(job_id) or filename not in FILES:raise HTTPException(404)
    path=STORAGE/job_id/filename
    if not path.is_file():raise HTTPException(404)
    if time.time()-(STORAGE/job_id).stat().st_mtime>TTL_SECONDS:
        shutil.rmtree(STORAGE/job_id,ignore_errors=True)
        raise HTTPException(410,detail='Срок хранения результата истёк; создайте файл снова.')
    return FileResponse(path,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'},
                        filename=filename if filename.endswith(('.zip','.svg','.txt')) else None)
