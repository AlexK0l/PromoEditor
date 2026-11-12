const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '../app/static/design-switcher.js'),'utf8');

function element(id, props={}) {
  const listeners={};
  return {
    id, type:'text', value:'', checked:false, files:[], hidden:false, open:false,
    tabIndex:0, listeners,
    ...props,
    addEventListener(kind,fn){ (listeners[kind] ||= []).push(fn); },
    setAttribute(name,value){ (this.attributes ||= {})[name]=value; },
    focus(){},
    async emit(kind,payload={}) {
      for(const callback of listeners[kind]||[])await callback(payload);
    }
  };
}

function mockDocument(initial={}) {
  const fields={
    brand:element('brand'), model:element('model'), slogan:element('slogan'),
    specs:element('specs'), 'use-openai':element('use-openai',{type:'checkbox'}),
    'use-demo':element('use-demo',{type:'checkbox',checked:true}),
    hero:element('hero',{type:'file'}), documents:element('documents',{type:'file'}),
    style:element('style',{value:'industrial'})
  };
  for(const [key,vals] of Object.entries(initial)){
    Object.assign(fields[key],vals);
  }
  const more={ 'advanced-settings':element('advanced-settings'), 'extract-box':element('extract-box',{hidden:true}) };
  return {
    fields,
    getElementById(id){return fields[id]||more[id]||null;},
    querySelectorAll(){return Object.values(fields);}
  };
}
function harness() {
  const activeResult={zip:'/files/'+('a'.repeat(32))+'/promo_kit.zip',
    images:{'4x3':'/files/abc/poster_4x3.png','9x16':'/files/abc/poster_9x16.png'}};
  const photo={name:'trailer.png',size:17000,type:'image/png'};
  const contexts={wizard:mockDocument(),studio:mockDocument(),compact:mockDocument({
    model:{value:'ZubrTrail 500'},slogan:{value:'Легче на 2,5 т'},
    hero:{files:[photo]}, 'use-demo':{checked:false},style:{value:'graphite'}
  })};
  const bridges={};
  const tabs={},frames={},views={};
  const notice=element('switch-notice',{hidden:true});
  const document={
    getElementById(id){
      if(id==='switch-notice')return notice;
      if(id.startsWith('tab-'))return tabs[id.slice(4)];
      if(id.startsWith('frame-'))return frames[id.slice(6)];
      if(id.startsWith('view-'))return views[id.slice(5)];
      throw Error('Unknown id '+id);
    }
  };
  for(const name of ['wizard','studio','compact']){
    tabs[name]=element('tab-'+name);
    views[name]=element('view-'+name,{hidden:name!=='compact'});
    bridges[name]={
      current:name==='compact'?activeResult:null, busyFlag:false, refreshCalls:0,
      getResult(){return this.current;},
      restoreResult(data){this.current=data;},
      refresh(){this.refreshCalls++;},
      busy(){return this.busyFlag;}
    };
    frames[name]={contentDocument:contexts[name],srcdoc:'',
      contentWindow:{PromoEditorVariant:bridges[name]}};
  }
  const localRecord={},handlers={};
  const window={location:{origin:'https://promo.example.com'},
    addEventListener(kind,fn){handlers[kind]=fn;}};
  class DataTransfer {
    constructor(){
      this.files=[];
      this.items={add:file=>this.files.push(file)};
    }
  }
  const localStorage={
    getItem:key=>localRecord[key]||null,
    setItem:(key,value)=>{localRecord[key]=value;}
  };
  vm.runInNewContext(script,{window,document,localStorage,DataTransfer,
    setTimeout,clearTimeout,console});
  return {tabs,views,bridges,contexts,photo,activeResult,localRecord,notice,handlers,frames};
}

test('switcher moves texts, checkboxes, styles, uploaded file objects and existing result', async()=>{
  const h=harness();
  await h.tabs.wizard.emit('click');
  assert.equal(h.contexts.wizard.fields.model.value,'ZubrTrail 500');
  assert.equal(h.contexts.wizard.fields.slogan.value,'Легче на 2,5 т');
  assert.equal(h.contexts.wizard.fields['use-demo'].checked,false);
  assert.equal(h.contexts.wizard.fields.style.value,'graphite');
  assert.equal(h.contexts.wizard.fields.hero.files[0],h.photo);
  assert.equal(h.bridges.wizard.current,h.activeResult);
  assert.equal(h.views.wizard.hidden,false);
  assert.equal(h.views.compact.hidden,true);
  assert.equal(h.localRecord['promoeditor.design.selection.v1'],'wizard');
  h.contexts.wizard.fields.model.value='Отредактированная модель';
  await h.tabs.studio.emit('click');
  assert.equal(h.contexts.studio.fields.model.value,'Отредактированная модель');
  assert.equal(h.contexts.studio.fields.hero.files[0],h.photo);
  assert.equal(h.bridges.studio.current,h.activeResult);
  assert.equal(h.bridges.studio.refreshCalls,1);
});

test('switching is blocked while generation runs, without losing current form',async()=>{
  const h=harness();
  h.bridges.compact.busyFlag=true;
  await h.tabs.studio.emit('click');
  assert.equal(h.views.compact.hidden,false);
  assert.equal(h.views.studio.hidden,true);
  assert.match(h.notice.textContent,/Дождитесь/);
  assert.equal(h.contexts.compact.fields.model.value,'ZubrTrail 500');
});

test('DENY-compatible layout loading uses same-origin fetch into srcdoc, not iframe navigation',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
  assert.doesNotMatch(html,/\bsrc="\/static\/designs\//);
  for(const name of ['wizard','studio','compact']){
    assert.match(html,new RegExp('data-layout="'+name+'"'));
  }
  assert.match(script,/frame\.srcdoc=markup/);
  assert.match(script,/credentials:'same-origin'/);
  assert.doesNotMatch(script,/target\.addEventListener\('load'/);
});
