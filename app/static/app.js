(() => {
  const $ = id => document.getElementById(id);
  let latest = null;
  let extractedPairs = [];
  let apiReady = false;
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
  function busy(on) { $('generate-btn').disabled=on;$('inspect-btn').disabled=on;$('loading').hidden=!on; }
  function download(path) {
    if (!path) return;
    const a=document.createElement('a');a.href=path;a.download=path.split('/').pop();document.body.appendChild(a);a.click();a.remove();
  }

  async function generate() {
    clearError();busy(true);
    $('modebanner').querySelector('b').textContent=checked('use-openai') ? 'Генерация визуальных материалов через OpenAI' : 'Сборка проверяемых макетов без внешнего API';
    try {
      const fd=new FormData();fd.append('payload',JSON.stringify(formBrief()));
      ['hero','detail','logo','drawing','references','documents'].forEach(id => appendFiles(fd,id));
      fd.append('use_openai',String(checked('use-openai')));fd.append('use_demo',String(checked('use-demo')));
      fd.append('model',get('image-model'));fd.append('quality',get('image-quality'));
      const response=await fetch('/api/generate',{method:'POST',body:fd});
      if (!response.ok) throw new Error(await parseError(response));
      latest=await response.json();
      $('download-panel').hidden=false;
      ['download-all','download-4x3','download-9x16'].forEach(id => $(id).disabled=false);
      $('modebanner').querySelector('b').textContent=latest.ai_used ? 'Готово: AI-визуалы и точная верстка' : 'Готово: оба PNG созданы локально';
      $('modebanner').querySelector('span').textContent=`Результат: 1440×1080 и 1080×1920. ${latest.warnings.join(' ')}`;
      $('modebanner').scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch (e) {
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
      const r=await fetch('/api/demo');if(!r.ok)throw new Error('Недоступен демонстрационный набор');
      const d=await r.json();fillBrief(d.brief);clearError();
      $('use-openai').checked=false;$('use-demo').checked=true;$('parse-ai').checked=false;
      for (const id of ['hero','detail','logo','drawing','references','documents']) {$(id).value='';}
      for (const id of ['hero','detail','logo','drawing']) {$('file-'+id).textContent='Выбрать';}
      $('extract-box').hidden=true;latest=null;
      $('download-panel').hidden=true;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
      $('modebanner').querySelector('b').textContent='Демо-режим — без расходов на API';
      $('modebanner').querySelector('span').textContent='Заполните форму и нажмите «Создать оба формата». Ссылки для скачивания появятся здесь.';
    } catch (e) {showError(e.message);}
  }

  async function init() {
    const resp=await fetch('/api/config').catch(()=>null);
    if (resp?.ok) {
      const cfg=await resp.json();apiReady=cfg.openai_ready;
      $('api-dot').classList.toggle('good',apiReady);
      $('api-state').textContent=apiReady?'OpenAI API подключён':'API ключ не задан';
    } else {$('api-state').textContent='Нет связи с сервером';}
    await resetDemo();
  }

  for (const id of ['hero','detail','logo','drawing']) {
    $(id).addEventListener('change', () => {$('file-'+id).textContent=$(id).files[0]?.name || 'Выбрать';});
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
    showError('Характеристики перенесены. Сверьте каждое значение с первичными документами перед публикацией.');
  });
  $('download-all').addEventListener('click',()=>download(latest?.zip));
  $('download-4x3').addEventListener('click',()=>download(latest?.images?.['4x3']));
  $('download-9x16').addEventListener('click',()=>download(latest?.images?.['9x16']));
  $('use-openai').addEventListener('change',()=>{
    if (checked('use-openai')&&!apiReady)
      showError('На сервере пока нет OPENAI_API_KEY. Режим локальной генерации продолжает работать.');
    else clearError();
  });
  init();
})();
