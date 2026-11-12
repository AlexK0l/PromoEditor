(() => {
  'use strict';
  const names = ['wizard','studio','compact','dialog'];
  const STORE_KEY = 'promoeditor.design.selection.v1';
  const frames = Object.fromEntries(names.map(name => [name, document.getElementById('frame-'+name)]));
  const tabs = Object.fromEntries(names.map(name => [name, document.getElementById('tab-'+name)]));
  let current = 'compact';
  let snapshot = null;
  let result = null;
  let switching = false;
  const notice = document.getElementById('switch-notice');

  function showNotice(text) {
    notice.textContent=text;
    notice.hidden=!text;
  }
  function isReady(frame) {
    try { return Boolean(frame.contentWindow && frame.contentWindow.PromoEditorVariant); }
    catch { return false; }
  }
  // Fetch markup as a same-origin resource and assign it to srcdoc.
  // Caddy's X-Frame-Options: DENY correctly blocks network iframe navigations;
  // srcdoc is created by the already-authorized parent and keeps that protection.
  const loading = new Map();
  async function ensureLoaded(name) {
    const frame=frames[name];
    if(isReady(frame))return;
    if(loading.has(name))return loading.get(name);
    const task=(async()=>{
      const controller=new AbortController();
      const abortTimer=setTimeout(()=>controller.abort(),12000);
      let markup;
      try {
        const response=await fetch('/static/designs/'+name+'/index.html',{
          credentials:'same-origin',cache:'no-store',signal:controller.signal
        });
        if(!response.ok)throw new Error('HTTP '+response.status);
        markup=await response.text();
      }finally{clearTimeout(abortTimer);}
      await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>{frame.removeEventListener('load',onLoad);reject(new Error('Загрузка интерфейса превысила 12 секунд'));},12000);
        function onLoad(){
          if(!isReady(frame))return;
          clearTimeout(timeout);
          frame.removeEventListener('load',onLoad);
          resolve();
        }
        frame.addEventListener('load',onLoad);
        frame.srcdoc=markup;
      });
    })();
    loading.set(name,task);
    try {await task;}finally {loading.delete(name);}
  }

  function readState(frame) {
    const data = {fields:{},expanded:null,extracted:null};
    const doc=frame.contentDocument;
    if(!doc)return data;
    for(const el of doc.querySelectorAll('input[id],textarea[id],select[id]')) {
      if(el.type==='file')data.fields[el.id]={kind:'file',files:Array.from(el.files||[])};
      else if(el.type==='checkbox'||el.type==='radio')data.fields[el.id]={kind:'checked',checked:el.checked};
      else data.fields[el.id]={kind:'value',value:el.value};
    }
    const settings=doc.getElementById('advanced-settings'),extract=doc.getElementById('extract-box');
    data.expanded=settings?settings.open:null;
    data.extracted=extract?!extract.hidden:null;
    return data;
  }
  function applyState(frame,data) {
    if(!data || !frame.contentDocument)return;
    const doc=frame.contentDocument;
    let lostFiles=false;
    for(const [id,field] of Object.entries(data.fields||{})) {
      const el=doc.getElementById(id);
      if(!el)continue;
      if(field.kind==='file'&&el.type==='file') {
        try {
          const transfer=new DataTransfer();
          for(const file of field.files||[])transfer.items.add(file);
          el.files=transfer.files;
        }catch(err){ lostFiles=lostFiles || (field.files||[]).length>0; }
      }else if(field.kind==='checked'&&(el.type==='checkbox'||el.type==='radio'))el.checked=field.checked;
      else if(field.kind==='value'&&el.type!=='file')el.value=field.value;
    }
    const settings=doc.getElementById('advanced-settings'),extract=doc.getElementById('extract-box');
    if(settings && data.expanded!==null)settings.open=data.expanded;
    if(extract && data.extracted!==null)extract.hidden=!data.extracted;
    const bridge=frame.contentWindow.PromoEditorVariant;
    bridge.refresh();
    bridge.restoreResult(result);
    if(lostFiles)showNotice('Браузер не разрешил перенести некоторые файлы. Выберите их ещё раз.');
  }
  function updateTabs(next) {
    for(const name of names) {
      const selected=name===next;
      tabs[name].setAttribute('aria-selected',String(selected));
      tabs[name].tabIndex=selected?0:-1;
      document.getElementById('view-'+name).hidden=!selected;
    }
  }
  function remember(next) {
    try {localStorage.setItem(STORE_KEY,next);}catch(err){/* private browsing */}
  }
  async function activate(next) {
    if(!names.includes(next)||switching)return;
    if(next===current) {updateTabs(next);return;}
    const previous=frames[current];
    if(isReady(previous)) {
      if(previous.contentWindow.PromoEditorVariant.busy()){
        showNotice('Дождитесь завершения генерации перед сменой интерфейса.');
        return;
      }
      snapshot=readState(previous);
      result=previous.contentWindow.PromoEditorVariant.getResult();
    }
    switching=true;
    current=next;
    updateTabs(next);
    remember(next);
    showNotice('');
    const target=frames[next];
    try {
      await ensureLoaded(next);
      applyState(target,snapshot);
    } catch(error) {
      current=previous===frames.wizard?'wizard':previous===frames.studio?'studio':'compact';
      updateTabs(current);
      remember(current);
      showNotice('Не удалось загрузить дизайн. Проверьте соединение и повторите переключение.');
      console.error('PromoEditor variant load failed:',error);
    } finally {switching=false;}
  }
  for(const name of names){
    tabs[name].addEventListener('click',()=>activate(name));
    tabs[name].addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();
      const index=names.indexOf(name);
      const next=event.key==='Home'?names[0]:event.key==='End'?names[names.length-1]:
        names[(index+(event.key==='ArrowRight'?1:-1)+names.length)%names.length];
      activate(next).then(()=>tabs[next].focus());
    });
  }
  window.addEventListener('message',event=>{
    if(event.origin!==window.location.origin)return;
    const sender=names.find(name=>frames[name].contentWindow===event.source);
    if(!sender || sender!==current || !event.data)return;
    if(event.data.type==='promoeditor:result' && event.data.result &&
        /^\/files\/[a-f0-9]{32}\/promo_kit\.zip$/.test(event.data.result.zip||'')) {
      result=event.data.result;
    }
    if(event.data.type==='promoeditor:cleared')result=null;
  });
  // Preference only; no text, uploaded files or OpenAI secrets are stored in localStorage.
  let saved='compact';
  try{saved=localStorage.getItem(STORE_KEY)||'compact';}catch(err){}
  updateTabs(current);
  if(names.includes(saved)&&saved!==current)activate(saved);
  else ensureLoaded(current).catch(error=>{
    showNotice('Не удалось загрузить редактор. Обновите страницу.');
    console.error('PromoEditor initial variant load failed:',error);
  });
})();
