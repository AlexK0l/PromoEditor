/* Multi-file project organizer for PromoEditor. Files stay in the browser
   until the user explicitly submits analysis or generation. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const FIELDS=['hero','logo','documents','references','detail','drawing'];
  const LABELS={hero:'Фото',logo:'Логотип',documents:'Документ',references:'Референс',
                detail:'Дополнительное фото',drawing:'Чертёж'};
  const SERVER={hero:'photos',logo:'logos',documents:'documents',references:'references',
                detail:'detail',drawing:'drawing'};
  const files=Object.fromEntries(FIELDS.map(id=>[id,[]]));
  const preferences={};
  const thumbs=[];
  const skipChange=new Set();
  let report=null,dirty=true,busy=false,aiReady=false,accepted=false;

  function announce(message,warning=false){
    const node=$('assets-analysis-status');
    if(node){node.textContent=message;node.classList.toggle('is-warning',warning);}
  }
  function fileKey(file){return [file.name,file.size,file.lastModified,file.type].join('|');}
  function rows(){
    const out=[];
    const add=(id,kind,offset=0)=>{
      files[id].forEach((file,i)=>out.push({id:kind+'_'+(i+1+offset),field:id,kind,file,index:i}));
    };
    add('hero','photo');
    add('detail','photo',files.hero.length);
    add('logo','logo');
    add('documents','document');
    add('references','reference');
    add('drawing','drawing');
    return out;
  }
  function fileCount(){return rows().length;}
  function objectLink(file){const url=URL.createObjectURL(file);thumbs.push(url);return url;}
  function element(tag,cls,text){
    const node=document.createElement(tag);
    if(cls)node.className=cls;
    if(text!==undefined)node.textContent=text;
    return node;
  }
  function option(value,text){
    const opt=document.createElement('option');opt.value=value;opt.textContent=text;return opt;
  }
  function clearThumbnails(){for(const url of thumbs)URL.revokeObjectURL(url);thumbs.length=0;}
  function renderFiles(){
    const list=$('asset-files-list');
    if(!list)return;
    clearThumbnails();list.replaceChildren();
    const current=rows();
    if(!current.length){
      list.appendChild(element('p','asset-empty','Здесь появятся загруженные фотографии, документы и логотипы.'));
      return;
    }
    for(const entry of current){
      const card=element('div','asset-file-card');
      card.setAttribute('role','listitem');card.dataset.assetId=entry.id;
      if(/^image\//.test(entry.file.type)){
        const img=element('img','asset-thumb');
        img.src=objectLink(entry.file);img.alt='Миниатюра: '+entry.file.name;img.loading='lazy';
        card.appendChild(img);
      }else{
        card.appendChild(element('div','asset-thumb asset-file-icon','▤'));
      }
      const copy=element('div','asset-file-copy');
      copy.appendChild(element('strong','asset-file-name',entry.file.name));
      copy.appendChild(element('small','asset-file-info',
        LABELS[entry.field]+' · '+(entry.file.size/1024/1024).toFixed(2)+' МБ'));
      const known=!dirty&&(report?.project_assets||[]).find(a=>a.id===entry.id);
      if(known)copy.appendChild(element('small','asset-file-decision',
        known.selected?'✓ Выбран: '+(known.assignment==='analysis_only'?'для анализа':known.assignment):
          'Не включён в макет'));
      card.appendChild(copy);
      const controls=element('div','asset-file-controls');
      const select=element('select','asset-pref');
      select.setAttribute('aria-label','Приоритет файла '+entry.file.name);
      select.append(option('auto','AI выбирает'),
                    option('include',entry.kind==='document'?'Приоритет анализа':'Обязательно использовать'),
                    option('exclude','Не использовать'));
      select.value=preferences[entry.id]||'auto';
      select.addEventListener('change',()=>{
        preferences[entry.id]=select.value;
        markStale('Приоритеты изменились. Нажмите «Пересобрать выбор».');
      });
      controls.appendChild(select);
      const remove=element('button','asset-remove','✕');
      remove.type='button';remove.title='Удалить '+entry.file.name;
      remove.setAttribute('aria-label','Удалить файл '+entry.file.name);
      remove.addEventListener('click',()=>{
        files[entry.field].splice(entry.index,1);
        // File IDs depend on positions, so never apply stale preferences.
        for(const key of Object.keys(preferences))delete preferences[key];
        report=null;replaceInput(entry.field);
        markStale('Файл удалён. Повторите анализ, чтобы обновить выбор.');
        renderFiles();
      });
      controls.appendChild(remove);card.appendChild(controls);list.appendChild(card);
    }
  }
  function replaceInput(id){
    const input=$(id),transfer=new DataTransfer();
    for(const file of files[id])transfer.items.add(file);
    input.files=transfer.files;
    skipChange.add(id);
    input.dispatchEvent(new Event('change',{bubbles:true}));
  }
  function markStale(message){
    dirty=true;accepted=false;
    announce(message||'Список изменился. Проанализируйте файлы перед генерацией.',true);
    $('asset-approve')?.classList.remove('is-accepted');
    $('asset-selection')?.classList.add('is-stale');
    window.dispatchEvent(new CustomEvent('promoeditor:assets-changed'));
  }
  function handleFiles(event){
    const id=event.target.id;
    if(skipChange.delete(id)){renderFiles();return;}
    const incoming=Array.from(event.target.files||[]);
    if(!incoming.length){
      files[id]=[];
    }else if(event.target.multiple){
      const already=new Set(files[id].map(fileKey));
      const merged=[...files[id]];
      for(const item of incoming){
        const key=fileKey(item);
        if(!already.has(key)){merged.push(item);already.add(key);}
      }
      files[id]=merged;
    }else{
      files[id]=incoming.slice(0,1);
    }
    for(const key of Object.keys(preferences))delete preferences[key];
    report=null;
    // All FileLists stay in sync with append-style selection.
    replaceInput(id);
    markStale('Материалы обновлены. Проведите анализ перед созданием промо.');
    renderFiles();
  }
  function append(form){
    for(const id of FIELDS)for(const file of files[id])form.append(SERVER[id],file,file.name);
    form.append('asset_preferences',JSON.stringify(preferences));
    if(report)form.append('asset_report',JSON.stringify(report));
  }
  function lookup(id){
    return (report?.project_assets||[]).find(item=>item.id===id);
  }
  function nameOf(id){
    return lookup(id)?.name||'Не выбран';
  }
  function picked(label,ids){
    const line=element('div','asset-pick');
    line.appendChild(element('strong','',label));
    if(Array.isArray(ids))line.appendChild(element('span','',ids.length?ids.map(nameOf).join(', '):'Не выбраны'));
    else line.appendChild(element('span','',ids?nameOf(ids):'Не выбран'));
    return line;
  }
  function extractedSpecs(){
    if(!report)return [];
    const parsed=report.extracted_data||{};
    const source=(parsed.suggested_specs||[]).map(item=>({
      label:item.label,value:item.value,source_file:item.source_file,source_excerpt:item.source_excerpt
    }));
    const ai=parsed.ai_suggestions?.specs||[];
    for(const row of ai){
      if(!row?.label||!row?.value)continue;
      if(source.some(s=>s.label===row.label&&s.value===row.value))continue;
      source.push({label:String(row.label).slice(0,90),value:String(row.value).slice(0,160),
                   source_file:'AI-предложение',source_excerpt:String(row.source_excerpt||'').slice(0,160)});
    }
    return source.slice(0,12);
  }
  function renderReport(){
    const panel=$('asset-selection');
    panel.hidden=!report;
    if(!report)return;
    panel.classList.toggle('is-stale',dirty);
    const selected=report.selected_assets||{};
    $('asset-analysis-method').textContent=report.analysis_method==='ai'?
      'Оценка изображений AI + проверка файлов':'Технический отбор без AI';
    $('asset-picked').replaceChildren(
      picked('Главное фото',selected.primary_photo),
      picked('Дополнительный ракурс',selected.secondary_photo),
      picked('Логотип',selected.logo),
      picked('Чертёж',selected.drawing),
      picked('Референсы',selected.references||[]),
      picked('Документы для анализа',selected.documents||[])
    );
    const unused=$('asset-unused');unused.replaceChildren();
    for(const record of (report.rejected_assets||[])){
      const line=element('p','asset-unused-row');
      line.appendChild(element('strong','',record.name+' — '));
      line.appendChild(document.createTextNode(record.reason||'Не выбран.'));
      unused.appendChild(line);
    }
    if(!unused.childElementCount)unused.appendChild(element('p','asset-fineprint','Все подходящие файлы распределены по ролям.'));
    const facts=extractedSpecs();
    $('asset-facts').hidden=!facts.length;
    const list=$('asset-specs-list');list.replaceChildren();
    for(const item of facts){
      list.appendChild(element('p','asset-fact',
        item.label+': '+item.value+' · источник: '+(item.source_file||'не подтверждён')+
        (item.source_excerpt?' · '+item.source_excerpt:'')));
    }
    const warnings=$('asset-analysis-warnings');warnings.replaceChildren();
    for(const warning of (report.warnings||[]).slice(0,12)){
      warnings.appendChild(element('p','',warning));
    }
    renderFiles();
  }
  async function errorText(response){
    try{const data=await response.json();return data.detail||('HTTP '+response.status);}
    catch{return 'Ошибка HTTP '+response.status;}
  }
  async function analyze(brief,{freeOnly=false}={}){
    if(busy)return null;
    if(!fileCount())throw Error('Сначала загрузите хотя бы один файл.');
    const ai=!freeOnly && $('assets-use-ai').checked;
    if(ai&&!aiReady)throw Error('OpenAI для анализа не настроен. Выключите AI-анализ.');
    if(ai&&!window.confirm(
      'Для оценки ВСЕХ изображений и извлечения сведений из документов будут выполнены платные запросы OpenAI (возможно несколько). Подтвердить анализ?'
    ))return null;
    busy=true;
    $('analyze-assets-btn').disabled=true;
    $('asset-rebuild').disabled=true;
    $('analyze-assets-btn').textContent='Анализируем…';
    announce('Проверяем все файлы и выбираем лучшее сочетание…');
    try {
      const form=new FormData();
      append(form);
      form.append('payload',JSON.stringify(brief||{}));
      form.append('use_ai',String(ai));
      const response=await fetch('/api/analyze-assets',{method:'POST',body:form});
      if(!response.ok)throw Error(await errorText(response));
      const result=await response.json();
      if(!Array.isArray(result.project_assets)||!result.selected_assets)
        throw Error('Сервер вернул неполный анализ файлов.');
      report=result;dirty=false;accepted=false;
      renderReport();
      announce('Анализ выполнен. Проверьте выбранные материалы; можно изменить приоритеты и пересобрать выбор.');
      window.dispatchEvent(new CustomEvent('promoeditor:assets-analyzed',{detail:result}));
      return result;
    }catch(error){
      announce(error.message||'Не удалось проанализировать вложения.',true);
      throw error;
    }finally{
      busy=false;$('analyze-assets-btn').disabled=false;$('asset-rebuild').disabled=false;
      $('analyze-assets-btn').textContent='Проанализировать материалы';
    }
  }
  function setAiReady(ready){
    aiReady=!!ready;
    const box=$('assets-use-ai');
    box.disabled=!aiReady;
    if(!aiReady)box.checked=false;
    else if(!box.dataset.userChosen)box.checked=true;
    $('assets-ai-hint').textContent=aiReady?
      'AI оценивает ракурс и содержимое всех фото, а также документы. Платные запросы — после подтверждения.':
      'Без ключа OpenAI доступна бесплатная техническая оценка (разрешение, резкость, повторы).';
  }
  function reset(){
    for(const id of FIELDS){
      files[id]=[];
      $(id).value='';
    }
    for(const key of Object.keys(preferences))delete preferences[key];
    report=null;dirty=true;accepted=false;
    $('asset-selection').hidden=true;
    announce('Добавьте файлы и нажмите «Проанализировать материалы».');
    renderFiles();
  }
  for(const id of FIELDS){
    const node=$(id);
    if(node){
      files[id]=Array.from(node.files||[]);
      node.addEventListener('change',handleFiles);
    }
  }
  $('assets-use-ai').addEventListener('change',event=>{event.target.dataset.userChosen='1';});
  $('asset-approve').addEventListener('click',()=>{
    if(dirty){announce('Сначала пересоберите выбор после изменений.',true);return;}
    accepted=true;
    $('asset-approve').classList.add('is-accepted');
    announce('Выбор принят. Теперь можно проверить промпт и создать промо.');
  });
  $('asset-manual').addEventListener('click',()=>{
    $('asset-files-list').scrollIntoView({behavior:'smooth',block:'center'});
    const first=$('asset-files-list').querySelector('select');
    if(first)first.focus({preventScroll:true});
    announce('Для каждого файла выберите «Обязательно использовать», «AI выбирает» или «Не использовать». После изменений пересоберите выбор.');
  });
  renderFiles();
  window.PromoAssets={
    append,analyze,reset,setAiReady,extractedSpecs,rows,
    hasFiles:()=>fileCount()>0,isReady:()=>!dirty&&!!report,
    getReport:()=>!dirty?report:null,getPreviousReport:()=>report,
    totalCount:fileCount,
    approveStatus:()=>accepted,
    validate:()=>{
      const list=rows();
      if(list.length>16)return 'Не более 16 файлов в одном проекте.';
      if(list.some(x=>x.file.size>20*1024*1024))return 'Каждый файл должен быть не более 20 МБ.';
      if(list.reduce((total,x)=>total+x.file.size,0)>68*1024*1024)return 'Общий размер файлов не более 68 МБ.';
      return '';
    }
  };
})();
