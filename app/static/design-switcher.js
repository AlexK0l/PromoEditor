(() => {
  'use strict';
  // Each layout is an ordinary top-level HTML page. X-Frame-Options: DENY
  // remains enabled at the reverse proxy. No iframes or dynamic HTML injection.
  const names=['wizard','studio','compact','dialog'];
  const label={wizard:'По шагам',studio:'Студия',compact:'Компактный',dialog:'Диалог'};
  const tagline={wizard:'Мастер',studio:'Карточки',compact:'Простая форма',dialog:'AI-бриф'};
  const selected=location.pathname.match(/^\/static\/designs\/(wizard|studio|compact|dialog)\/index\.html$/)?.[1];
  if(!selected)return;
  const PREF='promoeditor.design.selection.v1';
  const TRANSFER='promoeditor.ui.transfer.v2';
  const DB_NAME='PromoEditorTemporaryTransfer';
  const DB_STORE='handoffs';
  const EXPIRE_MS=10*60*1000;
  const elements=[...document.querySelectorAll('input[id],textarea[id],select[id]')];

  const nav=document.createElement('header');
  nav.id='pe-switchbar';
  nav.setAttribute('aria-label','Переключение интерфейса PromoEditor');
  nav.innerHTML='<div class="pe-brand"><span class="pe-brand-mark" aria-hidden="true">P</span><span><strong>PromoEditor</strong><small>Выберите удобный вид</small></span></div>'+
    '<nav class="pe-switch-list" aria-label="Варианты оформления">'+
    names.map(name=>'<a class="pe-option" data-variant="'+name+'" href="/static/designs/'+name+'/index.html"'+
      (name===selected?' aria-current="page"':'')+'><span class="pe-icon" aria-hidden="true">'+(name==='dialog'?'✦':name==='compact'?'≡':name==='studio'?'▦':'①')+
      '</span><span><strong>'+label[name]+'</strong><small>'+tagline[name]+'</small></span></a>').join('')+
    '</nav><span class="pe-note">✓ Поля и вложения сохраняются при переключении</span>';
  document.body.insertBefore(nav,document.body.firstChild);
  const message=document.createElement('div');
  message.id='pe-nav-message';
  message.setAttribute('role','status');
  message.setAttribute('aria-live','polite');
  document.body.appendChild(message);

  function info(text) {
    message.textContent=text;
    message.classList.toggle('is-visible',Boolean(text));
  }
  function idb() {
    return new Promise((resolve,reject)=>{
      if(!window.indexedDB){reject(new Error('IndexedDB недоступен'));return;}
      const req=window.indexedDB.open(DB_NAME,1);
      req.onupgradeneeded=()=>{
        if(!req.result.objectStoreNames.contains(DB_STORE))req.result.createObjectStore(DB_STORE);
      };
      req.onsuccess=()=>resolve(req.result);
      req.onerror=()=>reject(req.error||new Error('Ошибка временного хранилища'));
    });
  }
  async function storeFiles(token,uploads) {
    const db=await idb();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction(DB_STORE,'readwrite');
      tx.objectStore(DB_STORE).put(uploads,token);
      tx.oncomplete=()=>{db.close();resolve();};
      tx.onabort=()=>{db.close();reject(tx.error||new Error('Хранилище переполнено'));};
      tx.onerror=()=>{db.close();reject(tx.error||new Error('Ошибка сохранения файлов'));};
    });
  }
  async function takeFiles(token) {
    const db=await idb();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction(DB_STORE,'readwrite');
      const store=tx.objectStore(DB_STORE);
      let files=[];
      const req=store.get(token);
      req.onsuccess=()=>{files=req.result||[];store.delete(token);};
      tx.oncomplete=()=>{db.close();resolve(files);};
      tx.onabort=()=>{db.close();reject(tx.error||new Error('Не удалось вернуть файлы'));};
      tx.onerror=()=>{db.close();reject(tx.error||new Error('Хранилище недоступно'));};
    });
  }
  function snapshot() {
    const fields={};
    const uploads=[];
    for(const el of elements){
      if(el.type==='file'){
        const files=Array.from(el.files||[]);
        if(files.length)uploads.push({id:el.id,files});
      }else if(el.type==='checkbox'||el.type==='radio'){
        fields[el.id]={kind:'checked',checked:el.checked};
      }else fields[el.id]={kind:'value',value:el.value};
    }
    return {fields,uploads,settings:document.getElementById('advanced-settings')?.open??null,
      extracted:document.getElementById('extract-box')?.hidden??null,
      result:window.PromoEditorVariant?.getResult?.()||null};
  }
  let navigating=false;
  async function switchTo(name) {
    if(!names.includes(name)||navigating||name===selected)return;
    if(window.PromoEditorVariant?.busy?.()){
      info('Дождитесь завершения генерации, затем смените оформление.');
      return;
    }
    navigating=true;
    try {
      info('Переносим заполненные данные и файлы…');
      const draft=snapshot();
      const token=(window.crypto?.randomUUID?.()||String(Date.now())+'-'+Math.random());
      if(draft.uploads.length)await storeFiles(token,draft.uploads);
      const transfer={token,to:name,created:Date.now(),
        fields:draft.fields,settings:draft.settings,extracted:draft.extracted,
        result:draft.result,hasFiles:draft.uploads.length>0};
      window.sessionStorage.setItem(TRANSFER,JSON.stringify(transfer));
      try{window.localStorage.setItem(PREF,name);}catch(err){}
      window.location.assign('/static/designs/'+name+'/index.html');
    }catch(err){
      info('Не удалось перенести вложения. Проверьте свободное место браузера и повторите попытку.');
      navigating=false;
      console.error('PromoEditor: design switching failed',err);
    }
  }
  nav.querySelectorAll('[data-variant]').forEach(a=>{
    a.addEventListener('click',event=>{
      if(a.dataset.variant===selected)return;
      event.preventDefault();
      switchTo(a.dataset.variant);
    });
  });
  try{window.localStorage.setItem(PREF,selected);}catch(err){}
  async function restore() {
    let data;
    try {data=JSON.parse(window.sessionStorage.getItem(TRANSFER)||'null');}catch(err){}
    if(!data)return;
    if(data.to!==selected || Date.now()-data.created>EXPIRE_MS) {
      window.sessionStorage.removeItem(TRANSFER);
      return;
    }
    try {
      for(const [id,value] of Object.entries(data.fields||{})) {
        const el=document.getElementById(id);
        if(!el||el.type==='file')continue;
        if(value.kind==='checked'&&(el.type==='checkbox'||el.type==='radio'))el.checked=value.checked;
        else if(value.kind==='value')el.value=value.value;
      }
      let missedFiles=false;
      if(data.hasFiles){
        const uploads=await takeFiles(data.token);
        for(const upload of uploads){
          const el=document.getElementById(upload.id);
          if(!el||el.type!=='file')continue;
          try{
            const transfer=new DataTransfer();
            for(const file of upload.files)transfer.items.add(file);
            el.files=transfer.files;
          }catch(err){missedFiles=true;}
        }
        if(!uploads.length)missedFiles=true;
      }
      const settings=document.getElementById('advanced-settings');
      if(settings&&data.settings!==null)settings.open=data.settings;
      const extracted=document.getElementById('extract-box');
      if(extracted&&data.extracted!==null)extracted.hidden=data.extracted;
      const color=document.getElementById('accent'),label=document.getElementById('color-label');
      if(color&&label)label.textContent=color.value.toUpperCase();
      window.PromoEditorVariant?.refresh?.();
      window.PromoEditorVariant?.restoreResult?.(data.result);
      window.sessionStorage.removeItem(TRANSFER);
      if(missedFiles)info('Некоторые вложения не перенеслись. Прикрепите их ещё раз.');
    }catch(err){
      info('Поля не удалось полностью восстановить. Проверьте введённые данные.');
      console.error('PromoEditor: form restoration failed',err);
    }
  }
  // Variant app.js runs first and initializes the shared bridge.
  restore();
})();
