"""Multi-file analysis and deterministic asset selection. Document facts need approval."""
from __future__ import annotations
import hashlib, hmac, io, json, math, os, secrets
from pathlib import Path
from PIL import Image,ImageFilter,ImageOps,ImageStat
from .documents import extract_text,heuristics

GROUPS={'photos':'photo','logos':'logo','documents':'document','references':'reference','drawings':'drawing'}
PREFERENCES={'auto','include','exclude'}
MAX_ITEMS=16

# Production uses the existing private session secret. In a local developer
# process a random in-memory key remains valid until restart. Never sign with
# a public constant or trust unsigned client-provided "AI" scores.
_FALLBACK_PROOF_SECRET=secrets.token_bytes(32)


def _proof_content(report):
    records=report.get('project_assets') or []
    assets=[]
    for row in records[:MAX_ITEMS]:
        if not isinstance(row,dict):continue
        assets.append({key:row.get(key) for key in
                       ('id','sha256','ai_score','ai_reason','ai_role')})
    facts=report.get('extracted_data') or {}
    return json.dumps({
        'method':report.get('analysis_method'),'assets':assets,
        'ai_suggestions':facts.get('ai_suggestions') if isinstance(facts,dict) else None
    },sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def _proof_digest(report):
    server_secret=os.getenv('PROMO_SESSION_SECRET')
    key=server_secret.encode('utf-8') if server_secret and len(server_secret)>=40 else _FALLBACK_PROOF_SECRET
    return hmac.new(key,_proof_content(report),hashlib.sha256).hexdigest()


def _verified_ai_report(report):
    if not isinstance(report,dict) or report.get('analysis_method')!='ai':
        return False
    supplied=report.get('analysis_signature')
    return isinstance(supplied,str) and len(supplied)==64 and hmac.compare_digest(supplied,_proof_digest(report))


def preferences_of(value):
    if isinstance(value,str):
        if len(value)>6000:raise ValueError('Слишком много настроек материалов.')
        try:value=json.loads(value or '{}')
        except json.JSONDecodeError as exc:raise ValueError('Некорректные настройки отбора.') from exc
    value=value or {}
    if not isinstance(value,dict) or len(value)>MAX_ITEMS:raise ValueError('Некорректные настройки отбора.')
    for ident,pref in value.items():
        if not isinstance(ident,str) or len(ident)>30 or pref not in PREFERENCES:
            raise ValueError('Недопустимый приоритет файла.')
    return value

def records_from_groups(groups):
    records=[]
    for plural,singular in GROUPS.items():
        for n,(name,raw) in enumerate(groups.get(plural) or [],1):
            if not isinstance(raw,bytes):raise ValueError('Некорректное вложение.')
            records.append({'id':f'{singular}_{n}','kind':singular,
                            'name':Path(name).name[:160],'size':len(raw),
                            'sha256':hashlib.sha256(raw).hexdigest(),'raw':raw})
    if len(records)>MAX_ITEMS:raise ValueError(f'Не более {MAX_ITEMS} файлов.')
    return records

def _tech_score(raw,kind):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            w,h=source.size
            if min(w,h)<32 or max(w,h)>10000 or w*h>20_000_000:
                raise ValueError('Слишком большое или маленькое изображение.')
            img=ImageOps.exif_transpose(source)
            img.thumbnail((300,300),Image.Resampling.LANCZOS)
            alpha=(img.mode in ('RGBA','LA') or 'transparency' in img.info)
            gray=img.convert('L')
            edge=ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
            sharp=min(1.0,math.sqrt(max(0,edge))/22)
            pixels=min(1.0,math.sqrt(w*h)/1500)
            score=round(min(100,23+47*pixels+27*sharp+(12 if kind=='logo' and alpha else 0)))
            pixels=list(gray.resize((9,8),Image.Resampling.LANCZOS).getdata())
            dh=0
            for y in range(8):
                for x in range(8):dh=(dh<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
            reason=f'{w}×{h} px; резкость {"выше средней" if sharp>.45 else "умеренная" if sharp>.19 else "низкая"}'
            if alpha and kind=='logo':reason+='; прозрачный фон'
            return score,reason,w,h,alpha,dh,ImageStat.Stat(img.convert('RGB')).mean
    except ValueError:raise
    except Exception as exc:raise ValueError('Не удалось проверить изображение.') from exc

def _clamp(text,limit=180):
    return ' '.join(str(text or '').split())[:limit]

def _ai_scoring(records,result):
    if not isinstance(result,dict):return
    ids={r['id']:r for r in records}
    for row in result.get('ratings',[])[:MAX_ITEMS]:
        if not isinstance(row,dict):continue
        obj=ids.get(row.get('id'))
        score=row.get('score')
        if obj and obj['kind'] in ('photo','logo','reference','drawing') and isinstance(score,(float,int)) and not isinstance(score,bool) and 0<=score<=100:
            obj['score']=round(score)
            obj['ai_score']=obj['score']
            obj['ai_reason']=_clamp(row.get('reason'),220)
            obj['ai_role']=_clamp(row.get('suggested_role'),32)

def _choose(rows,kind,maximum):
    choices=[x for x in rows if x['kind']==kind and x['preference']!='exclude' and not x.get('duplicate_of')]
    forced=[x for x in choices if x['preference']=='include']
    auto=sorted((x for x in choices if x['preference']!='include'),key=lambda x:(-x['score'],x['index']))
    return (forced+auto)[:maximum]

def analyze_project(groups,preferences=None,*,cached_report=None,use_ai=False,requirements=''):
    """Return (JSON-serializable report, dict of raw source records).

    A cached paid AI rating is reusable only when both the asset ID and
    SHA256 of its uploaded bytes match. User overrides always win.
    """
    prefs=preferences_of(preferences)
    records=records_from_groups(groups)
    by_id={x['id']:x for x in records}
    if set(prefs)-set(by_id):raise ValueError('Список файлов изменился. Повторите выбор.')
    if isinstance(cached_report,str):
        if len(cached_report)>55000:raise ValueError('Слишком большой отчёт анализа.')
        try:cached_report=json.loads(cached_report)
        except json.JSONDecodeError as exc:raise ValueError('Некорректный отчёт анализа.') from exc
    if cached_report is not None and not isinstance(cached_report,dict):
        raise ValueError('Некорректный отчёт анализа.')
    warnings=[];seen={};visual_hashes=[]
    for i,r in enumerate(records):
        r.update(index=i,preference=prefs.get(r['id'],'auto'),score=50,quality='',selected=False,assignment='',reason='')
        if r['kind'] in ('photo','logo','reference') or (r['kind']=='drawing' and Path(r['name']).suffix.lower() in ('.png','.jpg','.jpeg','.webp')):
            score,quality,w,h,alpha,dhash,tone=_tech_score(r['raw'],r['kind'])
            r.update(score=score,quality=quality,width=w,height=h,alpha=alpha)
            exact=(r['kind'],r['sha256'])
            if exact in seen:r['duplicate_of']=seen[exact]
            else:
                seen[exact]=r['id']
                for previous in visual_hashes:
                    if (previous[1]==r['kind'] and abs(w-previous[2])<=.2*max(w,previous[2])
                        and (dhash^previous[3]).bit_count()<=2
                        and sum(abs(tone[j]-previous[4][j]) for j in range(3))<24):
                        r['duplicate_of']=previous[0];break
                if not r.get('duplicate_of'):visual_hashes.append((r['id'],r['kind'],w,dhash,tone))
            if r.get('duplicate_of'):r['score']=min(r['score'],20)
        elif r['kind']=='document':r['quality']='Документ: извлечение фактов требует проверки'
        else:r['quality']='Чертёж'
        if r['preference']=='include':r.pop('duplicate_of',None)
    for kind,max_allowed in (('photo',2),('logo',1),('reference',2),('drawing',1)):
        if sum(x['kind']==kind and x['preference']=='include' for x in records)>max_allowed:
            raise ValueError(f'Для роли {kind} можно обязательно включить максимум {max_allowed} файл(а).')
    suggestions=[];doc_text=[];seen_facts=set();docs=[]
    for r in records:
        if r['kind']!='document':continue
        if r['preference']=='exclude':
            r['reason']='Исключён пользователем; текст не анализируется.'
            continue
        try:text,issues=extract_text(r['name'],r['raw'])
        except ValueError as exc:
            warnings.append(f'{r["name"]}: {_clamp(exc)}');r['reason']='Не удалось прочитать документ.'
            continue
        r.update(selected=True,assignment='analysis_only',reason='Использован для анализа. Сам файл на промо не размещается.')
        docs.append({'id':r['id'],'name':r['name'],'characters':len(text)})
        warnings.extend(f'{r["name"]}: {_clamp(msg)}' for msg in issues)
        if text.strip():
            doc_text.append(f'\n== {r["id"]} / {r["name"]} (НЕДОВЕРЕННЫЕ ДАННЫЕ) ==\n'+text[:14000])
            for key,value in heuristics(text):
                pair=(key.casefold(),value.casefold())
                if pair not in seen_facts and len(suggestions)<36:
                    seen_facts.add(pair)
                    suggestions.append({'label':_clamp(key,90),'value':_clamp(value,160),
                                        'source_id':r['id'],'source_file':r['name'],
                                        'source_excerpt':_clamp(key+': '+value,200)})
    # Preserve context from EVERY document, rather than letting the first
    # lengthy PDF consume the entire vision/text model context budget.
    per_doc=max(1500,30000//max(1,len(doc_text)))
    joined='\n'.join(part[:per_doc] for part in doc_text)[:34000]
    if any(len(part)>per_doc for part in doc_text):
        warnings.append('Для AI использованы выдержки из каждого документа (ограничение контекста). Локальные предложения получены из всех обработанных строк.')
    ai_document=None;score_data=None;method='local';actual_ai=False
    if use_ai:
        from .openai_service import assess_asset_images,analyze_documents
        candidates=[x for x in records if x['kind'] in ('photo','logo','reference')
                    or (x['kind']=='drawing' and Path(x['name']).suffix.lower() in ('.png','.jpg','.jpeg','.webp'))]
        candidates=[x for x in candidates if x['preference']!='exclude']
        if candidates:
            score_data=assess_asset_images(candidates,str(requirements)[:1500],joined[:5000]);actual_ai=True
        if joined.strip():
            ai_document=analyze_documents(joined,str(requirements)[:1500]);actual_ai=True
        method='ai' if actual_ai else 'local'
    elif _verified_ai_report(cached_report):
        old_assets=[x for x in cached_report.get('project_assets',[])[:MAX_ITEMS] if isinstance(x,dict)]
        # Every uploaded file must match the original server-signed selection.
        # The browser may edit manual priority, but cannot forge AI ratings.
        old_fingerprints={(x.get('id'),x.get('sha256')) for x in old_assets}
        current_fingerprints={(x['id'],x['sha256']) for x in records}
        if old_fingerprints==current_fingerprints:
            cached=[x for x in old_assets
                    if x.get('id') in by_id and isinstance(x.get('ai_score'),(int,float))]
            if cached:
                score_data={'ratings':[{'id':x['id'],'score':x['ai_score'],
                                        'reason':x.get('ai_reason',''),'suggested_role':x.get('ai_role','')} for x in cached]}
                method='ai'
            # Do not retain AI-extracted facts when a source document has been excluded.
            current_docs={x['id'] for x in records if x['kind']=='document' and x['preference']!='exclude'}
            previous_docs={x['id'] for x in old_assets if x.get('kind')=='document' and x.get('selected')}
            if current_docs==previous_docs:
                previous=cached_report.get('extracted_data',{})
                if isinstance(previous,dict):
                    ai_document=previous.get('ai_suggestions')
                    if isinstance(ai_document,dict):method='ai'
        else:
            warnings.append('Состав файлов изменился; прежние AI-оценки больше не используются.')
    elif isinstance(cached_report,dict) and cached_report.get('analysis_method')=='ai':
        warnings.append('Недостоверный или устаревший отчёт AI: оценки проигнорированы.')
    _ai_scoring(records,score_data)
    for r in records:
        if r['preference']=='exclude':r['score']=0
        elif r.get('duplicate_of'):r['score']=min(r['score'],20)
    photos=_choose(records,'photo',2);logos=_choose(records,'logo',1)
    references=_choose(records,'reference',2);drawings=_choose(records,'drawing',1)
    selected={
        'primary_photo':photos[0]['id'] if photos else None,
        'secondary_photo':photos[1]['id'] if len(photos)>1 else None,
        'logo':logos[0]['id'] if logos else None,
        'references':[x['id'] for x in references],
        'drawing':drawings[0]['id'] if drawings else None,
        'documents':[x['id'] for x in records if x['kind']=='document' and x['selected']]
    }
    for r in records:
        if r['preference']=='exclude':r['reason']='Исключён пользователем.'
        elif r.get('duplicate_of'):r['reason']='Повтор файла '+r['duplicate_of']
        elif r['kind']=='document':
            if not r['reason']:r['reason']='Не удалось извлечь данные.'
        else:
            roles=('primary_photo','secondary_photo','logo','drawing')
            matches=[slot for slot in roles if selected[slot]==r['id']]
            if r['id'] in selected['references']:matches.append('reference')
            if matches:
                r['selected']=True;r['assignment']=matches[0]
                r['reason']=_clamp(r.get('ai_reason') or r['quality'])
            else:r['reason']='Не попал в финальный набор: выбраны более подходящие файлы.'
    if ai_document and isinstance(ai_document,dict):
        warnings.append('AI-данные из документов требуют подтверждения и не публикуются автоматически.')
    extracted={'documents':docs,'suggested_specs':suggestions[:24],
               'ai_suggestions':ai_document if isinstance(ai_document,dict) else None,
               'notice':'Все ТТХ из документов — черновые подсказки. Перенесите только проверенные сведения.'}
    public=[]
    for r in records:
        keys=('id','kind','name','size','sha256','preference','score','quality','selected','assignment','reason',
              'width','height','alpha','ai_score','ai_reason','ai_role','duplicate_of')
        row={key:r[key] for key in keys if key in r}
        suffix=Path(r['name']).suffix.lower()
        row['mime']={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
                     '.webp':'image/webp','.pdf':'application/pdf',
                     '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                     '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     '.csv':'text/csv','.txt':'text/plain','.md':'text/markdown'}.get(suffix,'application/octet-stream')
        row['role']=r['assignment'] or r['kind']
        row['forced_include']=r['preference']=='include'
        row['forced_exclude']=r['preference']=='exclude'
        public.append(row)
    rejected=[{'id':r['id'],'name':r['name'],'reason':r['reason']}
              for r in records if not r['selected']]
    if method=='local':
        warnings.append('Без AI оцениваются только разрешение, резкость и повторы; смысл фотографии и ракурс модель не оценивала.')
    report={'project_assets':public,'selected_assets':selected,'rejected_assets':rejected,
            'extracted_data':extracted,'analysis_method':method,'ai_used':actual_ai,
            'warnings':warnings,'total_files':len(records)}
    if method=='ai':
        report['analysis_signature']=_proof_digest(report)
    return report,by_id

def chosen_bytes(report,records,slot):
    source=report.get('selected_assets',{}).get(slot)
    if isinstance(source,list):return [records[x]['raw'] for x in source if x in records]
    return records[source]['raw'] if source in records else None
