(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fileIds = ['hero','documents','logo','detail','drawing','references'];
  const briefIds = ['model','slogan','design-notes','brand','category','claims','specs','benefits','dimensions','price','currency','vat','phones','show-roi','extra-payload','distance','rate','trips','years','baseline-price','style','accent','use-openai','image-model','image-quality','use-demo'];
  const placeholders = {documents:'PDF, Excel, Word',logo:'Необязательно',detail:'Дополнительный ракурс',drawing:'PNG, JPG или PDF',references:'До 2 изображений'};
  let latest = null;
  let apiReady = false;
  let isBusy = false;
  let hasDemo = false;

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
      slogan:get('slogan').trim(),design_notes:get('design-notes').trim(),
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
    ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
    setStatus('Параметры изменены','Создайте новый комплект, чтобы применить изменения.');
  }
  function updateFileLabels(){
    const hero=$('hero').files[0];
    $('hero-label').textContent=hero?(hero.name.length>45?hero.name.slice(0,42)+'…':hero.name):'Добавить фото товара';
    $('hero-hint').textContent=hero?'Фото выбрано — можно заменить':'Перетащите сюда или выберите файл';
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
    $('file-feedback').textContent=count?`Прикреплено файлов: ${count}. Оригиналы не включаются в готовый ZIP.`:'Оригинальные файлы не добавляются в скачиваемый ZIP.';
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
    if($('references').files.length>2)return 'Можно добавить до двух изображений-референсов.';
    if(all.some(file=>file.size>20*1024*1024))return 'Один из файлов больше 20 МБ. Уменьшите его размер.';
    if(all.reduce((sum,file)=>sum+file.size,0)>68*1024*1024)return 'Общий размер вложений не должен превышать 68 МБ.';
    return '';
  }
  function busy(on){
    isBusy=on;
    $('generate-btn').disabled=on;
    $('reset-btn').disabled=on;
    $('inspect-btn').disabled=on||!$('documents').files.length;
    $('loading').hidden=!on;
    const button=$('generate-btn');
    if(on)button.textContent='Создаём изображения…';
    else button.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 1.5 6L20 11l-6.5 2L12 20l-1.5-7L4 11l6.5-2L12 3Z"/></svg> Создать два формата <span aria-hidden="true">→</span>';
  }
  function appendFiles(form,id){for(const file of $(id).files)form.append(id,file,file.name);}
  function download(path){
    if(!path)return;
    const link=document.createElement('a');
    link.href=path;link.download=path.split('/').pop();document.body.appendChild(link);link.click();link.remove();
  }
  async function generate(){
    clearError();
    if(!get('model').trim()){
      showError('Укажите название или модель товара — это нужно для заголовка промо-листа.','model');return;
    }
    const invalid=validateFiles();if(invalid){showError(invalid);return;}
    if(checked('use-openai')&&!apiReady){showError('OpenAI не подключён на сервере. Используйте обычную сборку или настройте ключ в VPS.');return;}
    if(!checked('use-openai')&&!$('hero').files.length&&!checked('use-demo')){
      showError('Сначала добавьте фото товара или нажмите «Заполнить пример» для пробного комплекта.');return;
    }
    invalidateResult();busy(true);
    setStatus('Создаём изображения','Генерируем PNG 4:3 и 9:16.','working');
    try {
      const form=new FormData();form.append('payload',JSON.stringify(formBrief()));
      fileIds.forEach(id=>appendFiles(form,id));
      form.append('use_openai',String(checked('use-openai')));
      form.append('use_demo',String(checked('use-demo')));
      form.append('model',get('image-model'));
      form.append('quality',get('image-quality'));
      const response=await fetch('/api/generate',{method:'POST',body:form});
      if(!response.ok)throw new Error(await readError(response));
      latest=await response.json();
      notifyParent('promoeditor:result',latest);
      $('download-panel').hidden=false;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=false);
      setStatus('Готово','Оба PNG и ZIP можно скачать ниже.','done');
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
    set('claims',asLines(data.hero_claims));set('specs',asLines(data.specs));set('benefits',asLines(data.benefits));set('dimensions',asLines(data.dimensions));set('phones',asLines(data.phones));set('design-notes',data.design_notes);
    $('vat').checked=Boolean(data.vat);$('show-roi').checked=Boolean(data.show_roi);
    const roi=data.roi||{};
    for(const [id,key] of [['extra-payload','extra_payload'],['distance','distance'],['rate','rate'],['trips','trips'],['years','years'],['baseline-price','baseline_price']])set(id,roi[key]??'');
    $('color-label').textContent=get('accent').toUpperCase();
    updateRoi();refreshStyle();
  }
  function clearForm(){
    for(const id of ['brand','model','category','slogan','design-notes','claims','specs','benefits','dimensions','price','phones'])set(id,'');
    set('currency','Br');set('style','industrial');set('accent','#e31b26');
    $('vat').checked=true;$('show-roi').checked=false;$('use-openai').checked=false;$('use-demo').checked=false;$('parse-ai').checked=false;
    for(const id of fileIds)$(id).value='';
    $('extract-box').hidden=true;
    $('advanced-settings').open=false;
    $('color-label').textContent='#E31B26';
    hasDemo=false;
    $('reset-btn').textContent='Заполнить пример';
    latest=null;$('download-panel').hidden=true;
    ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
    clearError();updateRoi();refreshStyle();updateFileLabels();updateAi();
  }
  async function resetDemo(){
    if(hasDemo){clearForm();return;}
    clearError();
    try {
      const response=await fetch('/api/demo');if(!response.ok)throw new Error('Пример временно недоступен.');
      const result=await response.json();fillBrief(result.brief);
      for(const id of fileIds)$(id).value='';
      $('use-openai').checked=false;$('use-demo').checked=true;$('parse-ai').checked=false;
      $('advanced-settings').open=false;
      $('extract-box').hidden=true;
      hasDemo=true;
      $('reset-btn').textContent='Очистить форму';
      latest=null;$('download-panel').hidden=true;
      ['download-all','download-4x3','download-9x16'].forEach(id=>$(id).disabled=true);
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
      $('api-dot').classList.toggle('good',apiReady);
      $('api-state').textContent=apiReady?'OpenAI подключён':'Без OpenAI';
    }catch{
      $('api-state').textContent='Сервер недоступен';
    }
    updateAi();refreshStyle();updateFileLabels();updateRoi();
  }

  for(const id of fileIds){
    $(id).addEventListener('change',()=>{updateFileLabels();invalidateResult();clearError();});
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
      invalidateResult();
    });
    $(id).addEventListener('change',()=>invalidateResult());
  }
  document.querySelectorAll('[data-style]').forEach(button=>button.addEventListener('click',()=>{
    set('style',button.dataset.style);
    const accents={industrial:'#e31b26',graphite:'#344054',minimal:'#315ddc'};
    set('accent',accents[button.dataset.style]);$('color-label').textContent=get('accent').toUpperCase();
    refreshStyle();invalidateResult();
  }));
  $('use-openai').addEventListener('change',()=>{if(checked('use-openai')&&!apiReady){$('use-openai').checked=false;showError('OpenAI пока не подключён. Добавьте API-ключ на сервере.');}updateAi();invalidateResult();});
  $('show-roi').addEventListener('change',updateRoi);
  $('hero-drop').addEventListener('dragover',event=>{event.preventDefault();$('hero-drop').classList.add('is-dragging');});
  $('hero-drop').addEventListener('dragleave',event=>{if(!$('hero-drop').contains(event.relatedTarget))$('hero-drop').classList.remove('is-dragging');});
  $('hero-drop').addEventListener('drop',event=>{
    event.preventDefault();$('hero-drop').classList.remove('is-dragging');
    const file=Array.from(event.dataTransfer?.files||[]).find(f=>/\.(png|jpe?g|webp)$/i.test(f.name));
    if(!file){showError('Основное фото должно быть PNG, JPG или WEBP. Документы загружайте через кнопку ниже.');return;}
    if(file.size>20*1024*1024){showError('Фото больше 20 МБ. Выберите файл меньшего размера.');return;}
    const transfer=new DataTransfer();transfer.items.add(file);$('hero').files=transfer.files;
    $('hero').dispatchEvent(new Event('change',{bubbles:true}));
  });
  $('reset-btn').addEventListener('click',resetDemo);
  $('generate-btn').addEventListener('click',generate);
  $('inspect-btn').addEventListener('click',inspect);
  $('apply-extracted').addEventListener('click',()=>{
    const values=$('extract-result').value.trim();
    if(!values){showError('Нет характеристик для переноса.');return;}
    set('specs',values);$('advanced-settings').open=true;$('extract-box').hidden=true;
    invalidateResult();setStatus('ТТХ перенесены','Проверьте каждую характеристику до публикации.');
    $('specs').scrollIntoView({behavior:'smooth',block:'center'});
  });
  $('download-all').addEventListener('click',()=>download(latest?.zip));
  $('download-4x3').addEventListener('click',()=>download(latest?.images?.['4x3']));
  $('download-9x16').addEventListener('click',()=>download(latest?.images?.['9x16']));

  // Shared design switcher: only fields and File objects move between same-origin frames.
  // The UI keeps no copies in localStorage.
  function notifyParent(type, currentResult) {
    if (window.parent !== window)
      window.parent.postMessage({type, result:currentResult||null}, window.parent.location.origin);
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
      if(latest) setStatus('Комплект готов','Скачайте оба PNG или ZIP.','done');
    },
    refresh: () => {
      updateFileLabels();
      updateRoi();
      refreshStyle();updateAi();
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
