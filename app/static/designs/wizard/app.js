(() => {
  const $ = id => document.getElementById(id);
  let latest = null;
  let extractedPairs = [];
  let apiReady = false;
  let currentStep = 1;
  let isBusy = false;
  const stepCount = 3;
  function setStep(next, {moveFocus = true} = {}) {
    if (isBusy) return;
    currentStep = Math.min(stepCount, Math.max(1, next));
    for (let i=1; i<=stepCount; i++) {
      $('step-'+i).hidden = i !== currentStep;
    }
    document.querySelectorAll('[data-go-step]').forEach(button => {
      const n = Number(button.dataset.goStep);
      button.classList.toggle('is-active', n === currentStep);
      button.classList.toggle('is-done', n < currentStep);
      if (n === currentStep) button.setAttribute('aria-current','step');
      else button.removeAttribute('aria-current');
    });
    $('progress-fill').style.width = (currentStep / stepCount * 100) + '%';
    $('back-btn').hidden = currentStep === 1;
    $('next-btn').hidden = currentStep === stepCount;
    $('generate-btn').hidden = currentStep !== stepCount;
    $('step-counter').textContent = `Шаг ${currentStep} из ${stepCount}`;
    clearError();
    if (moveFocus) {
      const h = $('title-step-'+currentStep);
      h.setAttribute('tabindex','-1');
      h.focus({preventScroll:true});
      document.querySelector('.editor').scrollIntoView({behavior:'smooth', block:'start'});
    }
  }
  function updateFileLabels() {
    for (const id of ['hero','detail','logo','drawing']) {
      const input = $(id);
      const file = input.files[0];
      $('file-'+id).textContent = file ? file.name : 'Выбрать файл';
      input.closest('.upload-card').classList.toggle('has-file',Boolean(file));
    }
    for (const id of ['documents','references']) {
      const count=$(id).files.length;
      $('file-'+id).textContent=count ? `${count} файл(ов) выбрано` : 'Файлы не выбраны';
    }
    $('inspect-btn').disabled = !$('documents').files.length;
  }
  function setBanner(title,description,variant='') {
    const el=$('modebanner');
    el.classList.toggle('is-working',variant==='working');
    el.classList.toggle('is-done',variant==='done');
    el.querySelector('b').textContent=title;
    el.querySelector('small').textContent=description;
  }
  function updateAiOptions() {
    $('ai-options').hidden = !checked('use-openai');
  }
  const get = id => $(id).value;
  const checked = id => $(id).checked;
  const set = (id,value) => { $(id).value = value ?? ''; };
  const lines = id => get(id).split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  const pairs = id => lines(id).map(line => {
    const sep = line.includes('|') ? '|' : line.includes('\t') ? '\t' : line.includes(' = ') ? ' = ' : ' : ';
    const i = line.indexOf(sep);
    if (i < 0) return null;
    const a = line.slice(0,i).trim(), b = line.slice(i+sep.length).trim();
    return a && b ? [a,b] : null;
  }).filter(Boolean);
  const asLines = arr => (arr || []).map(x => Array.isArray(x) ? x.join(' | ') : x).join('\n');
  const fmt = num => Number.isFinite(num) ? new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(num) : '—';
  const num = id => Number(String(get(id)).replace(/\s/g,'').replace(',','.')) || 0;
  const money = val => fmt(val)+' '+get('currency');

  function updateRoi() {
    const a=num('extra-payload'), km=num('distance'), r=num('rate'),trips=num('trips'),yr=num('years'),baseline=num('baseline-price'),price=num('price');
    const annual=a*km*r*trips, total=annual*yr, diff=price-baseline;
    $('roi-preview').textContent = checked('show-roi') ?
      `Доход за рейс: ${money(a*km*r)} · В год: ${money(annual)} · За ${fmt(yr)} лет: ${money(total)} · Условный баланс: ${money(total-diff)}.` :
      'Экономический блок будет скрыт.';
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

  function fillBrief(b) {
    ['brand','model','category','slogan','price','currency','style','accent'].forEach(id => set(id,b[id]));
    set('claims',asLines(b.hero_claims));set('specs',asLines(b.specs));set('benefits',asLines(b.benefits));
    set('dimensions',asLines(b.dimensions));set('phones',asLines(b.phones));set('design-notes',b.design_notes);
    $('vat').checked=Boolean(b.vat);$('show-roi').checked=Boolean(b.show_roi);
    const r=b.roi || {};
    [['extra-payload','extra_payload'],['distance','distance'],['rate','rate'],['trips','trips'],['years','years'],['baseline-price','baseline_price']].forEach(([id,key]) => set(id,r[key] ?? ''));
    $('color-label').textContent=String(b.accent || '#e31b26').toUpperCase();
    updateRoi();
  }

  function appendFiles(fd,id) {
    const input=$(id);
    for (const file of input.files) fd.append(id,file,file.name);
  }
  function showError(msg) {
    $('error-box').hidden=false;$('error-box').textContent=msg;
    $('error-box').scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  function clearError() {$('error-box').hidden=true;$('error-box').textContent='';}
  async function parseError(response) {
    try { const b=await response.json(); return typeof b.detail==='string' ? b.detail : `Ошибка ${response.status}`; }
    catch { return `Ошибка ${response.status}. Проверьте подключение к серверу.`; }
  }
  function busy(on) { isBusy=on; $('generate-btn').disabled=on; $('next-btn').disabled=on; $('back-btn').disabled=on; $('inspect-btn').disabled=on||!$('documents').files.length; $('loading').hidden=!on; }
  function download(path) {
    if (!path) return;
    const a=document.createElement('a');a.href=path;a.download=path.split('/').pop();document.body.appendChild(a);a.click();a.remove();
  }

  async function generate() {
    clearError();busy(true);
    const brief = formBrief();
    if (!brief.brand && !brief.model && !brief.category) {
      busy(false);
      setStep(2);
      showError('Укажите бренд, модель или категорию товара, чтобы на макете был понятный заголовок.');
      return;
    }
    setBanner(checked('use-openai') ? 'Генерируем визуалы через OpenAI' : 'Собираем ваши промо-листы','Подготавливаем два самостоятельных PNG.', 'working');
    try {
      const fd=new FormData();fd.append('payload',JSON.stringify(brief));
      ['hero','detail','logo','drawing','references','documents'].forEach(id => appendFiles(fd,id));
      fd.append('use_openai',String(checked('use-openai')));fd.append('use_demo',String(checked('use-demo')));
      fd.append('model',get('image-model'));fd.append('quality',get('image-quality'));
      const response=await fetch('/api/generate',{method:'POST',body:fd});
      if (!response.ok) throw new Error(await parseError(response));
      latest=await response.json();
      notifyParent('promoeditor:result',latest);
      $('download-panel').hidden=false;
      ['download-all','download-4x3','download-9x16'].forEach(id => $(id).disabled=false);
      setBanner('Оба формата готовы', `Сохранены PNG 1440×1080 и 1080×1920. ${(latest.warnings||[]).join(' ')}`, 'done');
      $('download-panel').scrollIntoView({behavior:'smooth',block:'center'});
    } catch (e) {
      setBanner('Не удалось завершить генерацию', 'Проверьте данные или соединение с сервером.');
      showError(e.message || 'Неизвестная ошибка создания изображений.');
    } finally {busy(false);}
  }

  async function inspect() {
    clearError();
    if (!$('documents').files.length) {showError('Сначала добавьте PDF, DOCX, XLSX, CSV или TXT.');return;}
    $('inspect-btn').disabled=true;$('inspect-btn').textContent='Анализ документов...';
    try {
      const fd=new FormData();appendFiles(fd,'documents');
      fd.append('use_ai',String(checked('parse-ai')));fd.append('requirements',get('design-notes'));
      const response=await fetch('/api/inspect',{method:'POST',body:fd});
      if (!response.ok) throw new Error(await parseError(response));
      const result=await response.json();
      const ai=result.ai_suggestions;
      extractedPairs=ai && Array.isArray(ai.specs) ? ai.specs.map(x=>[x.label,x.value]).filter(x=>x[0]&&x[1]) : result.suggested_specs || [];
      $('extract-result').value=asLines(extractedPairs);
      const warn=(result.warnings || []).concat(ai?.warnings || []);
      $('extract-summary').textContent=`Прочитано: ${result.files.map(x=>x.file).join(', ')}. ${ai?'OpenAI предложил данные для проверки.':'Локальное извлечение строк. '} ${warn.join(' ')}`;
      $('extract-box').hidden=false;
      $('extract-box').scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch(e) {showError(e.message || 'Не удалось прочитать документы.');}
    finally {$('inspect-btn').disabled=false;$('inspect-btn').textContent='Извлечь характеристики из файлов';}
  }

  async function resetDemo() {
    try {
      const response=await fetch('/api/demo');
      if (!response.ok) throw new Error('Демонстрационный набор недоступен');
      const d=await response.json();
      fillBrief(d.brief);
      clearError();
      $('use-openai').checked=false; $('use-demo').checked=true; $('parse-ai').checked=false;
      for (const id of ['hero','detail','logo','drawing','references','documents']) $(id).value='';
      $('extract-box').hidden=true;latest=null;
      $('download-panel').hidden=true;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
      updateFileLabels(); updateAiOptions();
      setBanner('Пример ZubrTrail 500 загружен', 'Вы можете заменить тексты и изображения своими, затем создать комплект.');
      setStep(2);
    } catch(e){showError(e.message);}
  }

  async function init() {
    const resp=await fetch('/api/config').catch(()=>null);
    if (resp?.ok) {
      const cfg=await resp.json();apiReady=Boolean(cfg.openai_ready);
      $('api-dot').classList.toggle('good',apiReady);
      $('api-state').textContent=apiReady?'OpenAI подключён':'Без OpenAI API';
    } else {
      $('api-state').textContent='Нет связи с сервером';
    }
    // No automatic test brief: a new document starts with a blank form.
    updateRoi(); updateFileLabels(); updateAiOptions(); setStep(1,{moveFocus:false});
  }

  document.querySelectorAll('[data-go-step]').forEach(button=>{
    button.addEventListener('click',()=>setStep(Number(button.dataset.goStep)));
  });
  $('back-btn').addEventListener('click',()=>setStep(currentStep-1));
  $('next-btn').addEventListener('click',()=>setStep(currentStep+1));
  for (const id of ['hero','detail','logo','drawing','references','documents']) {
    $(id).addEventListener('change',()=>{
      if (id==='references' && $(id).files.length>2)
        showError('Для референсов выберите не более двух изображений.');
      else clearError();
      updateFileLabels();
    });
  }
  $('accent').addEventListener('input',()=>{$('color-label').textContent=get('accent').toUpperCase();});
  for (const id of ['extra-payload','distance','rate','trips','years','baseline-price','price','currency','show-roi'])
    $(id).addEventListener('input',updateRoi);
  $('generate-btn').addEventListener('click',generate);
  $('inspect-btn').addEventListener('click',inspect);
  $('reset-btn').addEventListener('click',resetDemo);
  $('apply-extracted').addEventListener('click',()=>{
    const val=$('extract-result').value.trim();
    if (!val) {showError('Нет распознанных характеристик для переноса.');return;}
    set('specs',val);$('extract-box').hidden=true;
    setStep(2);
    setBanner('Характеристики перенесены в форму', 'Проверьте каждое значение по исходным документам перед генерацией.');
  });
  $('download-all').addEventListener('click',()=>download(latest?.zip));
  $('download-4x3').addEventListener('click',()=>download(latest?.images?.['4x3']));
  $('download-9x16').addEventListener('click',()=>download(latest?.images?.['9x16']));
  $('use-openai').addEventListener('change',()=>{
    updateAiOptions();
    if (checked('use-openai')&&!apiReady)
      showError('OpenAI пока не подключён на сервере. Выключите эту опцию для локальной генерации.');
    else clearError();
  });

  // Shared design switcher: only fields and File objects move between same-origin frames.
  // The UI keeps no copies in localStorage.
  function notifyParent(type, currentResult) {
    if (window.parent !== window)
      window.parent.postMessage({type, result:currentResult||null}, window.location.origin);
  }
  window.PromoEditorVariant = {
    busy: () => isBusy,
    getResult: () => latest,
    restoreResult: (data) => {
      latest = data && data.zip && data.images ? data : null;
      const panel=$('download-panel');
      if (panel) panel.hidden=!latest;
      for(const id of ['download-all','download-4x3','download-9x16'])
        if($(id)) $(id).disabled=!latest;
      if(latest) setBanner('Комплект готов','PNG 4:3 и PNG 9:16 доступны для скачивания.','done');
    },
    refresh: () => {
      updateFileLabels();
      updateRoi();
      updateAiOptions();
    }
  };
  function onRealEdit(event) {
    if(!event.isTrusted || isBusy || !latest) return;
    const node=event.target;
    if(!node || !node.closest('input,textarea,select,[data-style]'))return;
    latest=null;
    $('download-panel').hidden=true;
    for(const id of ['download-all','download-4x3','download-9x16'])$(id).disabled=true;
    notifyParent('promoeditor:cleared',null);
  }
  document.addEventListener('input',onRealEdit,true);
  document.addEventListener('change',onRealEdit,true);
  document.addEventListener('click',onRealEdit,true);

  init();
})();
