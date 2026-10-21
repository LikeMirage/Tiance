import assert from "node:assert/strict";
import { after, test } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React, { useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TestRenderer, { act } from "react-test-renderer";
import ts from "typescript";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { createMarkdownAssetUrlResolver } = await vite.ssrLoadModule("/src/features/document-editor-canvas/model/markdownPreviewAssets.ts");
const { MarkdownPreview } = await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");
const { useDocumentTabFileSync } = await vite.ssrLoadModule("/src/features/document-tabs/model/useDocumentTabFileSync.ts");
const tab = { id: "project:p:docs/A.docx", filePath: "docs/A.docx", kind: "office", mtimeMs: 123, assetVersion: 1,
  fileSource: { kind: "project", id: "p", key: "project:p" } };

test("Markdown parser Unicode/space encoding resolves to the original project file", () => {
  const resolveAssetUrl = createMarkdownAssetUrlResolver({ ...tab, filePath: "防飞溅液品类分析/02_客户与流失.md" });
  const markup = renderToStaticMarkup(React.createElement(MarkdownPreview, {
    content: "![客户生命周期](charts/02_客户生命周期.png)", resolveAssetUrl,
  }));
  const src = /<img[^>]*src="([^"]+)"/.exec(markup)?.[1].replaceAll("&amp;", "&");
  assert.equal(new URL(src).searchParams.get("path"), "防飞溅液品类分析/charts/02_客户生命周期.png");
  const encoded = resolveAssetUrl("charts/hello%20world%23%E5%9B%BE.png");
  assert.equal(new URL(encoded).searchParams.get("path"), "防飞溅液品类分析/charts/hello world#图.png");
  assert.equal(resolveAssetUrl("https://example.com/a.png"), "https://example.com/a.png");
  assert.equal(resolveAssetUrl("//example.com/a.png"), "//example.com/a.png");
});

test("directory notifications reconcile assets without reloading an unchanged sibling", async () => {
  let handlers, current, lists = 0;
  const runtime = { source: tab.fileSource,
    getApi: () => ({ listTree: async () => { lists++; return { items: [{ path: "docs/A.docx", mtime_ms: 123 }] }; } }),
    watchFileEvents: (value) => { handlers = value; return () => {}; },
  };
  function Harness() {
    const [tabs, setTabs] = useState([tab]);
    current = tabs;
    const tabsRef = useRef(tabs);
    tabsRef.current = tabs;
    const sync = useDocumentTabFileSync({
      activeTabIdRef: useRef(tab.id), fileLoadRequestIdsRef: useRef(new Map()),
      setActiveTabId: () => {}, setTabs, tabs, tabsRef,
    });
    sync.registerFileSource(runtime);
    return null;
  }
  let root;
  await act(async () => { root = TestRenderer.create(React.createElement(Harness)); });
  await act(async () => handlers.onChanged(["docs/B.txt"]));
  assert.equal(lists, 0);
  await act(async () => handlers.onChanged(["docs", "docs/B.txt"]));
  assert.equal(lists, 1);
  assert.equal(current[0].assetVersion, 1);
  await act(async () => handlers.onChanged(["docs/A.docx"]));
  assert.notEqual(current[0].assetVersion, 1);
  await act(async () => root.unmount());
});

// Stub drawing/network dependencies, keeping the actual component and React lifecycle.
const require = createRequire(import.meta.url);
function load(relative, mocks = {}) {
  const source = fs.readFileSync(new URL("../" + relative, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { fileName: relative, compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext("(function(require,module,exports){" + js + "\n})", { filename: relative })(
    (name) => name in mocks ? mocks[name] : require(name), module, module.exports);
  return module.exports;
}
const reading = load("src/entities/editor/model/documentReadingState.tsx");
const filePreview = load("src/features/file-preview/model/filePreview.ts", {
  "../../../services/http/httpClient": {},
});
const empty = () => null;
const loadingContext = load("src/shared/ui/loading-strip/loadingBoundaryContext.ts");
const { LoadingStrip } = load("src/shared/ui/loading-strip/LoadingStrip.tsx", {
  "./loadingBoundaryContext": loadingContext, "./loading-strip.css": {},
});
const { LoadingBoundary } = load("src/shared/ui/loading-strip/LoadingBoundary.tsx", {
  "./loadingBoundaryContext": loadingContext, "./LoadingStrip": { LoadingStrip },
});

test("PDF retains page on parent rerender and new version, clamps to a shorter document", async () => {
  let loads = 0, pages = 8;
  const panZoom = { viewportRef: { current: null }, contentRef: { current: null } };
  const { PdfPreview } = load("src/features/pdf-preview/ui/PdfPreview.tsx", {
    "../../../entities/editor/model/documentReadingState": reading,
    "@phosphor-icons/react": new Proxy({}, { get: () => empty }),
    "../model/pdfPageImage": {},
    "../model/pdfjsLoader": { loadPdfJs: async () => ({ getDocument: () => {
      loads++; return { promise: Promise.resolve({ numPages: pages }), destroy: async () => {} };
    } }) },
    "./PdfPageView": { PdfPageView: empty }, "./PdfThumbnailStrip": { PdfThumbnailStrip: empty },
    "../../../shared/model/pan-zoom/usePanZoomViewport": { usePanZoomViewport: () => panZoom },
    "../../../shared/ui/context-menu": { ContextMenu: empty, ContextMenuItem: empty },
    "../../../shared/ui/loading-strip": { LoadingStrip: empty },
    "../../../shared/ui/preview-zoom-control": { PreviewZoomControl: empty }, "./pdf-preview.css": {},
  });
  const view = (version) => React.createElement(reading.DocumentReadingStateProvider, { activeKey: "a", openKeys: ["a"] },
    React.createElement(PdfPreview, { key: version, src: `http://localhost/a.pdf?v=${version}`,
      displayPath: "a.pdf", fileName: "a.pdf", onMissing: () => {} }));
  let root;
  await act(async () => { root = TestRenderer.create(view(1)); });
  const page = () => root.root.findByProps({ className: "pdf-preview__page-label" }).children.join("");
  await act(async () => root.root.findAllByType("button").find(x => x.props.title === "下一页").props.onClick());
  assert.equal(page(), "2 / 8");
  await act(async () => root.update(view(1)));
  assert.equal(loads, 1);
  assert.equal(page(), "2 / 8");
  await act(async () => root.update(view(2)));
  assert.equal(loads, 2);
  assert.equal(page(), "2 / 8");
  pages = 1;
  await act(async () => root.update(view(3)));
  assert.equal(page(), "1 / 1");
  await act(async () => root.unmount());
});

test("reading state belongs to its tab and is released when that tab closes", async () => {
  let update, current;
  function Reader() {
    [current, update] = reading.useDocumentReadingValue("page", 1);
    return null;
  }
  const view = (key, open) => React.createElement(reading.DocumentReadingStateProvider,
    { activeKey: key, openKeys: open }, React.createElement(Reader));
  let root;
  await act(async () => { root = TestRenderer.create(view("a", ["a", "b"])); });
  await act(async () => update(12));
  await act(async () => root.update(view("b", ["a", "b"])));
  assert.equal(current, 1);
  await act(async () => root.update(view("a", ["a", "b"])));
  assert.equal(current, 12);
  await act(async () => root.update(view("b", ["b"])));
  await act(async () => root.update(view("a", ["a", "b"])));
  assert.equal(current, 1);
  await act(async () => root.unmount());
});

test("preview gate preserves an unchanged rendering, replaces new versions and ignores cancelled checks", async () => {
  global.window = { location: { href: "http://localhost/" } };
  const checks = [];
  let mounts = 0, releases = 0;
  const { FilePreviewGate } = load("src/features/file-preview/ui/FilePreviewGate.tsx", {
    "../../../shared/ui/loading-strip": { LoadingBoundary },
    "../../../entities/editor/model/documentReadingState": reading,
    "../../../services/http/httpClient": { HttpRequestError: class extends Error {} },
    "../../document-editor-canvas/ui/UnsupportedDocumentContent": { DocumentOpenFallbackContent: empty },
    "../model/filePreview": { ...filePreview, inspectFilePreview: (src, signal) => new Promise(resolve => {
      checks.push({ src, signal, resolve });
    }) },
    "./file-preview.css": {},
  });
  function Renderer({ src }) {
    React.useEffect(() => { mounts++; return () => { releases++; }; }, []);
    return React.createElement("output", null, src);
  }
  const view = version => React.createElement(FilePreviewGate, { tab, src: `http://localhost/asset?v=${version}` },
    (_inspection, src) => React.createElement(Renderer, { src }));
  const result = version => ({ mode: "inline", version });
  let root;
  await act(async () => { root = TestRenderer.create(view(1)); });
  await act(async () => checks[0].resolve(result("a")));
  assert.equal(root.root.findAllByProps({ className: "file-preview-session__bar" }).length, 0);
  const original = root.root.findByType("output").children.join("");
  await act(async () => root.update(view(2)));
  assert.equal(mounts, 1);
  assert.equal(root.root.findByProps({ className: "file-preview-session__content" }).props.inert, true);
  await act(async () => checks[1].resolve(result("a")));
  assert.equal(root.root.findByType("output").children.join(""), original);
  assert.equal(mounts, 1);
  await act(async () => root.update(view(3)));
  await act(async () => checks[2].resolve(result("b")));
  assert.equal(mounts, 2);
  assert.equal(releases, 1);
  await act(async () => root.update(view(4)));
  await act(async () => root.update(view(5)));
  assert.equal(checks[3].signal.aborted, true);
  await act(async () => checks[4].resolve(result("c")));
  await act(async () => checks[3].resolve(result("stale")));
  assert.match(root.root.findByType("output").children.join(""), /preview_version=c$/);
  await act(async () => root.update(view(6)));
  await act(async () => root.root.findAllByType("button").find(b => b.children[0] === "取消加载").props.onClick());
  assert.equal(checks[5].signal.aborted, true);
  await act(async () => checks[5].resolve(result("cancelled")));
  assert.equal(root.root.findAllByType("output").length, 0);
  assert.equal(releases, mounts);
  await act(async () => root.unmount());
  const csvView = React.createElement(FilePreviewGate, { tab: { ...tab, title: "file.csv" }, src: "http://localhost/asset?v=1" },
    (_inspection, src) => React.createElement(Renderer, { src }));
  await act(async () => { root = TestRenderer.create(csvView); });
  await act(async () => checks.at(-1).resolve({ ...result("csv"), delimited: { encoding: "utf-8-sig", delimiter: "comma" } }));
  const before = mounts;
  assert.equal(new URL(root.root.findByType("output").children.join("")).searchParams.get("delimiter"), "comma");
  await act(async () => root.root.findByProps({ "aria-label": "分隔符" }).props.onChange({ target: { value: "semicolon" } }));
  assert.equal(mounts, before); // old view stays inert until the new interpretation is ready
  await act(async () => checks.at(-1).resolve({ ...result("csv"), delimited: { encoding: "utf-8-sig", delimiter: "semicolon" } }));
  assert.equal(mounts, before + 1);
  assert.equal(new URL(root.root.findByType("output").children.join("")).searchParams.get("delimiter"), "semicolon");
  await act(async () => root.unmount());
  delete global.window;
});
