"""Import and revise a paid PromoEditor pair without buying new base artwork.

No extraction of arbitrary ZIP paths. Only recognized bundle members are
read/copied, under size and image geometry limits. Source jobs stay immutable.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageChops

from .ai_artwork_fit import artwork_geometry
from .ai_poster_finish import try_expand_artwork, repair_artwork, validate_repair
from .ai_poster_review import (expected_fields, review_pair, skipped_review,
                               pending_review, normalized_region)
from .ai_review_archive import attach_review
from .openai_service import IMAGE_MODELS, IMAGE_QUALITIES, _default_visual_cache

FORMATS={"4x3":(1440,1080),"9x16":(1080,1920)}
MAX_ARCHIVE=68*1024*1024
MAX_MEMBER=20*1024*1024
MAX_EXPANDED=140*1024*1024
MAX_JSON=256*1024
VERSION="poster-bundle-revision-v1"
KNOWN=re.compile(
    r"(?:ai_poster_(?:4x3|9x16)\.(?:png|jpg)|native_ai_artwork_(?:4x3|9x16)\.png|"
    r"rebranded_product\.png|(?:approved_copy|brief|selected_photo|export_geometry|"
    r"poster_review|refinement_history)\.json|REVIEW_BEFORE_PUBLICATION\.txt|"
    r"originals/(?:product_photo|customer_logo|drawing_preview|secondary_photo|style_reference)\.(?:jpg|png|webp)|"
    r"originals/drawing_source\.pdf)"
)


def _json(z,name,default=None):
    if name not in z.namelist():
        if default is not None:
            return default
        raise ValueError("В ZIP отсутствует "+name+".")
    if z.getinfo(name).file_size>MAX_JSON:
        raise ValueError("Слишком большой файл данных в ZIP.")
    try:
        value=json.loads(z.read(name))
    except (ValueError,UnicodeError) as exc:
        raise ValueError("Некорректный JSON в ZIP.") from exc
    return value


def _image(raw, size=None):
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (size is not None and (image.size!=size or image.format!="PNG")):
                raise ValueError("Некорректные размеры или формат PNG плаката.")
            if image.width<1 or image.height<1 or max(image.size)>4096 or image.width*image.height>9_000_000:
                raise ValueError("Недопустимое разрешение AI-изображения.")
            image.load()
            return image.convert("RGB")
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError("Повреждённое изображение в ZIP.") from exc


def _check_approved(approved):
    if not isinstance(approved,dict):
        raise ValueError("В ZIP отсутствуют корректные исходные данные.")
    for name in ("technical_specifications","engineering_dimensions"):
        rows=approved.get(name,[])
        if (not isinstance(rows,list) or len(rows)>100 or
                any(not isinstance(r,list) or len(r)!=2 or
                    any(not isinstance(s,str) or len(s)>1500 for s in r) for r in rows)):
            raise ValueError("Некорректные исходные характеристики в ZIP.")
    if (not isinstance(approved.get("model"),str) or not approved["model"].strip() or
            len(approved["model"])>500 or
            not isinstance(approved.get("phone_numbers",[]),list) or
            len(approved.get("phone_numbers",[]))>20 or
            any(not isinstance(p,str) or len(p)>150 for p in approved.get("phone_numbers",[])) or
            approved.get("verified_economic_scenario") is not None and
            not isinstance(approved.get("verified_economic_scenario"),dict)):
        raise ValueError("Некорректные исходные данные в ZIP.")
    for name in ("selling_claims","customer_benefits","approved_proofs"):
        values=approved.get(name,[])
        if (not isinstance(values,list) or len(values)>20 or
                any(not isinstance(s,str) or len(s)>500 for s in values)):
            raise ValueError("Некорректные рекламные сведения в ZIP.")
    if len(expected_fields(approved))>250:
        raise ValueError("Слишком много полей для сверки.")


def _safe_review(raw, approved):
    """An imported report is evidence for UI, not permission to edit."""
    if not isinstance(raw,dict) or raw.get("status") not in (
            "issues_found","no_issues_detected","not_requested","unavailable"):
        return skipped_review()
    if raw["status"] in ("not_requested","unavailable"):
        return {**skipped_review(),"status":raw["status"],
                "reason":str(raw.get("reason",""))[:500]}
    fields={x["id"]:x for x in expected_fields(approved)}
    reports=raw.get("formats")
    if not isinstance(reports,dict):
        return skipped_review()
    clean={"status":raw["status"],"human_review_required":True,
           "issues_count":0,"formats":{}}
    for fmt in FORMATS:
        report=reports.get(fmt)
        if not isinstance(report,dict):
            return skipped_review()
        checks=[]
        values=report.get("fields",[])
        if not isinstance(values,list):
            return skipped_review()
        for item in values[:250]:
            if not isinstance(item,dict) or item.get("id") not in fields:
                continue
            field=fields[item["id"]]
            region=item.get("region")
            if (not isinstance(region,list) or len(region)!=4 or
                    any(type(n) is not int for n in region) or
                    not(0<=region[0]<region[2]<=1000 and 0<=region[1]<region[3]<=1000)):
                region=None
            state=item.get("status")
            checks.append({**field,"observed":str(item.get("observed",""))[:500],
                           "status":state if state in ("match","different","missing","unreadable","conflicting","unverified") else "unverified",
                           "region":region})
        visuals=[]
        if isinstance(report.get("visuals"),list):
            for item in report["visuals"][:30]:
                if isinstance(item,dict):
                    visuals.append({"id":str(item.get("id",""))[:80],
                                    "observation":str(item.get("observation",""))[:500],
                                    "region":normalized_region(item.get("region")),
                                    "status":item.get("status") if item.get("status") in
                                    ("no_issue_detected","issue","uncertain") else "uncertain"})
        vehicle=report.get("vehicle_check",{})
        issues=vehicle.get("issues",[]) if isinstance(vehicle,dict) else []
        issues=[s[:500] for s in issues[:50] if isinstance(s,str)] if isinstance(issues,list) else []
        count=sum(c["status"]!="match" for c in checks)+sum(v["status"]!="no_issue_detected" for v in visuals)+len(issues)
        clean["formats"][fmt]={"fields":checks,"visuals":visuals,"vehicle_check":{"issues":issues},"issues_count":count}
        clean["issues_count"]+=count
    if clean["issues_count"]:
        clean["status"]="issues_found"
    return clean


def inspect_bundle(z):
    members=z.infolist()
    names=[i.filename for i in members]
    if (not members or len(members)>48 or len(set(names))!=len(names) or
            any(not KNOWN.fullmatch(i.filename) or i.is_dir() or i.flag_bits&1 or
                i.file_size>MAX_MEMBER for i in members) or
            sum(i.file_size for i in members)>MAX_EXPANDED):
        raise ValueError("Неподдерживаемый или слишком большой ZIP-комплект PromoEditor.")
    approved=_json(z,"approved_copy.json")
    _check_approved(approved)
    raw_geometry=_json(z,"export_geometry.json")
    if not isinstance(raw_geometry,dict):
        raise ValueError("Не найдена геометрия исходных плакатов.")
    geometry={}
    for fmt,target in FORMATS.items():
        required=(f"ai_poster_{fmt}.png",f"ai_poster_{fmt}.jpg",f"native_ai_artwork_{fmt}.png")
        if any(name not in names for name in required):
            raise ValueError("В ZIP нет полной пары исходных AI-плакатов.")
        source=_image(z.read(required[2]))
        computed=artwork_geometry(source.size,target)
        prior=raw_geometry.get(fmt,{})
        if not isinstance(prior,dict) or any(prior.get(k)!=computed[k] for k in ("source_size","target_size","content_box","crop","matte_rgb")):
            raise ValueError("Геометрия ZIP не соответствует исходным изображениям.")
        # Actual final dimensions are mandatory. We don't use a downloaded
        # JPEG as a source for precision editing.
        final=_image(z.read(required[0]),target)
        box=tuple(computed["content_box"])
        prior_finish=prior.get("outpaint",{})
        finish_status=prior_finish.get("status") if isinstance(prior_finish,dict) else None
        if finish_status in ("complete","not_needed"):
            # Retain the declared history but never overwrite existing bleed.
            computed["outpaint"]=prior_finish
        elif box==(0,0,*target):
            computed["outpaint"]={"status":"not_needed","protected_box":list(box)}
        else:
            computed["outpaint"]={"status":"not_requested"}
        if box==(0,0,*target) and prior.get("generation")=="native_target_aspect":
            computed["generation"]="native_target_aspect"
        if isinstance(prior.get("local_repair"),dict):
            computed["local_repair"]=prior["local_repair"]
        geometry[fmt]=computed
        del source,final
    review=_safe_review(_json(z,"poster_review.json",{}),approved)
    selected=_json(z,"selected_photo.json",{})
    if not isinstance(selected,dict):
        selected={}
    primary=selected.get("selected_primary",{})
    if not isinstance(primary,dict):
        primary={}
    selected_photo={k:str(primary[k])[:240] for k in ("id","name","sha256") if k in primary}
    return approved,geometry,review,selected_photo


def _open_bundle(path):
    try:
        if path.stat().st_size>MAX_ARCHIVE:
            raise ValueError("ZIP превышает 68 МБ.")
        return zipfile.ZipFile(path)
    except (OSError,zipfile.BadZipFile) as exc:
        raise ValueError("Не удалось открыть ZIP PromoEditor.") from exc


def _public_result(job_id,geometry,review,selected,revision=None):
    prefix=f"/files/{job_id}/"
    warnings=["Проверьте факты, логотип, геометрию и читаемость перед публикацией."]
    if revision and revision.get("status")=="failed":
        warnings.append(revision["reason"])
    return {"job_id":job_id,"images":{fmt:prefix+f"ai_poster_{fmt}.png" for fmt in FORMATS},
            "jpeg":{fmt:prefix+f"ai_poster_{fmt}.jpg" for fmt in FORMATS},
            "zip":prefix+"ai_posters.zip","generation_mode":"openai_full_poster",
            "ai_used":True,"raster_only":True,"selected_photo":selected,
            "publication_status":"human_review_required","poster_review":review,
            "export_geometry":geometry,"refinement":revision,
            "review_gate":"blocked" if review["status"]=="issues_found" or
            (revision and revision.get("status")=="failed") else "human_review_required",
            "warnings":warnings}


def import_bundle(path,folder,job_id):
    """Validate a previously downloaded package without any paid call."""
    with _open_bundle(path) as z:
        approved,geometry,review,selected=inspect_bundle(z)
        for fmt in FORMATS:
            for ext in ("png","jpg"):
                name=f"ai_poster_{fmt}.{ext}"
                (folder/name).write_bytes(z.read(name))
        # Validate CRCs of all archive members without retaining them in RAM.
        for item in z.infolist():
            with z.open(item) as source:
                while source.read(1024*1024):
                    pass
    path.replace(folder/"ai_posters.zip")
    return _public_result(job_id,geometry,review,selected,
                          {"status":"imported","action":"import","changed_formats":[]})


def _source_asset(z,stem):
    for name in (stem+".png",stem+".jpg",stem+".webp"):
        if name in z.namelist():
            return z.read(name)
    return None


def revise_bundle(path,folder,job_id,*,action,fmt,region,instruction,
                  model,quality,verify,attempt,progress=None,on_ready=None):
    if model not in IMAGE_MODELS or quality not in IMAGE_QUALITIES:
        raise ValueError("Недопустимые настройки OpenAI Images.")
    if action not in ("expand","repair","review"):
        raise ValueError("Неизвестная операция доработки.")
    if action=="repair":
        if fmt not in FORMATS:
            raise ValueError("Выберите формат плаката.")
        region=validate_repair(FORMATS[fmt],region,instruction)
    with _open_bundle(path) as z:
        approved,geometry,review,selected=inspect_bundle(z)
        history=_json(z,"refinement_history.json",[])
        if not isinstance(history,list):
            history=[]
        history=history[-30:]
        revision={"status":"complete","action":action,"changed_formats":[],"operations":{}}
        for key,target in FORMATS.items():
            png,jpg=f"ai_poster_{key}.png",f"ai_poster_{key}.jpg"
            raw=z.read(png)
            if action=="review":
                # A review-only operation must not decode/re-encode or
                # generate either image. inspect_bundle already validated PNGs.
                (folder/png).write_bytes(raw)
                (folder/jpg).write_bytes(z.read(jpg))
                continue
            source=_image(raw,target)
            final=source
            if action=="expand":
                if progress:
                    progress("AI дорисовывает поля "+key+"; оригинальная композиция защищена")
                final,operation=try_expand_artwork(source,geometry[key],model=model,
                                                    quality=quality,attempt=attempt)
                geometry[key]["outpaint"]=operation
                revision["operations"][key]=operation
                if operation["status"]=="failed":
                    revision["status"]="failed"
                    revision["reason"]=operation["reason"]
            elif action=="repair" and key==fmt:
                # Don't let a local edit consume old empty matte that the
                # outpainting stage is supposed to fill separately.
                if geometry[key]["outpaint"]["status"] not in ("complete","not_needed"):
                    x,y,r,b=geometry[key]["content_box"]
                    if not(x<=region[0]<region[2]<=r and y<=region[1]<region[3]<=b):
                        raise ValueError("Выделите область внутри исходного плаката, не захватывая пустые поля.")
                if progress:
                    progress("AI исправляет выбранную область "+key+"; остальные пиксели защищены")
                try:
                    final,operation=repair_artwork(source,region,instruction,model=model,
                                                   quality=quality,attempt=attempt)
                    geometry[key]["local_repair"]=operation
                except Exception:
                    final=source
                    operation={"status":"failed","region":list(region)}
                    revision["status"]="failed"
                    revision["reason"]="Локальная AI-правка не завершена. Исходные изображения сохранены; автоматических повторов нет."
                revision["operations"][key]=operation
            if ImageChops.difference(final,source).getbbox() is not None:
                final.save(folder/png,"PNG")
                final.save(folder/jpg,"JPEG",quality=93,subsampling=0)
                revision["changed_formats"].append(key)
            else:
                # No re-encoding of the other format, even its JPEG bytes.
                (folder/png).write_bytes(raw)
                (folder/jpg).write_bytes(z.read(jpg))
            del source,final,raw
        needs_review=bool(action=="review" or (revision["changed_formats"] and verify))
        if action=="review":
            review=pending_review()
        elif revision["changed_formats"]:
            # Previous QA is stale as soon as any image pixel changes.
            review=pending_review() if needs_review else skipped_review()
        elif revision["status"]!="failed":
            revision["status"]="no_change"
        history.append(revision)
        replacements={"export_geometry.json":geometry,"poster_review.json":review,
                      "refinement_history.json":history}
        output=folder/"ai_posters.zip"
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_STORED) as out:
            for member in z.infolist():
                name=member.filename
                if name in replacements or name=="REVIEW_BEFORE_PUBLICATION.txt" or re.fullmatch(r"ai_poster_(4x3|9x16)\.(png|jpg)",name):
                    continue
                # Copy only names validated by inspect_bundle, no path extraction.
                with z.open(member) as src,out.open(name,"w") as dest:
                    shutil.copyfileobj(src,dest,1024*1024)
            for key in FORMATS:
                for ext in ("png","jpg"):
                    name=f"ai_poster_{key}.{ext}"
                    out.write(folder/name,name)
            for name,data in replacements.items():
                out.writestr(name,json.dumps(data,ensure_ascii=False,indent=2))
            out.writestr("REVIEW_BEFORE_PUBLICATION.txt",
                         "Доработка AI-плакатов. Исходные native_ai_artwork и originals сохранены. "
                         "Дорисовка меняет только поля, локальная коррекция только выделенную область. "
                         "refinement_history.json содержит статус операции. "
                         "poster_review.json относится к текущим PNG. При неудачной дорисовке поля остаются. "
                         "Ручная проверка обязательна; это не подтверждение точности.")
        if output.stat().st_size>MAX_ARCHIVE:
            # Don't create a package that our own import cannot accept.
            raise ValueError("Доработанный комплект превышает лимит 68 МБ; исходный ZIP не изменён.")
        if needs_review:
            if on_ready:
                on_ready({**_public_result(job_id,geometry,review,selected,revision),
                          "review_pending":True})
            if progress:
                progress("Доработанный ZIP доступен; выполняется AI-сверка (до 180 секунд на запрос)")
            try:
                cache=_default_visual_cache(approved,True,[
                    (folder/f"ai_poster_{key}.png").read_bytes() for key in FORMATS
                ],model,quality,VERSION,("refinement-review:"+attempt
                                         if action=="review" else "refinement-review"))
                checked=review_pair(approved,folder,cache,
                                   logo=_source_asset(z,"originals/customer_logo"),
                                   drawing=_source_asset(z,"originals/drawing_preview"),
                                   product=_source_asset(z,"rebranded_product"),
                                   original_product=_source_asset(z,"originals/product_photo"))
                if attach_review(folder,checked):
                    review=checked
            except Exception:
                # Optional QA never destroys the completed paid edit.
                pass
    return {**_public_result(job_id,geometry,review,selected,revision),
            "review_pending":False}
