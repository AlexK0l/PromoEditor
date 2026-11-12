(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const inputs = ['hero','detail','logo','drawing','documents','references'];
  const briefControls = ['brand','model','category','slogan','claims','design-notes','specs','benefits','dimensions','price','currency','vat','phones','show-roi','extra-payload','distance','rate','trips','years','baseline-price','style','accent','use-openai','image-model','image-quality','use-demo'];
  let latest = null;
  let apiReady = false;
  let isBusy = false;

  const get = id => $(id).value;
  const checked = id => $(id).checked;
  const set = (id, val) => { $(id).value = val ?? ''; };
  const lines = id => get(id).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  const asLines = rows => (rows || []).map(x=>Array.isArray(x)?x.join(' | '):x).join('\n');
  const pairs = id => lines(id).map(line => {
    const sep = line.includes('|')?'|':line.includes('\t')?'\t':line.includes(' = ')?' = ':' : ';
    const i = line.indexOf(sep);
    if (i === -1) return null;
    const a = line.slice(0,i).trim(), b = line.slice(i+sep.length).trim();
    return a && b ? [a,b] : null;
  }).filter(Boolean);
  const number = id => Number(String(get(id)).replace(/\s/g,'').replace(',','.')) || 0;
  const fmt = n => Number.isFinite(n)?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(n):'—';
  const money = n => `${fmt(n)} ${get('currency')}`;

  function updateRoi() {
    $('roi-fields').hidden = !checked('show-roi');
    if (!checked('show-roi')) return;
    const p=number('extra-payload'), km=number('distance'), r=number('rate'), trips=number('trips'), y=number('years');
    const delta=number('price')-number('baseline-price');
    $('roi-preview').textContent=`Дополнительная выручка за год: ${money(p*km*r*trips)} · Баланс за ${fmt(y)} лет после разницы в цене: ${money(p*km*r*trips*y-delta)}.`;
  }
  function formBrief() {
    return {
      brand:get('brand').trim(),model:get('model').trim(),category:get('category').trim(),
      slogan:get('slogan').trim(),design_notes:get('design-notes').trim(),
      style:get('style'),accent:get('accent'),
      hero_claims:lines('claims').slice(0,4),specs:pairs('specs'),benefits:lines('benefits'),dimensions:pairs('dimensions'),
      price:get('price').trim(),currency:get('currency'),vat:checked('vat'),phones:lines('phones').slice(0,2),
      show_roi:checked('show-roi'),roi:{extra_payload:get('extra-payload'),distance:get('distance'),rate:get('rate'),trips:get('trips'),years:get('years'),baseline_price:get('baseline-price')}
    };
  }
  function updateReady() {
    const states = {'ready-photo': $('hero').files.length>0 || checked('use-demo') || checked('use-openai'),
      'ready-name':Boolean(get('model').trim()||get('brand').trim()||get('category').trim()),
      'ready-message':Boolean(get('slogan').trim())};
    Object.entries(states).forEach(([id,done])=>{$(id).classList.toggle('done',done);$(id).textContent=done?'✓':'○';});
  }
  function refreshStyle() {
    document.querySelectorAll('[data-style]').forEach(button=>{
      const selected = button.dataset.style === get('style');
      button.classList.toggle('is-selected',selected);
      button.setAttribute('aria-pressed',String(selected));
    });
  }
  function updateFileLabels() {
    const photo=$('hero').files[0];
    $('hero-label').textContent=photo?photo.name:'Перетащите фото сюда';
    $('hero-drop').classList.toggle('has-file',Boolean(photo));
    $('clear-hero').hidden=!photo;
    const placeholder={documents:'PDF, Word, Excel и текст',logo:'Добавить логотип',detail:'Другой ракурс',drawing:'Изображение или PDF',references:'До двух изображений для OpenAI'};
    for (const id of ['documents','logo','detail','drawing','references']) {
      const f=Array.from($(id).files);
      $('file-'+id).textContent=f.length === 1?f[0].name:f.length>1?`${f.length} файлов выбрано`:placeholder[id];
      $(id).closest('.attachment').classList.toggle('has-file',f.length>0);
      if (['documents','logo'].includes(id)) $('clear-'+id).hidden=!f.length;
    }
    $('inspect-btn').disabled=isBusy || !$('documents').files.length;
    updateReady();
  }
  function setStatus(title,subtitle,type='') {
    const banner=$('modebanner');
    banner.classList.toggle('is-working',type==='working');
    banner.classList.toggle('is-done',type==='done');
    banner.querySelector('b').textContent=title;
    banner.querySelector('small').textContent=subtitle;
  }
  function updateAi() {
    $('ai-options').hidden=!checked('use-openai');
    $('ai-description').textContent=apiReady?'AI-фон и атмосфера, 2 платных запроса за комплект':'OpenAI не подключён на сервере. Можно создавать без API.';
    if (!isBusy) {
      if (checked('use-openai')) setStatus('OpenAI включён','На каждый комплект будет два платных вызова API.');
      else setStatus('Без платных запросов','Локальная генерация PNG доступна без OpenAI.');
    }
    updateReady();
  }
  function showError(text, target=null) {
    $('error-box').hidden=false;
    $('error-box').textContent=text;
    $('error-box').scrollIntoView({behavior:'smooth',block:'center'});
    if (target) { $(target).focus({preventScroll:true}); }
    else $('error-box').focus({preventScroll:true});
  }
  function clearError() { $('error-box').hidden=true;$('error-box').textContent=''; }
  async function readError(resp) {
    try { const j=await resp.json();return typeof j.detail==='string'?j.detail:`Ошибка HTTP ${resp.status}`; }
    catch {return `Не удалось выполнить запрос (HTTP ${resp.status}).`;}
  }
  function markEdited() {
    if (isBusy || !latest) return;
    latest=null;
    $('download-panel').hidden=true;
    ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
    setStatus('Данные изменены','Нажмите «Создать оба формата», чтобы получить обновлённые файлы.');
  }
  function busy(active) {
    isBusy=active;
    $('generate-btn').disabled=active;
    $('reset-btn').disabled=active;
    $('inspect-btn').disabled=active||!$('documents').files.length;
    $('loading').hidden=!active;
    if (active) $('generate-btn').textContent='Создаём…';
    else $('generate-btn').innerHTML='<span aria-hidden="true">✦</span> Создать оба формата';
  }
  function appendFiles(fd,id) { for(const f of $(id).files) fd.append(id,f,f.name); }
  function validateFiles() {
    const all=inputs.flatMap(id=>Array.from($(id).files));
    if (all.length>16) return 'Загрузите не более 16 файлов за раз.';
    if ($('references').files.length>2) return 'Для референсов выберите не более двух изображений.';
    if (all.some(f=>f.size>20*1024*1024)) return 'Каждый файл должен быть не больше 20 МБ.';
    if (all.reduce((s,f)=>s+f.size,0)>68*1024*1024) return 'Суммарный объём файлов должен быть не больше 68 МБ.';
    return null;
  }
  function download(path) {
    if (!path) return;
    const a=document.createElement('a');a.href=path;a.download=path.split('/').pop();document.body.appendChild(a);a.click();a.remove();
  }
  async function generate() {
    clearError();
    const brief=formBrief();
    if (!brief.brand && !brief.model && !brief.category) {
      showError('Укажите хотя бы название, бренд или тип продукта — так мы поймём, что рекламируем.','model');return;
    }
    const fileError=validateFiles();if(fileError){showError(fileError);return;}
    if (checked('use-openai')&&!apiReady) {showError('На сервере пока не настроен OpenAI API. Выключите OpenAI или добавьте ключ на VPS.');return;}
    if (!checked('use-openai')&&!$('hero').files.length&&!checked('use-demo')) {
      showError('Добавьте главное фото или включите демонстрационную иллюстрацию в расширенных настройках.');return;
    }
    markEdited();busy(true);
    setStatus('Собираем материалы','Готовим два независимых PNG для публикации.','working');
    try {
      const fd=new FormData();fd.append('payload',JSON.stringify(brief));
      inputs.forEach(id=>appendFiles(fd,id));
      fd.append('use_openai',String(checked('use-openai')));
      fd.append('use_demo',String(checked('use-demo')));
      fd.append('model',get('image-model'));fd.append('quality',get('image-quality'));
      const resp=await fetch('/api/generate',{method:'POST',body:fd});
      if(!resp.ok)throw new Error(await readError(resp));
      latest=await resp.json();
      $('download-panel').hidden=false;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=false);
      setStatus('Оба формата готовы', 'PNG 4:3, PNG 9:16 и ZIP-комплект. Не забудьте проверить данные.', 'done');
      $('download-panel').scrollIntoView({behavior:'smooth',block:'center'});
    }catch(e){setStatus('Генерация не завершена','Попробуйте ещё раз после исправления ошибки.');showError(e.message||'Не получилось создать изображения.');}
    finally{busy(false);}
  }
  async function inspect() {
    clearError();
    if (!$('documents').files.length) {showError('Сначала прикрепите документы с характеристиками.');return;}
    const fileError=validateFiles();if(fileError){showError(fileError);return;}
    $('inspect-btn').disabled=true;$('inspect-btn').textContent='Извлекаем…';
    try {
      const fd=new FormData();appendFiles(fd,'documents');
      fd.append('use_ai',String(checked('parse-ai')));fd.append('requirements',get('design-notes'));
      const resp=await fetch('/api/inspect',{method:'POST',body:fd});
      if(!resp.ok)throw new Error(await readError(resp));
      const result=await resp.json(), ai=result.ai_suggestions;
      const extracted=ai&&Array.isArray(ai.specs)?ai.specs.map(v=>[v.label,v.value]).filter(p=>p[0]&&p[1]):result.suggested_specs||[];
      $('extract-result').value=asLines(extracted);
      const warn=[...(result.warnings||[]),...(ai?.warnings||[])].join(' ');
      $('extract-summary').textContent=`Прочитано: ${(result.files||[]).map(v=>v.file).join(', ')}. ${warn}`;
      $('extract-box').hidden=false;
      $('extract-box').scrollIntoView({behavior:'smooth',block:'center'});
    }catch(e){showError(e.message||'Не удалось прочитать документы.');}
    finally{$('inspect-btn').textContent='Извлечь данные';$('inspect-btn').disabled=isBusy||!$('documents').files.length;}
  }
  function fillBrief(b) {
    for (const id of ['brand','model','category','slogan','price','currency','style','accent']) set(id,b[id]);
    set('claims',asLines(b.hero_claims));set('specs',asLines(b.specs));set('benefits',asLines(b.benefits));
    set('dimensions',asLines(b.dimensions));set('phones',asLines(b.phones));set('design-notes',b.design_notes);
    $('vat').checked=Boolean(b.vat);$('show-roi').checked=Boolean(b.show_roi);
    const roi=b.roi||{};for(const [id,key] of [['extra-payload','extra_payload'],['distance','distance'],['rate','rate'],['trips','trips'],['years','years'],['baseline-price','baseline_price']]) set(id,roi[key]??'');
    $('color-label').textContent=String(b.accent||'#E31B26').toUpperCase();
    refreshStyle();updateRoi();updateReady();
  }
  async function resetDemo() {
    clearError();
    try {
      const resp=await fetch('/api/demo');if(!resp.ok)throw new Error('Демонстрационный бриф недоступен');
      const data=await resp.json();fillBrief(data.brief);
      $('advanced-settings').open=true;
      $('use-openai').checked=false;$('parse-ai').checked=false;$('use-demo').checked=true;
      for(const id of inputs) $(id).value='';
      $('extract-box').hidden=true;latest=null;
      $('download-panel').hidden=true;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
      updateAi();updateFileLabels();updateRoi();
      setStatus('Пример заполнен','Замените данные своими или создайте тестовый комплект без OpenAI.');
      $('media-title').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){showError(e.message||'Не удалось загрузить пример.');}
  }
  async function init() {
    try {
      const r=await fetch('/api/config');if(!r.ok)throw new Error('offline');
      const config=await r.json();apiReady=Boolean(config.openai_ready);
      $('api-dot').classList.toggle('good',apiReady);
      $('api-state').textContent=apiReady?'OpenAI доступен':'Без OpenAI';
    }catch{$('api-state').textContent='Нет связи с сервером';}
    refreshStyle();updateFileLabels();updateRoi();updateAi();updateReady();
  }
  for (const id of ['hero','documents','logo']) {
    $('clear-'+id).addEventListener('click',()=>{$(id).value='';$(id).dispatchEvent(new Event('change',{bubbles:true}));});
  }
  for (const id of inputs) {
    $(id).addEventListener('change',()=>{updateFileLabels();markEdited();clearError();});
  }
  for (const id of briefControls) {
    $(id).addEventListener('input',()=>{if(id==='accent')$('color-label').textContent=get('accent').toUpperCase();if(['price','currency','show-roi','extra-payload','distance','rate','trips','years','baseline-price'].includes(id))updateRoi();updateReady();markEdited();});
    $(id).addEventListener('change',()=>{updateReady();markEdited();});
  }
  document.querySelectorAll('[data-style]').forEach(b=>b.addEventListener('click',()=>{set('style',b.dataset.style);refreshStyle();markEdited();}));
  $('use-openai').addEventListener('change',()=>{
    if(checked('use-openai')&&!apiReady){$('use-openai').checked=false;showError('OpenAI API ещё не подключён. Пока можно создавать изображения без API-ключа.');}
    updateAi();markEdited();
  });
  $('hero-drop').addEventListener('dragover',e=>{e.preventDefault();$('hero-drop').classList.add('is-dragging');});
  $('hero-drop').addEventListener('dragleave',e=>{if(!$('hero-drop').contains(e.relatedTarget))$('hero-drop').classList.remove('is-dragging');});
  $('hero-drop').addEventListener('drop',e=>{
    e.preventDefault();$('hero-drop').classList.remove('is-dragging');
    const files=Array.from(e.dataTransfer?.files||[]), image=files.find(f=>/\.(png|jpe?g|webp)$/i.test(f.name));
    if(!image){showError('Сюда можно перетащить изображение PNG, JPG или WEBP. Для документов используйте кнопку ниже.');return;}
    if(image.size>20*1024*1024){showError('Главное фото должно быть не больше 20 МБ.');return;}
    const transfer=new DataTransfer();transfer.items.add(image);$('hero').files=transfer.files;
    $('hero').dispatchEvent(new Event('change',{bubbles:true}));
  });
  $('generate-btn').addEventListener('click',generate);
  $('reset-btn').addEventListener('click',resetDemo);
  $('inspect-btn').addEventListener('click',inspect);
  $('apply-extracted').addEventListener('click',()=>{
    const text=$('extract-result').value.trim();if(!text){showError('Нет характеристик для переноса.');return;}
    set('specs',text);$('advanced-settings').open=true;$('extract-box').hidden=true;
    markEdited();updateReady();
    setStatus('Характеристики добавлены','Проверьте значения в расширенных настройках перед созданием макета.');
    $('specs').scrollIntoView({behavior:'smooth',block:'center'});
  });
  $('download-all').addEventListener('click',()=>download(latest?.zip));
  $('download-4x3').addEventListener('click',()=>download(latest?.images?.['4x3']));
  $('download-9x16').addEventListener('click',()=>download(latest?.images?.['9x16']));
  init();
})();
