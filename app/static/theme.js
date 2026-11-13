/* Shared appearance switcher. Does not affect image pixels or API requests. */
(() => {
  'use strict';
  const KEY='promoeditor.theme.v1';
  const darkColor='#0d1420',lightColor='#f6f7fb';
  const system=window.matchMedia?.('(prefers-color-scheme: dark)');
  let preference=null;
  try {
    const saved=window.localStorage.getItem(KEY);
    if(saved==='light'||saved==='dark')preference=saved;
  }catch(error){/* private mode/storage restriction */}
  function chosen(){return preference||(system?.matches?'dark':'light');}
  function apply(theme){
    document.documentElement.setAttribute('data-theme',theme);
    const meta=document.querySelector('meta[name="theme-color"]');
    if(meta)meta.setAttribute('content',theme==='dark'?darkColor:lightColor);
    document.querySelectorAll('[data-theme-toggle]').forEach(button=>{
      button.setAttribute('aria-pressed',String(theme==='dark'));
      button.setAttribute('aria-label',theme==='dark'?'Включить светлую тему':'Включить тёмную тему');
      button.setAttribute('title',theme==='dark'?'Включить светлую тему':'Включить тёмную тему');
      const label=button.querySelector('[data-theme-label]');
      const icon=button.querySelector('[data-theme-icon]');
      if(label)label.textContent=theme==='dark'?'Светлая тема':'Тёмная тема';
      if(icon)icon.textContent=theme==='dark'?'☀':'☾';
    });
  }
  function set(theme){
    if(theme!=='light'&&theme!=='dark')return;
    preference=theme;
    try{window.localStorage.setItem(KEY,theme);}catch(error){}
    apply(theme);
  }
  apply(chosen()); // before CSS parsing on the main page: avoids dark-mode flash
  function bind(){
    apply(chosen());
    // First paint uses the saved/system theme without animation.
    // Only subsequent user/system changes interpolate colors.
    document.documentElement.classList.add('theme-ready');
    document.querySelectorAll('[data-theme-toggle]').forEach(button=>{
      button.addEventListener('click',()=>set(chosen()==='dark'?'light':'dark'));
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});
  else bind();
  window.addEventListener('storage',event=>{
    if(event.key!==KEY)return;
    preference=event.newValue==='light'||event.newValue==='dark'?event.newValue:null;
    apply(chosen());
  });
  system?.addEventListener?.('change',()=>{if(!preference)apply(chosen());});
})();
