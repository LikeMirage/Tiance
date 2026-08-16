import{x as o,n}from"./index-DPdXAWT8.js";const m=o.memo(function({htmlContent:i}){const r=o.useMemo(()=>a(i),[i]);return n.jsx("iframe",{className:"html-preview-frame",scrolling:"yes",srcDoc:r,sandbox:"",title:"HTML Preview"})}),t=`
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  html {
    width: 100%;
    height: 100%;
    min-height: 100%;
    overflow: auto !important;
    background: #fff;
  }
  body {
    width: 100%;
    min-width: 100%;
    height: auto;
    min-height: 100vh;
    margin: 0;
    overflow: auto !important;
    background: #fff;
  }
  *, *::before, *::after {
    box-sizing: border-box;
  }
  body > :not(script):not(style):not(link):not(meta) {
    min-width: 100vw;
    min-height: 100vh;
  }
  #root, #app, .app, main {
    min-width: 100vw;
    min-height: 100vh;
  }
</style>`;function a(e){return/<\/head>/i.test(e)?e.replace(/<\/head>/i,`${t}</head>`):/<html[\s>]/i.test(e)?e.replace(/<html([^>]*)>/i,`<html$1><head>${t}</head>`):`<!doctype html><html><head>${t}</head><body>${e}</body></html>`}export{m as HtmlPreview};
