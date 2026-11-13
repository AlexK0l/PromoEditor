(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const canvas=$('edit-canvas');
  if(!canvas)return;
  const ctx=canvas.getContext('2d',{alpha:false});
  const MAX_FILE=20*1024*1024;
  const MAX_PROJECT=30*1024*1024;
  const MAX_PIXELS=9_000_000;
  const TOOLS=['select','cover','region'];
  const VALID_IMAGE=/^data:image\/(png|jpeg|webp);base64,/i;
  const STATE={
    base:null,baseData:'',name:'promo',layers:[],selectedId:null,
    tool:'select',region:null,draft:null,drag:null,busy:false,
    history:[],future:[],latest:null
  };

  function status(message,error=false) {
    $('edit-status').textContent=message;
    $('edit-status').classList.toggle('is-error',Boolean(error));
  }
  function requireBase() {
    if(!STATE.base){status('Сначала откройте PNG или загрузите свой файл.',true);return false;}
    return true;
  }
  function bounds(layer) {
    return {x:layer.x,y:layer.y,w:layer.w||80,h:layer.h||80};
  }
  function cloneState(){
    return {
      base:STATE.base,baseData:STATE.baseData,name:STATE.name,
      layers:STATE.layers.map(layer=>({...layer})),
      selectedId:STATE.selectedId,
      region:STATE.region?{...STATE.region}:null
    };
  }
  function remember(){
    STATE.history.push(cloneState());
    if(STATE.history.length>25)STATE.history.shift();
    STATE.future=[];
    updateHistory();
  }
  function restore(snapshot){
    STATE.base=snapshot.base;
    STATE.baseData=snapshot.baseData;
    STATE.name=snapshot.name;
    STATE.layers=snapshot.layers.map(layer=>({...layer}));
    STATE.selectedId=snapshot.selectedId;
    STATE.region=snapshot.region?{...snapshot.region}:null;
    STATE.draft=null;
    canvas.width=STATE.base.width;canvas.height=STATE.base.height;
    $('edit-workspace').hidden=false;
    refreshSelected();draw();
  }
  function updateHistory(){
    $('edit-undo').disabled=!STATE.history.length||STATE.busy;
    $('edit-redo').disabled=!STATE.future.length||STATE.busy;
  }
  function setTool(name){
    if(!TOOLS.includes(name))return;
    STATE.tool=name;
    document.querySelectorAll('[data-edit-tool]').forEach(button=>{
      const active=button.dataset.editTool===name;
      button.classList.toggle('is-selected',active);
      button.setAttribute('aria-pressed',String(active));
    });
    canvas.style.cursor=name==='select'?'move':'crosshair';
    status(name==='cover'?'Протяните рамку поверх элемента, который хотите закрыть выбранным цветом.':
      name==='region'?'Протяните рамку по области, которую нужно заменить с помощью OpenAI.':
      'Нажмите на добавленный слой и перетащите его на новое место.');
  }
  function textLines(layer) {
    ctx.font='700 '+layer.size+'px Arial, sans-serif';
    const output=[];
    const maxWidth=Math.max(30,layer.w);
    for(const paragraph of String(layer.text||'').split(/\r?\n/)){
      let line='';
      for(const word of paragraph.split(/\s+/)){
        if(!word)continue;
        const candidate=line?line+' '+word:word;
        if(line&&ctx.measureText(candidate).width>maxWidth){
          output.push(line);line=word;
        }else line=candidate;
      }
      output.push(line||' ');
      if(output.length>=18)break;
    }
    return output;
  }
  function drawText(layer){
    const lines=textLines(layer);
    const height=layer.size*1.18;
    layer.h=Math.ceil(lines.length*height);
    ctx.font='700 '+layer.size+'px Arial, sans-serif';
    ctx.textBaseline='top';
    ctx.fillStyle=layer.color;
    for(let i=0;i<lines.length;i++)ctx.fillText(lines[i],layer.x,layer.y+i*height,layer.w);
  }
  function outline(area,color='#2663db'){
    ctx.save();ctx.strokeStyle=color;ctx.lineWidth=Math.max(2,canvas.width/650);
    ctx.setLineDash([Math.max(6,canvas.width/140),Math.max(4,canvas.width/210)]);
    ctx.strokeRect(area.x,area.y,area.w,area.h);
    ctx.restore();
  }
  function draw(guides=true){
    if(!STATE.base)return;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(STATE.base,0,0,canvas.width,canvas.height);
    for(const layer of STATE.layers){
      if(layer.type==='cover'){
        ctx.fillStyle=layer.color;ctx.fillRect(layer.x,layer.y,layer.w,layer.h);
      }else if(layer.type==='image'&&layer.image){
        ctx.drawImage(layer.image,layer.x,layer.y,layer.w,layer.h);
      }else if(layer.type==='text'){
        drawText(layer);
      }
    }
    if(!guides)return;
    if(STATE.selectedId!==null){
      const sel=STATE.layers.find(layer=>layer.id===STATE.selectedId);
      if(sel)outline(bounds(sel));
    }
    if(STATE.region) {
      ctx.save();ctx.fillStyle='rgba(54,97,240,.1)';
      ctx.fillRect(STATE.region.x,STATE.region.y,STATE.region.w,STATE.region.h);
      ctx.restore();outline(STATE.region,'#e22f53');
    }
    if(STATE.draft)outline(STATE.draft,STATE.tool==='cover'?'#ff7d1f':'#e22f53');
  }
  async function dataURL(blob){
    return await new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onload=()=>resolve(reader.result);
      reader.onerror=()=>reject(new Error('Не удалось прочитать файл.'));
      reader.readAsDataURL(blob);
    });
  }
  async function decode(uri){
    if(typeof uri!=='string'||!VALID_IMAGE.test(uri)||uri.length>45_000_000)
      throw Error('Неподдерживаемый формат изображения в проекте.');
    const image=new Image();
    image.src=uri;
    try{await image.decode();}catch{throw Error('Не удалось открыть изображение.');}
    if(image.naturalWidth<128||image.naturalHeight<128||
       image.naturalWidth>4096||image.naturalHeight>4096||
       image.naturalWidth*image.naturalHeight>MAX_PIXELS)
      throw Error('Слишком большое изображение: максимум 4096 px по стороне и 9 млн пикселей.');
    return image;
  }
  function resetWithBase(image,uri,name){
    STATE.base=image;STATE.baseData=uri;STATE.name=name||'promo';
    STATE.layers=[];STATE.selectedId=null;STATE.region=null;STATE.draft=null;STATE.drag=null;
    STATE.history=[];STATE.future=[];
    canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    $('edit-workspace').hidden=false;
    $('edit-body').hidden=false;
    $('edit-toggle').setAttribute('aria-expanded','true');
    $('edit-toggle').textContent='Свернуть редактор';
    refreshSelected();updateHistory();draw();
    status('Загружено '+image.naturalWidth+' × '+image.naturalHeight+' px. Исходник останется неизменным.');
  }
  async function openBlob(blob,name){
    if(!blob||!blob.size||blob.size>MAX_FILE)throw Error('Файл должен быть до 20 МБ.');
    const uri=await dataURL(blob);
    const image=await decode(uri);
    resetWithBase(image,uri,name);
  }
  async function loadCreated(fmt){
    if(!STATE.latest||!STATE.latest.images||!STATE.latest.images[fmt]){status('Сначала создайте комплект.',true);return;}
    const path=STATE.latest.images[fmt];
    if(!/^\/files\/[a-f0-9]{32}\/poster_(4x3|9x16)\.png$/.test(path))
      throw Error('Некорректная ссылка на результат.');
    const response=await fetch(path,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw Error('Не удалось загрузить созданный PNG (HTTP '+response.status+').');
    await openBlob(await response.blob(),'promo_'+fmt);
  }
  function selected(){return STATE.layers.find(layer=>layer.id===STATE.selectedId)||null;}
  function refreshSelected(){
    const layer=selected();
    $('edit-selected-fields').hidden=!layer;
    $('edit-selected-name').textContent=!layer?'Нажмите на добавленный текст или изображение.':
      (layer.type==='text'?'Текстовый слой':layer.type==='cover'?'Закрытая область':'Изображение поверх');
    if(!layer)return;
    const isText=layer.type==='text';
    $('edit-selected-text-wrap').hidden=!isText;
    $('edit-selected-text').value=isText?layer.text:'';
    $('edit-layer-width').value=Math.round(layer.w);
    $('edit-layer-height').value=Math.round(layer.h);
  }
  function nextId(){return Date.now()+Math.random();}
  function addText(){
    if(!requireBase())return;
    const text=$('edit-text-input').value.trim();
    if(!text){status('Введите текст, который нужно добавить.',true);return;}
    const size=Number($('edit-text-size').value)||52;
    remember();
    const layer={id:nextId(),type:'text',text:text.slice(0,500),
      x:canvas.width*.1,y:canvas.height*.2,w:Math.round(canvas.width*.78),
      h:size*1.4,size:Math.max(12,Math.min(200,size)),color:$('edit-text-color').value};
    STATE.layers.push(layer);STATE.selectedId=layer.id;setTool('select');
    refreshSelected();draw();status('Текст добавлен. Перетащите его на нужное место.');
  }
  async function addImage(file){
    if(!requireBase())return;
    if(!file||file.size>MAX_FILE||!/^image\/(png|jpeg|webp)$/.test(file.type))
      throw Error('Добавьте PNG/JPG/WEBP размером до 20 МБ.');
    const uri=await dataURL(file),image=await decode(uri);
    const w=Math.min(canvas.width*.42,image.width),h=w*image.height/image.width;
    remember();
    const layer={id:nextId(),type:'image',image,imageData:uri,
      x:Math.round(canvas.width*.15),y:Math.round(canvas.height*.18),
      w:Math.round(w),h:Math.round(h)};
    STATE.layers.push(layer);STATE.selectedId=layer.id;setTool('select');
    refreshSelected();draw();status('Изображение добавлено. Можно переместить, изменить размер или удалить.');
  }
  function ppoint(event){
    const rect=canvas.getBoundingClientRect();
    return {x:Math.max(0,Math.min(canvas.width,(event.clientX-rect.left)*canvas.width/rect.width)),
            y:Math.max(0,Math.min(canvas.height,(event.clientY-rect.top)*canvas.height/rect.height))};
  }
  function area(a,b){
    const x=Math.round(Math.min(a.x,b.x)),y=Math.round(Math.min(a.y,b.y));
    const w=Math.round(Math.abs(a.x-b.x)),h=Math.round(Math.abs(a.y-b.y));
    return {x,y,w,h};
  }
  function hit(point){
    for(let i=STATE.layers.length-1;i>=0;i--){
      const layer=STATE.layers[i],b=bounds(layer);
      if(point.x>=b.x&&point.x<=b.x+b.w&&point.y>=b.y&&point.y<=b.y+b.h)return layer;
    }
    return null;
  }
  function pointerDown(event){
    if(!STATE.base||STATE.busy||event.button!==0)return;
    event.preventDefault();
    const p=ppoint(event);
    if(STATE.tool==='select'){
      const found=hit(p);
      STATE.selectedId=found?.id??null;
      if(found){
        remember();
        STATE.drag={mode:'layer',id:found.id,start:p,x:found.x,y:found.y};
      }else STATE.drag=null;
      refreshSelected();
    }else{
      STATE.drag={mode:'area',start:p};
      STATE.draft={x:p.x,y:p.y,w:0,h:0};
    }
    try{canvas.setPointerCapture(event.pointerId);}catch{}
    draw();
  }
  function pointerMove(event){
    if(!STATE.drag||!STATE.base||STATE.busy)return;
    event.preventDefault();const p=ppoint(event),drag=STATE.drag;
    if(drag.mode==='layer'){
      const layer=STATE.layers.find(v=>v.id===drag.id);
      if(layer) {
        layer.x=Math.round(Math.max(-layer.w+10,Math.min(canvas.width-10,drag.x+p.x-drag.start.x)));
        layer.y=Math.round(Math.max(-layer.h+10,Math.min(canvas.height-10,drag.y+p.y-drag.start.y)));
      }
    }else STATE.draft=area(drag.start,p);
    draw();
  }
  function pointerUp(event){
    if(!STATE.drag||!STATE.base||STATE.busy)return;
    const drag=STATE.drag;
    const region=drag.mode==='area'?area(drag.start,ppoint(event)):null;
    STATE.drag=null;STATE.draft=null;
    if(region&&region.w>8&&region.h>8){
      if(STATE.tool==='region'){
        STATE.region=region;
        status('Область выделена. Введите запрос ниже и нажмите «Применить через OpenAI».');
      }else if(STATE.tool==='cover'){
        remember();
        const layer={id:nextId(),type:'cover',x:region.x,y:region.y,
          w:region.w,h:region.h,color:$('edit-cover-color').value};
        STATE.layers.push(layer);STATE.selectedId=layer.id;
        refreshSelected();
        status('Область закрыта сплошным цветом. Теперь можно добавить поверх текст или изображение.');
      }
    }
    draw();
  }
  function updateLayer(field){
    const layer=selected();
    if(!layer)return;
    const val=field.value;
    remember();
    if(field.id==='edit-selected-text'&&layer.type==='text')layer.text=val.slice(0,500);
    if(field.id==='edit-layer-width'){
      const width=Math.max(10,Math.min(canvas.width*2,Number(val)||10));
      if(layer.type==='image')layer.h=Math.round(width*layer.h/layer.w);
      layer.w=width;
    }
    if(field.id==='edit-layer-height'){
      const height=Math.max(10,Math.min(canvas.height*2,Number(val)||10));
      if(layer.type==='image')layer.w=Math.round(height*layer.w/layer.h);
      else if(layer.type==='text')layer.size=Math.max(12,Math.min(200,Math.round(layer.size*height/layer.h)));
      layer.h=height;
    }
    refreshSelected();draw();
  }
  function deleteLayer(){
    const idx=STATE.layers.findIndex(l=>l.id===STATE.selectedId);
    if(idx<0)return;
    remember();STATE.layers.splice(idx,1);STATE.selectedId=null;
    refreshSelected();draw();status('Элемент удалён.');
  }
  function bringForward(){
    const idx=STATE.layers.findIndex(l=>l.id===STATE.selectedId);
    if(idx<0||idx===STATE.layers.length-1)return;
    remember();
    const [layer]=STATE.layers.splice(idx,1);STATE.layers.splice(idx+1,0,layer);
    draw();
  }
  async function snapshotPng(){
    if(!requireBase())return null;
    draw(false);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
    draw(true);
    if(!blob)throw Error('Не удалось экспортировать PNG.');
    return blob;
  }
  function downloadBlob(blob,name) {
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download=name;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  async function exportPng() {
    const blob=await snapshotPng();if(!blob)return;
    downloadBlob(blob,(STATE.name||'promo').replace(/[^a-z0-9_-]/gi,'_')+'_edited.png');
    status('PNG сохранён. Исходное промо не изменено.');
  }
  async function saveProject(){
    if(!requireBase())return;
    const layers=STATE.layers.map(layer=>{
      const {image,...other}=layer;
      return other;
    });
    const file={type:'PromoEditor-editable-v1',width:canvas.width,height:canvas.height,
      base:STATE.baseData,name:STATE.name,layers};
    const data=JSON.stringify(file);
    if(data.length>MAX_PROJECT)throw Error('Проект превышает 30 МБ. Скачайте текущий PNG.');
    downloadBlob(new Blob([data],{type:'application/json'}),
      (STATE.name||'promo').replace(/[^a-z0-9_-]/gi,'_')+'.promo.json');
    status('Редактируемый проект сохранён. Его можно снова открыть в этой форме.');
  }
  async function openProject(file){
    if(!file||file.size>MAX_PROJECT)throw Error('Проект не должен превышать 30 МБ.');
    let doc;
    try{doc=JSON.parse(await file.text());}catch{throw Error('Проект должен содержать корректный JSON.');}
    if(!doc||doc.type!=='PromoEditor-editable-v1'||!Array.isArray(doc.layers)||
       doc.layers.length>80)throw Error('Это не сохранённый проект PromoEditor.');
    const image=await decode(doc.base);
    if(image.width!==doc.width||image.height!==doc.height)
      throw Error('Размеры сохранённого проекта не совпадают.');
    const layers=[];
    for(const raw of doc.layers){
      if(!raw||!['text','image','cover'].includes(raw.type))throw Error('Некорректный слой.');
      const w=Number(raw.w),h=Number(raw.h),x=Number(raw.x),y=Number(raw.y);
      if(![w,h,x,y].every(Number.isFinite)||w<1||h<1||w>8192||h>8192||
          Math.abs(x)>8192||Math.abs(y)>8192)throw Error('Некорректный размер слоя.');
      const layer={id:nextId(),type:raw.type,w,h,x,y};
      if(raw.type==='text'){
        layer.text=String(raw.text||'').slice(0,500);
        layer.size=Math.max(12,Math.min(200,Number(raw.size)||52));
        layer.color=/^#[0-9a-f]{6}$/i.test(raw.color)?raw.color:'#ffffff';
      }else if(raw.type==='cover'){
        layer.color=/^#[0-9a-f]{6}$/i.test(raw.color)?raw.color:'#ffffff';
      }else{
        layer.imageData=raw.imageData;
        layer.image=await decode(raw.imageData);
      }
      layers.push(layer);
    }
    resetWithBase(image,doc.base,String(doc.name||'promo').slice(0,100));
    STATE.layers=layers;refreshSelected();draw();
    status('Проект открыт: все добавленные текстовые и графические слои можно редактировать.');
  }
  function maskCanvas(){
    if(!STATE.region)return null;
    const tmp=document.createElement('canvas');tmp.width=canvas.width;tmp.height=canvas.height;
    const m=tmp.getContext('2d');
    m.fillStyle='rgba(255,255,255,1)';m.fillRect(0,0,tmp.width,tmp.height);
    m.clearRect(STATE.region.x,STATE.region.y,STATE.region.w,STATE.region.h);
    return tmp;
  }
  async function imageBlobForAI(){
    const tmp=document.createElement('canvas');
    tmp.width=canvas.width;tmp.height=canvas.height;
    tmp.getContext('2d').drawImage(STATE.base,0,0,canvas.width,canvas.height);
    return await new Promise(resolve=>tmp.toBlob(resolve,'image/png'));
  }
  async function runAi(){
    if(!requireBase()||STATE.busy)return;
    const instruction=$('edit-ai-prompt').value.trim();
    if(!instruction||instruction.length>2500){
      status('Опишите, что нужно изменить (до 2500 символов).',true);return;
    }
    const whole=!STATE.region;
    if(!window.confirm(whole?
      'Будет выполнен один ПЛАТНЫЙ запрос OpenAI для изменения всего изображения. AI может исказить текст и детали. Продолжить?':
      'Будет выполнен один ПЛАТНЫЙ запрос OpenAI для выбранной области. Остальные исходные пиксели будут сохранены. Продолжить?'))return;
    STATE.busy=true;
    const button=$('edit-run-ai');button.disabled=true;button.textContent='AI редактирует…';
    updateHistory();status('OpenAI редактирует исходное изображение. Это платный запрос…');
    try{
      const image=await imageBlobForAI();
      if(!image||image.size>MAX_FILE)throw Error('Слишком большой PNG для API (максимум 20 МБ).');
      const form=new FormData();
      form.append('image',image,'existing_promo.png');
      form.append('instruction',instruction);
      form.append('model',$('image-model')?.value||'gpt-image-2.5-flare');
      form.append('quality',$('edit-ai-quality').value);
      const mask=maskCanvas();
      if(mask){
        const blob=await new Promise(resolve=>mask.toBlob(resolve,'image/png'));
        if(!blob||blob.size>=4*1024*1024)throw Error('Выделенная область слишком большая для маски.');
        form.append('mask',blob,'region.png');
      }
      const response=await fetch('/api/edit',{method:'POST',body:form});
      let result;
      try{result=await response.json();}catch{throw Error('Сервер вернул некорректный ответ.');}
      if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Ошибка AI-редактирования.');
      if(!/^\/files\/[a-f0-9]{32}\/edit\.png$/.test(result.image||''))throw Error('Сервер вернул неверный путь к файлу.');
      const edited=await fetch(result.image,{credentials:'same-origin',cache:'no-store'});
      if(!edited.ok)throw Error('Не удалось скачать изменённое изображение.');
      const uri=await dataURL(await edited.blob());
      const imageUpdated=await decode(uri);
      if(imageUpdated.width!==canvas.width||imageUpdated.height!==canvas.height)
        throw Error('Размеры изменённого изображения не совпадают с исходным.');
      remember();
      STATE.base=imageUpdated;STATE.baseData=uri;STATE.region=null;
      draw();status('AI-правка применена. Проверьте мелкий текст и технические данные. Слои поверх изображения остались редактируемыми.');
    }catch(err){
      status(err.message||'Не удалось выполнить AI-редактирование.',true);
    }finally{
      STATE.busy=false;button.disabled=false;button.textContent='✦ Применить через OpenAI';
      updateHistory();
    }
  }
  async function task(action){
    try{await action();}catch(error){status(error.message||'Ошибка редактирования.',true);}
  }
  $('edit-toggle').addEventListener('click',()=>{
    const opened=$('edit-body').hidden;
    $('edit-body').hidden=!opened;
    $('edit-toggle').setAttribute('aria-expanded',String(opened));
    $('edit-toggle').textContent=opened?'Свернуть редактор':'Открыть редактор';
  });
  $('edit-open-landscape').addEventListener('click',()=>task(()=>loadCreated('4x3')));
  $('edit-open-portrait').addEventListener('click',()=>task(()=>loadCreated('9x16')));
  $('edit-open-file').addEventListener('change',event=>task(async()=>{
    const file=event.target.files[0];
    if(!file)return;
    if(STATE.base&&STATE.layers.length&&!window.confirm('Открыть другое изображение и сбросить текущие слои? Сохраните проект, если нужно вернуться.'))return;
    await openBlob(file,file.name.replace(/\.[^.]+$/,''));
    event.target.value='';
  }));
  $('edit-project-file').addEventListener('change',event=>task(async()=>{
    if(!event.target.files[0])return;
    if(STATE.base&&STATE.layers.length&&!window.confirm('Заменить текущий редактор сохранённым проектом?'))return;
    await openProject(event.target.files[0]);event.target.value='';
  }));
  document.querySelectorAll('[data-edit-tool]').forEach(button=>
    button.addEventListener('click',()=>setTool(button.dataset.editTool)));
  $('edit-clear-region').addEventListener('click',()=>{
    STATE.region=null;draw();status('Область AI-редактирования сброшена.');
  });
  $('edit-add-text').addEventListener('click',addText);
  $('edit-overlay-file').addEventListener('change',event=>task(async()=>{
    const file=event.target.files[0];if(!file)return;
    await addImage(file);event.target.value='';
  }));
  $('edit-selected-text').addEventListener('change',event=>updateLayer(event.target));
  $('edit-layer-width').addEventListener('change',event=>updateLayer(event.target));
  $('edit-layer-height').addEventListener('change',event=>updateLayer(event.target));
  $('edit-delete-layer').addEventListener('click',deleteLayer);
  $('edit-bring-forward').addEventListener('click',bringForward);
  canvas.addEventListener('pointerdown',pointerDown);
  canvas.addEventListener('pointermove',pointerMove);
  canvas.addEventListener('pointerup',pointerUp);
  canvas.addEventListener('pointercancel',pointerUp);
  $('edit-undo').addEventListener('click',()=>{
    if(!STATE.history.length||STATE.busy)return;
    STATE.future.push(cloneState());restore(STATE.history.pop());updateHistory();
  });
  $('edit-redo').addEventListener('click',()=>{
    if(!STATE.future.length||STATE.busy)return;
    STATE.history.push(cloneState());restore(STATE.future.pop());updateHistory();
  });
  $('edit-download').addEventListener('click',()=>task(exportPng));
  $('edit-save-project').addEventListener('click',()=>task(saveProject));
  $('edit-run-ai').addEventListener('click',runAi);
  window.addEventListener('promoeditor:generated',event=>{
    STATE.latest=event.detail;
    const good=Boolean(STATE.latest?.images?.['4x3']&&STATE.latest?.images?.['9x16']);
    $('edit-open-landscape').disabled=!good;
    $('edit-open-portrait').disabled=!good;
    if(good&&$('edit-body').hidden)status('Комплект создан. Откройте редактор, чтобы изменить готовое промо.');
  });
})();
