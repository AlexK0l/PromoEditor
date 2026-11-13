(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fileIds = ['hero','documents','logo','detail','drawing','references'];
  const briefIds = ['model','slogan','design-notes','design-actions','brand','category','claims','specs','benefits','dimensions','price','currency','vat','phones','show-roi','extra-payload','distance','rate','trips','years','baseline-price','style','accent','use-openai','image-model','image-quality','use-demo'];
  const placeholders = {documents:'Несколько документов · PDF / Word / Excel',logo:'Несколько логотипов',detail:'Дополнительный ракурс',drawing:'PNG, JPG или PDF',references:'Несколько референсов; система отберёт до 2'};
  let latest = null;
  let apiReady = false;
  let isBusy = false;
  let hasDemo = false;
  let promptDirty = true;

  const get = id => $(id).value;
  const checked = id => $(id).checked;
  const set = (id,val) => { $(id).value = val ?? ''; };
  const lines = id => get(id).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  const asLines = values => (values||[]).map(x=>Array.isArray(x)?x.join(' | '):x).join('\n');
  const pairs = id => lines(id).map(line=>{
    const separator = line.includes('|')?'|':line.includes('\t')?'\t':line.includes(' = ')?' = ':' : ';
    const i=line.indexOf(separator);
    if(i<0)return null;
    const label=line.slice(0,i).trim(), value=line.slice(i+separator.length).trim();
    return label&&value?[label,value]:null;
  }).filter(Boolean);
  const number = id => Number(String(get(id)).replace(/\s/g,'').replace(',','.'))||0;
  const fmt = value => Number.isFinite(value)?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(value):'—';
  const money = value => `${fmt(value)} ${get('currency')}`;

  function formBrief(){
    return {
      brand:get('brand').trim(),model:get('model').trim(),category:get('category').trim(),
      slogan:get('slogan').trim(),design_notes:get('design-notes').trim(),design_actions:get('design-actions').trim(),
      style:get('style'),accent:get('accent'),
      hero_claims:lines('claims').slice(0,4),specs:pairs('specs'),benefits:lines('benefits'),dimensions:pairs('dimensions'),
      price:get('price').trim(),currency:get('currency'),vat:checked('vat'),phones:lines('phones').slice(0,2),
      show_roi:checked('show-roi'),roi:{extra_payload:get('extra-payload'),distance:get('distance'),rate:get('rate'),trips:get('trips'),years:get('years'),baseline_price:get('baseline-price')}
    };
  }
  function updateRoi(){
    $('roi-fields').hidden=!checked('show-roi');
    if(!checked('show-roi'))return;
    const value=number('extra-payload')*number('distance')*number('rate')*number('trips');
    const years=number('years');
    const delta=number('price')-number('baseline-price');
    $('roi-preview').textContent=`Дополнительная выручка за год: ${money(value)}. Условный баланс за ${fmt(years)} лет после разницы в цене: ${money(value*years-delta)}.`;
  }
  function setStatus(title,message,state=''){
    const banner=$('modebanner');
    banner.classList.toggle('is-working',state==='working');
    banner.classList.toggle('is-done',state==='done');
    banner.querySelector('strong').textContent=title;
    banner.querySelector('small').textContent=message;
  }
  function showError(message,focusId){
    $('error-box').hidden=false;
    $('error-box').textContent=message;
    $('error-box').scrollIntoView({behavior:'smooth',block:'start'});
    if(focusId) $(focusId).focus({preventScroll:true});
    else $('error-box').focus({preventScroll:true});
  }
  function clearError(){$('error-box').hidden=true;$('error-box').textContent='';}
  async function readError(response){
    try {const json=await response.json();return typeof json.detail==='string'?json.detail:`Ошибка HTTP ${response.status}`;}
    catch {return `Ошибка HTTP ${response.status}. Проверьте соединение.`;}
  }
  function invalidateResult(){
    if(isBusy||!latest)return;
    latest=null;
    $('download-panel').hidden=true;
    ['download-all','download-4x3','download-9x16','download-jpeg-4x3','download-jpeg-9x16','download-svg-4x3','download-svg-9x16'].forEach(id=>$(id).disabled=true);
    setStatus('Параметры изменены','Создайте новый комплект, чтобы применить изменения.');
  }
  function updateFileLabels(){
    const heroFiles=Array.from($('hero').files);
    const hero=heroFiles[0];
    $('hero-label').textContent=heroFiles.length>1?`${heroFiles.length} фотографий товара`:hero?(hero.name.length>45?hero.name.slice(0,42)+'…':hero.name):'Добавить фотографии товара';
    $('hero-hint').textContent=hero?'Можно добавить ещё фотографии':'Перетащите несколько фото или выберите файлы';
    $('hero-drop').classList.toggle('has-file',Boolean(hero));
    $('clear-hero').hidden=!hero;
    for(const id of fileIds.filter(v=>v!=='hero')){
      const count=$(id).files.length;
      $('file-'+id).textContent=count===1?$(id).files[0].name:count>1?`${count} файла(ов)`:placeholders[id];
      $(id).closest('.mini-upload').classList.toggle('has-file',Boolean(count));
      const clear=$('clear-'+id)||document.querySelector(`[data-clear="${id}"]`);
      if(clear)clear.hidden=!count;
    }
    $('inspect-btn').disabled=isBusy||!$('documents').files.length;
    $('inspect-btn').hidden=!$('documents').files.length;
    const count=fileIds.reduce((total,id)=>total+$(id).files.length,0);
    $('file-feedback').textContent=count?`Прикреплено файлов: ${count}. Лучшие материалы будут выбраны после анализа; не все войдут в промо.`:'Фото и логотипы встраиваются в SVG-исходники ZIP.';
  }
  function refreshStyle(){
    document.querySelectorAll('[data-style]').forEach(button=>{
      const active=button.dataset.style===get('style');
      button.classList.toggle('is-active',active);
      button.setAttribute('aria-pressed',String(active));
    });
  }
  function updateAi(){
    $('ai-description').textContent=apiReady?'Два платных запроса за комплект':'На сервере не настроен API-ключ';
    $('use-openai').disabled=!apiReady;
    $('use-openai').closest('.ai-choice').classList.toggle('is-disabled',!apiReady);
    if(!isBusy){
      if(checked('use-openai'))setStatus('OpenAI включён','Два платных запроса для 4:3 и 9:16.');
      else setStatus('Без расходов на API','Обычная сборка изображений.');
    }
  }
  function validateFiles(){
    const all=fileIds.flatMap(id=>Array.from($(id).files));
    if(all.length>16)return 'Слишком много вложений: не более 16 файлов за один комплект.';
    // Можно загрузить несколько референсов: только два будут выбраны.
    if(all.some(file=>file.size>20*1024*1024))return 'Один из файлов больше 20 МБ. Уменьшите его размер.';
    if(all.reduce((sum,file)=>sum+file.size,0)>68*1024*1024)return 'Общий размер вложений не должен превышать 68 МБ.';
    return window.PromoAssets?.validate()||'';
  }
  function busy(on){
    isBusy=on;
    $('generate-btn').disabled=on;
    $('build-prompt-btn').disabled=on;
    $('analyze-assets-btn').disabled=on;
    $('asset-rebuild').disabled=on;
    $('reset-btn').disabled=on;
    $('inspect-btn').disabled=on||!$('documents').files.length;
    $('loading').hidden=!on;
    const button=$('generate-btn');
    if(on)button.textContent='Создаём изображения…';
    else button.textContent='Создать PNG · JPEG · SVG →';
  }
  function appendFiles(form,id){for(const file of $(id).files)form.append(id,file,file.name);}
  function download(path){
    if(!path)return;
    const link=document.createElement('a');
    link.href=path;link.download=path.split('/').pop();document.body.appendChild(link);link.click();link.remove();
  }
  function markPromptStale(){
    promptDirty=true;
    $('promo-prompt-status').classList.add('is-stale');
    $('promo-prompt-status').textContent='Поля изменились. Сформируйте промпт заново, чтобы учесть актуальные данные.';
  }
  async function buildPrompt(){
    if(!get('model').trim())throw new Error('Сначала укажите модель товара.');
    const response=await fetch('/api/prompt',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...formBrief(),asset_report:window.PromoAssets?.getReport()||null})
    });
    if(!response.ok)throw new Error(await readError(response));
    const result=await response.json();
    $('promo-prompt').value=result.prompt;
    promptDirty=false;
    $('promo-prompt-status').classList.remove('is-stale');
    $('promo-prompt-status').textContent='Промпт собран из формы бесплатно. Можно дополнить его своими словами.';
    return result.prompt;
  }

  async function generate(){
    clearError();
    if(!get('model').trim()){
      showError('Укажите название или модель товара — это нужно для заголовка промо-листа.','model');return;
    }
    const invalid=validateFiles();if(invalid){showError(invalid);return;}
    if(window.PromoAssets?.hasFiles()&&!window.PromoAssets.isReady()){
      showError('Сначала нажмите «Проанализировать материалы», проверьте выбор и при необходимости измените приоритеты.');return;
    }
    if(checked('use-openai')&&!apiReady){showError('OpenAI не подключён на сервере. Используйте обычную сборку или настройте ключ в VPS.');return;}
    if(!checked('use-openai')&&!$('hero').files.length&&!$('detail').files.length&&!checked('use-demo')){
      showError('Сначала добавьте фото товара или нажмите «Заполнить пример» для пробного комплекта.');return;
    }
    invalidateResult();busy(true);
    setStatus('Создаём промо','Генерируем два SVG-исходника, PNG и JPEG.','working');
    try {
      const prompt=(promptDirty||!get('promo-prompt').trim())?await buildPrompt():get('promo-prompt').trim();
      const form=new FormData();form.append('payload',JSON.stringify(formBrief()));
      form.append('prompt',prompt);
      if(window.PromoAssets)window.PromoAssets.append(form);
      else fileIds.forEach(id=>appendFiles(form,id));
      form.append('use_openai',String(checked('use-openai')));
      form.append('use_demo',String(checked('use-demo')));
      form.append('model',get('image-model'));
      form.append('quality',get('image-quality'));
      const response=await fetch('/api/generate',{method:'POST',body:form});
      if(!response.ok)throw new Error(await readError(response));
      latest=await response.json();
      const gaps=(latest.warnings||[]).filter(w=>/ТТХ|Габариты|Цена не указана/.test(w)).slice(0,4);
      $('result-warnings').hidden=!gaps.length;
      $('result-warning-items').replaceChildren();
      for(const message of gaps){
        const item=document.createElement('li');item.textContent=message;
        $('result-warning-items').appendChild(item);
      }
      window.dispatchEvent(new CustomEvent('promoeditor:generated',{detail:latest}));
      $('download-panel').hidden=false;
      ['download-all','download-4x3','download-9x16','download-jpeg-4x3','download-jpeg-9x16','download-svg-4x3','download-svg-9x16'].forEach(id=>$(id).disabled=false);
      setStatus('Готово','PNG, JPEG, CorelDRAW SVG и ZIP готовы.','done');
      $('download-panel').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){
      setStatus('Не удалось создать файлы','Исправьте ошибку и повторите попытку.');
      showError(error.message||'Не удалось завершить генерацию.');
    }finally{busy(false);}
  }
  async function inspect(){
    clearError();
    if(!$('documents').files.length){showError('Сначала приложите документы с характеристиками.');return;}
    const invalid=validateFiles();if(invalid){showError(invalid);return;}
    if(checked('parse-ai')&&!apiReady){showError('OpenAI недоступен. Выключите платный анализ документов.');return;}
    $('inspect-btn').disabled=true;$('inspect-btn').textContent='Извлекаем характеристики…';
    try {
      const form=new FormData();appendFiles(form,'documents');
      form.append('use_ai',String(checked('parse-ai')));
      form.append('requirements',get('design-notes'));
      const response=await fetch('/api/inspect',{method:'POST',body:form});
      if(!response.ok)throw new Error(await readError(response));
      const result=await response.json();
      const ai=result.ai_suggestions;
      const pairsFound=ai&&Array.isArray(ai.specs)?ai.specs.map(v=>[v.label,v.value]).filter(p=>p[0]&&p[1]):result.suggested_specs||[];
      $('extract-result').value=asLines(pairsFound);
      $('extract-summary').textContent=`Обработано: ${(result.files||[]).map(v=>v.file).join(', ')}. ${[...(result.warnings||[]),...(ai?.warnings||[])].join(' ')}`;
      $('advanced-settings').open=true;
      $('extract-box').hidden=false;
      $('extract-box').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){showError(error.message||'Ошибка при извлечении данных.');}
    finally{$('inspect-btn').textContent='Извлечь характеристики из документов →';$('inspect-btn').disabled=isBusy||!$('documents').files.length;}
  }
  function fillBrief(data){
    for(const id of ['brand','model','category','slogan','price','currency','style','accent'])set(id,data[id]);
    set('claims',asLines(data.hero_claims));set('specs',asLines(data.specs));set('benefits',asLines(data.benefits));set('dimensions',asLines(data.dimensions));set('phones',asLines(data.phones));set('design-notes',data.design_notes);set('design-actions',data.design_actions);
    $('vat').checked=Boolean(data.vat);$('show-roi').checked=Boolean(data.show_roi);
    const roi=data.roi||{};
    for(const [id,key] of [['extra-payload','extra_payload'],['distance','distance'],['rate','rate'],['trips','trips'],['years','years'],['baseline-price','baseline_price']])set(id,roi[key]??'');
    $('color-label').textContent=get('accent').toUpperCase();
    markPromptStale();
    updateRoi();refreshStyle();
  }
  function clearForm(){
    for(const id of ['brand','model','category','slogan','design-notes','design-actions','claims','specs','benefits','dimensions','price','phones','promo-prompt'])set(id,'');
    markPromptStale();
    set('currency','Br');set('style','industrial');set('accent','#e31b26');
    $('vat').checked=true;$('show-roi').checked=false;$('use-openai').checked=false;$('use-demo').checked=false;$('parse-ai').checked=false;
    for(const id of fileIds)$(id).value='';
    window.PromoAssets?.reset();
    $('extract-box').hidden=true;
    $('advanced-settings').open=false;
    $('color-label').textContent='#E31B26';
    hasDemo=false;
    $('reset-btn').textContent='Заполнить пример';
    latest=null;$('download-panel').hidden=true;
    ['download-all','download-4x3','download-9x16','download-jpeg-4x3','download-jpeg-9x16','download-svg-4x3','download-svg-9x16'].forEach(id=>$(id).disabled=true);
    clearError();updateRoi();refreshStyle();updateFileLabels();updateAi();
  }
  async function resetDemo(){
    if(hasDemo){clearForm();return;}
    clearError();
    try {
      const response=await fetch('/api/demo');if(!response.ok)throw new Error('Пример временно недоступен.');
      const result=await response.json();fillBrief(result.brief);
      for(const id of fileIds)$(id).value='';
      window.PromoAssets?.reset();
      $('use-openai').checked=false;$('use-demo').checked=true;$('parse-ai').checked=false;
      $('advanced-settings').open=false;
      $('extract-box').hidden=true;
      hasDemo=true;
      $('reset-btn').textContent='Очистить форму';
      latest=null;$('download-panel').hidden=true;
      ['download-all','download-4x3','download-9x16','download-jpeg-4x3','download-jpeg-9x16','download-svg-4x3','download-svg-9x16'].forEach(id=>$(id).disabled=true);
      markPromptStale();
      updateAi();updateFileLabels();updateRoi();refreshStyle();
      setStatus('Пример заполнен','Создайте комплект без расходов на API.');
      $('model').focus({preventScroll:true});
      window.scrollTo({top:0,behavior:'smooth'});
    }catch(error){showError(error.message||'Не удалось загрузить пример.');}
  }
  async function init(){
    try {
      const response=await fetch('/api/config');if(!response.ok)throw new Error('API недоступен');
      const config=await response.json();apiReady=Boolean(config.openai_ready);
      window.PromoAssets?.setAiReady(apiReady);
      $('logout-form').hidden=!config.auth_enabled;
      $('logout-csrf').value=config.logout_csrf_token||'';
      $('api-dot').classList.toggle('good',apiReady);
      $('api-state').textContent=apiReady?'OpenAI подключён':'Без OpenAI';
    }catch{
      $('api-state').textContent='Сервер недоступен';
    }
    updateAi();refreshStyle();updateFileLabels();updateRoi();
  }

  for(const id of fileIds){
    $(id).addEventListener('change',()=>{updateFileLabels();markPromptStale();invalidateResult();clearError();});
  }
  for(const id of ['hero','documents','logo']){
    $('clear-'+id).addEventListener('click',()=>{$(id).value='';$(id).dispatchEvent(new Event('change',{bubbles:true}));});
  }
  document.querySelectorAll('[data-clear]').forEach(button=>{
    button.addEventListener('click',()=>{const id=button.dataset.clear;$(id).value='';$(id).dispatchEvent(new Event('change',{bubbles:true}));});
  });
  for(const id of briefIds){
    $(id).addEventListener('input',()=>{
      if(id==='accent')$('color-label').textContent=get('accent').toUpperCase();
      if(['show-roi','price','currency','extra-payload','distance','rate','trips','years','baseline-price'].includes(id))updateRoi();
      markPromptStale();
      invalidateResult();
    });
    $(id).addEventListener('change',()=>{markPromptStale();invalidateResult();});
  }
  document.querySelectorAll('[data-style]').forEach(button=>button.addEventListener('click',()=>{
    set('style',button.dataset.style);
    const accents={industrial:'#e31b26',graphite:'#344054',minimal:'#315ddc'};
    set('accent',accents[button.dataset.style]);$('color-label').textContent=get('accent').toUpperCase();
    refreshStyle();markPromptStale();invalidateResult();
  }));
  $('use-openai').addEventListener('change',()=>{if(checked('use-openai')&&!apiReady){$('use-openai').checked=false;showError('OpenAI пока не подключён. Добавьте API-ключ на сервере.');}updateAi();invalidateResult();});
  $('show-roi').addEventListener('change',updateRoi);
  $('hero-drop').addEventListener('dragover',event=>{event.preventDefault();$('hero-drop').classList.add('is-dragging');});
  $('hero-drop').addEventListener('dragleave',event=>{if(!$('hero-drop').contains(event.relatedTarget))$('hero-drop').classList.remove('is-dragging');});
  $('hero-drop').addEventListener('drop',event=>{
    event.preventDefault();$('hero-drop').classList.remove('is-dragging');
    const files=Array.from(event.dataTransfer?.files||[]);
    if(!files.length||files.some(f=>!/\.(png|jpe?g|webp)$/i.test(f.name))){
      showError('Перетащите только PNG, JPG или WEBP. Документы загружайте отдельно.');return;
    }
    if(files.some(f=>f.size>20*1024*1024)){showError('Каждое фото должно быть не больше 20 МБ.');return;}
    const transfer=new DataTransfer();
    for(const file of files)transfer.items.add(file);
    $('hero').files=transfer.files;
    $('hero').dispatchEvent(new Event('change',{bubbles:true}));
  });
  $('analyze-assets-btn').addEventListener('click',async()=>{
    clearError();
    try {
      const report=await window.PromoAssets.analyze(formBrief());
      if(report){markPromptStale();invalidateResult();}
    }catch(error){showError(error.message||'Не удалось проверить материалы.');}
  });
  $('asset-rebuild').addEventListener('click',async()=>{
    clearError();
    try {
      // Content-matched earlier AI assessments can be reused without a paid call.
      const report=await window.PromoAssets.analyze(formBrief(),{freeOnly:true});
      if(report){markPromptStale();invalidateResult();}
    }catch(error){showError(error.message||'Не удалось пересобрать выбор.');}
  });
  $('asset-apply-specs').addEventListener('click',()=>{
    const entries=window.PromoAssets?.extractedSpecs()||[];
    if(!entries.length){showError('Нет предложенных характеристик.');return;}
    if(!window.confirm('Перенести данные из документов в поля ТТХ? Проверьте все значения и источники перед публикацией.'))return;
    const old=pairs('specs');
    const used=new Set(old.map(row=>row[0].toLowerCase()+'|'+row[1].toLowerCase()));
    const combined=[...old];
    for(const entry of entries){
      const key=(entry.label+'|'+entry.value).toLowerCase();
      if(entry.label&&entry.value&&!used.has(key)&&combined.length<12){
        combined.push([entry.label,entry.value]);used.add(key);
      }
    }
    set('specs',asLines(combined));
    $('advanced-settings').open=true;
    markPromptStale();invalidateResult();
    setStatus('ТТХ перенесены','Проверьте каждую характеристику по источникам перед публикацией.');
    $('specs').scrollIntoView({behavior:'smooth',block:'center'});
  });
  $('asset-apply-extra-facts').addEventListener('click',()=>{
    const facts=window.PromoAssets?.extraFacts();
    if(!facts){showError('Нет других предложений из документов.');return;}
    if(!window.confirm('Перенести предложенные модель, цену, телефоны и другие сведения? Данные AI не проверены; заполненные вручную поля не будут перезаписаны.'))return;
    const values={model:'model',category:'category',slogan:'slogan',price:'price'};
    let count=0;
    for(const [key,id] of Object.entries(values)){
      if(facts[key]&&!get(id).trim()){set(id,facts[key]);count++;}
    }
    for(const [key,id] of [['phones','phones'],['benefits','benefits']]){
      if(Array.isArray(facts[key])&&facts[key].length&&!get(id).trim()){
        set(id,asLines(facts[key]));count++;
      }
    }
    if(Array.isArray(facts.dimensions)&&facts.dimensions.length&&!get('dimensions').trim()){
      set('dimensions',asLines(facts.dimensions.map(row=>[row.label,row.value])));count++;
    }
    $('advanced-settings').open=true;
    markPromptStale();invalidateResult();
    setStatus('Предложения перенесены',count?
      'Перенесено незаполненных полей: '+count+'. Проверьте каждый факт.':
      'Заполненные поля не изменены. При необходимости отредактируйте их вручную.');
  });
  window.addEventListener('promoeditor:assets-changed',()=>{
    markPromptStale();invalidateResult();clearError();
  });
  $('build-prompt-btn').addEventListener('click',async()=>{
    clearError();
    $('build-prompt-btn').disabled=true;
    $('build-prompt-btn').textContent='Формируем промпт…';
    try{await buildPrompt();}
    catch(error){showError(error.message||'Не удалось сформировать промпт.');}
    finally{$('build-prompt-btn').disabled=isBusy;$('build-prompt-btn').textContent='Сформировать промпт ↻';}
  });
  $('promo-prompt').addEventListener('input',()=>{
    promptDirty=false;
    $('promo-prompt-status').classList.remove('is-stale');
    $('promo-prompt-status').textContent='Промпт изменён вручную. Он будет отправлен для AI-сцены и сохранён в ZIP.';
    invalidateResult();
  });
  $('reset-btn').addEventListener('click',resetDemo);
  $('generate-btn').addEventListener('click',generate);
  $('inspect-btn').addEventListener('click',inspect);
  $('apply-extracted').addEventListener('click',()=>{
    const values=$('extract-result').value.trim();
    if(!values){showError('Нет характеристик для переноса.');return;}
    set('specs',values);$('advanced-settings').open=true;$('extract-box').hidden=true;
    markPromptStale();invalidateResult();setStatus('ТТХ перенесены','Проверьте каждую характеристику до публикации.');
    $('specs').scrollIntoView({behavior:'smooth',block:'center'});
  });
  $('download-all').addEventListener('click',()=>download(latest?.zip));
  $('download-4x3').addEventListener('click',()=>download(latest?.images?.['4x3']));
  $('download-9x16').addEventListener('click',()=>download(latest?.images?.['9x16']));
  $('download-jpeg-4x3').addEventListener('click',()=>download(latest?.jpeg?.['4x3']));
  $('download-jpeg-9x16').addEventListener('click',()=>download(latest?.jpeg?.['9x16']));
  $('download-svg-4x3').addEventListener('click',()=>download(latest?.corel?.['4x3']));
  $('download-svg-9x16').addEventListener('click',()=>download(latest?.corel?.['9x16']));
  init();
})();
