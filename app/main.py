"""Promo Studio web application: local-first, server-side OpenAI integration."""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from PIL import Image, ImageDraw

from .documents import ALLOWED_DOCS, extract_text, heuristics, pdf_first_page_png
from .openai_service import analyze_documents, generate_visuals
from .editor_service import edit_promotional_image
from .render import default_brief, image_bytes, load_image, render_poster, valid_hex
from .auth import enabled as auth_enabled, guard as password_guard, login_get, login_post, logout_post

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
MAX_FILES=16
TTL_SECONDS=int(os.getenv('PROMO_JOB_TTL_SECONDS','7200'))
LIMIT=int(os.getenv('PROMO_REQUESTS_PER_HOUR','20'))
RATE=defaultdict(list)
LOCK=threading.Lock()
ALLOWED_IMAGES={'.png','.jpg','.jpeg','.webp'}
FILES={'poster_4x3.png','poster_9x16.png','promo_kit.zip','brief.json','edit.png'}
JOB_ID=re.compile(r'^[a-f0-9]{32}$')

app=FastAPI(title='Promo Studio',description='Генератор рекламной инфографики 4:3 и 9:16 на основе OpenAI API',version='1.0.0')
app.mount('/static',StaticFiles(directory=str(STATIC)),name='static')

@app.middleware('http')
async def password_auth_middleware(request:Request,call_next):
    return await password_guard(request,call_next)

@app.get('/login')
async def password_login_page(request:Request):
    return await login_get(request)

@app.post('/login')
async def password_login_submit(request:Request):
    return await login_post(request)

@app.post('/logout')
async def password_logout(request:Request):
    return await logout_post(request)



@app.get('/')
def home():
    return FileResponse(STATIC/'index.html')


@app.get('/api/config')
def config():
    return {'openai_ready':bool(os.getenv('OPENAI_API_KEY')),
            'auth_enabled':auth_enabled(),
            'image_models':['gpt-image-2.5-flare','gpt-image-2.5-sunburst'],
            'max_file_mb':20,'max_files':MAX_FILES,'formats':[{'id':'4x3','size':[1440,1080]},{'id':'9x16','size':[1080,1920]}],
            'preview':True}


@app.get('/api/demo')
def demo():
    return {'brief':default_brief(),
            'reference_4x3':'/static/demo_4x3.svg',
            'reference_9x16':'/static/demo_9x16.svg',
            'sample_hero':'/static/demo_4x3.svg'}


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
            try:
                img=Image.open(io.BytesIO(raw));img.verify()
                if img.width>10000 or img.height>10000:raise ValueError('large image')
            except Exception:raise HTTPException(400,detail=f'{name}: файл не является корректным изображением')
        out.append((name,raw))
    return out


def _normalize(data):
    if not isinstance(data,dict):raise HTTPException(400,detail='Некорректная форма данных')
    clean={}
    for key,lim in [('brand',70),('category',100),('model',80),('slogan',250),('design_notes',1800),('design_actions',1200),('price',30),('currency',12)]:
        clean[key]=str(data.get(key,''))[:lim].strip()
    clean['accent']=valid_hex(data.get('accent','#E31B26'))
    clean['style']=str(data.get('style','industrial')) if data.get('style') in {'industrial','graphite','minimal'} else 'industrial'
    clean['vat']=bool(data.get('vat',True));clean['show_roi']=bool(data.get('show_roi',False))
    for key,count,lim in [('benefits',12,160),('hero_claims',4,120),('phones',2,48)]:
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


def _generate_sync(brief,hero_raw,detail_raw,logo_raw,drawing_raw,references,use_demo,use_openai,model,quality):
    _clean_jobs()
    job_id=secrets.token_hex(16)
    folder=STORAGE/job_id;folder.mkdir(mode=0o700)
    try:
        hero=load_image(hero_raw)
        detail=load_image(detail_raw)
        logo=load_image(logo_raw)
        drawing=load_image(drawing_raw)
        if hero is None and use_demo and not use_openai:
            hero=_demo_hero()
        visuals={};ai_product=False
        if use_openai:
            visuals=generate_visuals(brief,hero_present=(hero is not None),references=references,model=model,quality=quality)
            ai_product=hero is None
        paths={}
        for key,filename in [('4x3','poster_4x3.png'),('9x16','poster_9x16.png')]:
            atmosphere=visuals.get(key)
            product=atmosphere if ai_product else hero
            bg=None if ai_product else atmosphere
            img=render_poster(brief,key,hero=product,detail=detail,logo=logo,drawing=drawing,backdrop=bg,ai_product=ai_product)
            (folder/filename).write_bytes(image_bytes(img))
            paths[key]=f'/files/{job_id}/{filename}'
        briefing=dict(brief)
        briefing['_metadata']={'generator':'Promo Studio 1.0','image_source':'OpenAI API' if use_openai else 'Исходное фото пользователя / демо',
                  'ai_product_visualization':ai_product,'verified_specs':False,'design_actions_sent_to_ai':bool(use_openai and brief.get('design_actions')),
                  'note':'Технические характеристики, преимущества, экономику и права на материалы подтвердите до публикации.'}
        (folder/'brief.json').write_text(json.dumps(briefing,ensure_ascii=False,indent=2),encoding='utf-8')
        with zipfile.ZipFile(folder/'promo_kit.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for file in ['poster_4x3.png','poster_9x16.png','brief.json']:
                z.write(folder/file,arcname=file)
        return {'job_id':job_id,'images':paths,'zip':f'/files/{job_id}/promo_kit.zip',
                'brief':f'/files/{job_id}/brief.json',
                'ai_used':use_openai,'visualization':ai_product,
                'warnings':['Проверяйте каждую техническую цифру и сравнительное преимущество до публикации.'] +
                (['Дополнительные действия сохранены в брифе, но без OpenAI не применяются к визуалу.'] if brief.get('design_actions') and not use_openai else [])}
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise


@app.post('/api/generate')
async def generate(request:Request):
    _guard_rate(request)
    if int(request.headers.get('content-length') or 0)>MAX_ALL:
        raise HTTPException(413,detail='Превышен общий лимит загрузки 68 МБ')
    form=await request.form()
    raw=form.get('payload','{}')
    if not isinstance(raw,str) or len(raw)>48000:raise HTTPException(400,detail='Некорректные данные формы')
    try:brief=_normalize(json.loads(raw))
    except json.JSONDecodeError:raise HTTPException(400,detail='Некорректный JSON')
    pairs={k:(await _files(form,k,ALLOWED_IMAGES | ({'.pdf'} if k=='drawing' else set()))) for k in ['hero','detail','logo','drawing']}
    refs=await _files(form,'references',ALLOWED_IMAGES,collection=True)
    docs=await _files(form,'documents',ALLOWED_DOCS,collection=True)
    if len(refs)+len(docs)+sum(len(v) for v in pairs.values())>MAX_FILES:
        raise HTTPException(400,detail=f'Не более {MAX_FILES} файлов за запрос')
    all_files=refs+docs+sum(pairs.values(),[])
    if sum(len(content) for _,content in all_files)>MAX_ALL:
        raise HTTPException(413,detail='Общий объём файлов не должен превышать 68 МБ')
    # Documents are intentionally never auto-trusted as copy; extract/approve in /api/inspect first.
    use_openai=str(form.get('use_openai','false')).lower()=='true'
    use_demo=str(form.get('use_demo','false')).lower()=='true'
    if use_openai and not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(400,detail='Для AI-генерации укажите OPENAI_API_KEY на сервере. Доступен предпросмотр без API.')
    drawing_raw=pairs['drawing'][0][1] if pairs['drawing'] else None
    if drawing_raw and pairs['drawing'][0][0].lower().endswith('.pdf'):
        try:drawing_raw=await asyncio.to_thread(pdf_first_page_png,drawing_raw)
        except ValueError as exc:raise HTTPException(400,detail=str(exc))
    try:
        result=await asyncio.to_thread(
            _generate_sync,brief,
            pairs['hero'][0][1] if pairs['hero'] else None,
            pairs['detail'][0][1] if pairs['detail'] else None,
            pairs['logo'][0][1] if pairs['logo'] else None,
            drawing_raw,
            [x[1] for x in refs],use_demo,use_openai,str(form.get('model','gpt-image-2.5-flare')),
            str(form.get('quality','medium')))
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


@app.post('/api/inspect')
async def inspect(request:Request):
    if int(request.headers.get('content-length') or 0)>MAX_ALL:raise HTTPException(413,detail='Файлы слишком большие')
    form=await request.form()
    docs=await _files(form,'documents',ALLOWED_DOCS,collection=True)
    if not docs:raise HTTPException(400,detail='Загрузите PDF, DOCX, XLSX, CSV или TXT')
    if len(docs)>MAX_FILES:raise HTTPException(400,detail='Слишком много документов')
    warnings=[];contents=[];parsed=[]
    for name,raw in docs:
        try:text,issues=extract_text(name,raw)
        except ValueError as exc:raise HTTPException(400,detail=f'{name}: {exc}')
        contents.append(f'\n----- FILE {name} -----\n'+text)
        warnings.extend([f'{name}: {msg}' for msg in issues])
        parsed.append({'file':name,'characters':len(text)})
    joined='\n'.join(contents)[:35000]
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
    return FileResponse(path,headers={'Cache-Control':'private, no-store'},filename=filename if filename.endswith('.zip') else None)
