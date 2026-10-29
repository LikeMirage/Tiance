import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../", import.meta.url));
function load(relative, mocks = {}) {
  const file = path.join(root, relative);
  const js = ts.transpileModule(fs.readFileSync(file,"utf8"), { fileName: file, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const module = {exports:{}};
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, {filename:file})(name => {
    if (name in mocks) return typeof mocks[name] === "function" ? mocks[name]() : mocks[name];
    if (name.startsWith(".")) return {};
    return require(name);
  }, module, module.exports);
  return module.exports;
}

test("PDF loader shares in-flight imports but retries after a rejected import", async () => {
  let imports = 0;
  const library = {GlobalWorkerOptions:{}};
  const loader = load("src/features/pdf-preview/model/pdfjsLoader.ts", {
    "pdfjs-dist/build/pdf.worker.mjs?url": {default:"worker.js"},
    "pdfjs-dist": () => { if (++imports === 1) throw new Error("temporary network failure");return library; },
  });
  const first = loader.loadPdfJs();
  assert.equal(first, loader.loadPdfJs());
  await assert.rejects(first, loader.PdfModuleLoadError);
  const second = loader.loadPdfJs();
  assert.equal(second, loader.loadPdfJs());
  await second;
  assert.equal(imports,2);
  assert.equal(library.GlobalWorkerOptions.workerSrc,"worker.js");
  assert.equal(await loader.loadPdfJs(),await second);
});

test("tool basics and examples submit one batch; failures never start independent writes", async () => {
  const {saveToolDashboardContent} = load("src/features/document-tabs/model/documentToolDashboardTabs.ts");
  const requests = [];
  const api = { saveTextFile() {throw new Error("independent write must not occur");},
    async saveTextFiles(files) {requests.push(files);throw new Error("second file rejected; rolled back");} };
  const runtime = {getApi:()=>api};
  await assert.rejects(saveToolDashboardContent(runtime, JSON.stringify({registration_name:"tool", input_schema:{type:"object"}}),"basics"),/rolled back/);
  assert.deepEqual(requests[0].map(x=>x.path),[".tool/input.schema.json",".tool/tool.json"]);
  await assert.rejects(saveToolDashboardContent(runtime, JSON.stringify({registration_name:"tool",examples:[]}),"examples"),/rolled back/);
  assert.deepEqual(requests[1].map(x=>x.path),[".tool/examples.json",".tool/tool.json"]);
});

test("PPT renders the restored page once at fitted zoom; ready notification adds no draw", async t => {
  const original = {document:globalThis.document,fetch:globalThis.fetch,ResizeObserver:globalThis.ResizeObserver,IntersectionObserver:globalThis.IntersectionObserver};
  t.after(()=>Object.assign(globalThis,original));
  const canvas = () => ({width:0,height:0,style:{},getContext:()=>({clearRect(){},drawImage(){}})});
  globalThis.document = {createElement:()=>({...canvas(),offscreen:true})};
  globalThis.fetch = async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(4)});
  globalThis.ResizeObserver = class {observe(){} disconnect(){}};
  globalThis.IntersectionObserver = class {observe(){} disconnect(){}};
  const draws=[];
  const dims={width:800,height:600};
  class Viewer {
    async loadFile(){} getSlideCount(){return 3;} destroy(){}
    async render(target,options){draws.push({offscreen:!!target.offscreen,width:target.width,page:options.slideIndex});}
  }
  const utils = {
    preparePresentationCanvas:(c,d,z)=>{c.width=d.width*z;c.height=d.height*z;},
    readPresentationDimensions:async()=>dims,resolvePresentationDimensions:()=>dims,
    slideCssSize:d=>d,presentationThumbnailZoom:()=>0.1,
    repairPresentationCanvasBlankBottomEdge(){},restorePresentationZoomAnchor(){},
  };
  const {PresentationPreview} = load("src/features/office-preview/ui/PresentationPreview.tsx", {
    "pptxviewjs":{PPTXViewer:Viewer},
    "@phosphor-icons/react": {CaretLeft:()=>null,CaretRight:()=>null},
    "../../../entities/editor/model/documentReadingState":{
      useDocumentReadingValue:(key,initial)=>React.useState(key==="ppt:slide"?1:initial),useDocumentReadingScroll(){},
    },
    "../../../shared/ui/loading-strip":{LoadingStrip:()=>null},
    "./presentationPreviewUtils":utils,"./officePreviewUtils":{clampOfficeZoom:x=>x},
  });
  let setZoom,renderer;
  function Harness(){const [zoom,update]=React.useState(1);setZoom=update;
    return React.createElement(PresentationPreview,{displayPath:"test.pptx",fileName:"test.pptx",src:"/test.pptx",zoom,onZoomChange:update});}
  const createNodeMock = node => node.type === "canvas" ? canvas() : {
    clientWidth:496,scrollLeft:0,scrollTop:0,style:{},scrollIntoView(){},
    getBoundingClientRect:()=>({width:496,height:600,left:0,top:0}),
  };
  await act(async()=>{renderer=create(React.createElement(Harness),{createNodeMock});});
  t.after(async()=>act(async()=>renderer.unmount()));
  await act(async()=>{});
  assert.deepEqual(draws.filter(x=>x.offscreen),[{offscreen:true,width:400,page:1}]);
  await act(async()=>{setZoom(0.75);});
  assert.equal(draws.filter(x=>x.offscreen).length,2);
  assert.equal(draws.filter(x=>x.offscreen)[1].width,600);
});

test("provider selection waits for the shared unsaved transition before changing either selection",async()=>{
  const filename=path.join(root,"src/pages/workspace/ui/WorkspacePage.tsx");
  const source=ts.createSourceFile(filename,fs.readFileSync(filename,"utf8"),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let initializer;
  function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(source)==="handleSelectProvider")initializer=node.initializer.arguments[0].getText(source);ts.forEachChild(node,visit);}
  visit(source);assert.ok(initializer);
  const js=ts.transpile(`const handler=${initializer};`,{target:ts.ScriptTarget.ES2022});
  const calls=[];let transition;
  const project={project_id:"b",root_path:"b"};
  const handler=new Function("providerProjects","getProviderIdFromProject","projectCatalog","providerCatalog","requestUnsavedTransition","projectDocumentTabs",`${js};return handler;`)(
    [project],x=>x,{selectedProjectId:"a",selectProject:id=>calls.push(["project",id])},
    {selectProvider:id=>calls.push(["provider",id])},(_tabs,_kind,callback)=>{transition=callback;},{});
  await handler("b");
  assert.deepEqual(calls,[]);
  assert.equal(typeof transition,"function");
  await transition();
  assert.deepEqual(calls,[["provider","b"],["project","b"]]);
});
