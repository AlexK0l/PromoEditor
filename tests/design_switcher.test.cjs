const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../app/static/design-switcher.js'),'utf8');
const all=['wizard','studio','compact','dialog'];

function harness(opts={}){
 const handlers={},links={};
 const files=opts.files===false?[]:[{name:'trailer.png',size:5000}];
 const controls={
   model:{id:'model',type:'text',value:'ZubrTrail 500'},
   slogan:{id:'slogan',type:'textarea',value:'Больше груза'},
   'use-demo':{id:'use-demo',type:'checkbox',checked:false},
   style:{id:'style',type:'select-one',value:'graphite'},
   hero:{id:'hero',type:'file',files}
 };
 const draftStore=opts.draftStore||{};
 const persisted=opts.persisted||{};
 const result={zip:'/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/promo_kit.zip',images:{'4x3':'/files/aaaa/poster_4x3.png'}};
 const bridge={busy:()=>Boolean(opts.busy),getResult:()=>result,refresh:()=>{bridge.refreshed=true;},
   restoreResult:data=>{bridge.restored=data;}};
 const nav={
   id:'pe-switchbar',listeners:{},
   setAttribute(){},
   set innerHTML(html){this.html=html;},
   querySelectorAll(sel){
     assert.equal(sel,'[data-variant]');
     return all.map(name=>({dataset:{variant:name},addEventListener(k,fn){handlers[name]=fn;}}));
   }
 };
 const message={setAttribute(){},classList:{toggle(){}}};
 const body={firstChild:{},insertBefore(node){assert.equal(node,nav)},appendChild(node){assert.equal(node,message)}};
 const document={
   body,
   createElement(tag){return tag==='header'?nav:message;},
   querySelectorAll(){return Object.values(controls);},
   getElementById(id){return controls[id]||null;}
 };
 const location={pathname:'/static/designs/'+(opts.variant||'compact')+'/index.html',
   assign(url){location.target=url;}};
 const window={location,PromoEditorVariant:bridge,
   crypto:{randomUUID:()=> 'test-token'},
   localStorage:{getItem:key=>persisted[key]||null,setItem:(key,val)=>{persisted[key]=val;}},
   sessionStorage:{getItem:key=>draftStore[key]||null,setItem:(key,val)=>{draftStore[key]=val;},
    removeItem:key=>{delete draftStore[key];}},
   indexedDB:opts.indexedDB||null};
 const ctx={window,document,location,DataTransfer:class{constructor(){this.files=[];this.items={add:f=>this.files.push(f)};}},
   console,Date,Math,setTimeout,clearTimeout};
 vm.runInNewContext(script,ctx);
 return {handlers,window,location,controls,bridge,nav,files,draftStore,persisted};
}
test('real top-level paths only, no iframe or srcdoc',()=>{
 const root=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
 assert.doesNotMatch(root,/<iframe\b/i);
 assert.doesNotMatch(script,/frame\.srcdoc=/);
 for(const variant of all){
  const html=fs.readFileSync(path.join(__dirname,'../app/static/designs/'+variant+'/index.html'),'utf8');
  assert.match(html, /design-switcher\.js\?v=/);
  assert.match(html, /design-switcher\.css\?v=/);
 }
});
test('navigation transfers scalar fields and result via sessionStorage',async()=>{
 const h=harness({files:false});
 await h.handlers.dialog({preventDefault(){}});
 assert.equal(h.location.target,'/static/designs/dialog/index.html');
 const transfer=JSON.parse(h.draftStore['promoeditor.ui.transfer.v2']);
 assert.equal(transfer.fields.model.value,'ZubrTrail 500');
 assert.equal(transfer.fields['use-demo'].checked,false);
 assert.equal(transfer.result.zip,'/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/promo_kit.zip');
 assert.equal(h.persisted['promoeditor.design.selection.v1'],'dialog');
});
test('switch is blocked while creation is active',async()=>{
 const h=harness({files:false,busy:true});
 await h.handlers.dialog({preventDefault(){}});
 assert.equal(h.location.target,undefined);
 assert.equal(h.controls.model.value,'ZubrTrail 500');
});
test('top-level switch refuses to silently discard files when IndexedDB unavailable',async()=>{
 const h=harness({files:[{name:'product.png',size:1200}]});
 await h.handlers.wizard({preventDefault(){}});
 assert.equal(h.location.target,undefined);
 assert.equal(h.draftStore['promoeditor.ui.transfer.v2'],undefined);
});
