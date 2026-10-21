import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import React from "react";
import TestRenderer, { act } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
function load(relative, mocks = {}) {
  const source = fs.readFileSync(new URL("../" + relative, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { fileName: relative, compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext("(function(require,module,exports){" + js + "\n})", { filename: relative })(
    name => name in mocks ? mocks[name] : require(name), module, module.exports);
  return module.exports;
}

test("Word mounts only nearby chunks, cancels scrolling-away requests, and restores its reading chunk", async () => {
  const reads = [];
  const frames = [];
  global.requestAnimationFrame = callback => { frames.push(callback); return frames.length; };
  global.cancelAnimationFrame = () => {};
  const reading = load("src/entities/editor/model/documentReadingState.tsx");
  const scroller = { scrollTop: 0 };
  const { WordPreview } = load("src/features/office-preview/ui/WordPreview.tsx", {
    "../../../entities/editor/model/documentReadingState": reading,
    "../../file-preview/model/filePreview": { readWordChunk: (src, version, chunk, signal) => {
      reads.push({ src, version, chunk, signal });
      return new Promise(() => {});
    } },
    "../../../shared/ui/loading-strip": { LoadingStrip: () => null },
    "./wordChunkLayout": {},
  });
  const view = version => React.createElement(reading.DocumentReadingStateProvider, { activeKey: "a", openKeys: ["a"] },
    React.createElement(WordPreview, { key: version, inspection: { version, word: { chunks: 100, fingerprint: "sha256:source" } },
      src: "http://localhost/projects/p/files/asset?path=a.docx", zoom: 1 }));
  let root;
  try {
    await act(async () => { root = TestRenderer.create(view("v1"), { createNodeMock: element =>
      element.props.className?.includes("word-scroll") ? scroller : { replaceChildren() {} },
    }); });
    assert.deepEqual(reads.map(read => read.chunk), [0, 1]);
    scroller.scrollTop = 70 * 1182 + 30;
    await act(async () => {
      root.root.findByProps({ className: "office-preview__scroll office-preview__word-scroll" }).props.onScroll();
      frames.splice(0).forEach(callback => callback());
    });
    assert(reads[0].signal.aborted && reads[1].signal.aborted);
    assert.deepEqual(reads.slice(2).map(read => read.chunk), [69, 70, 71]);
    assert.equal(root.root.findAllByProps({ className: "office-word-chunk" }).length, 3);
    await act(async () => root.update(view("v2")));
    assert(reads.slice(2, 5).every(read => read.signal.aborted));
    assert.deepEqual(reads.slice(5).map(read => [read.version, read.chunk]), [["v2", 69], ["v2", 70], ["v2", 71]]);
    assert.equal(scroller.scrollTop, 70 * 1182 + 30);
    await act(async () => root.unmount());
    assert(reads.every(read => read.signal.aborted));
  } finally {
    delete global.requestAnimationFrame;
    delete global.cancelAnimationFrame;
  }
});

test("queued Word render skips cancelled work and keeps the next document usable", async () => {
  const { scheduleWordRender } = load("src/features/office-preview/ui/wordChunkLayout.ts");
  const first = new AbortController(), cancelled = new AbortController(), last = new AbortController();
  let release;
  const running = scheduleWordRender(first.signal, () => new Promise(resolve => { release = resolve; }));
  await Promise.resolve();
  await Promise.resolve();
  const skipped = scheduleWordRender(cancelled.signal, async () => assert.fail("cancelled renderer ran"));
  cancelled.abort();
  const completed = scheduleWordRender(last.signal, async () => "next document");
  release();
  await running;
  await assert.rejects(skipped, { name: "AbortError" });
  assert.equal(await completed, "next document");
});

test("Word fetch preserves the resolved tool folder and refuses stale or mismatched chunks", async () => {
  global.window = { location: { href: "http://localhost/" } };
  let returned = { version: "new", chunk: 4 };
  let requested;
  const { readWordChunk } = load("src/features/file-preview/model/filePreview.ts", {
    "../../../services/http/httpClient": { fetchJson: async url => { requested = new URL(url); return returned; } },
  });
  try {
    const src = "http://localhost/tools/categories/c/projects/t/files/asset?path=folder%2Fa.docx&preview_version=new";
    await readWordChunk(src, "new", 4, new AbortController().signal);
    assert.equal(requested.pathname, "/tools/categories/c/projects/t/files/preview/word");
    assert.equal(requested.searchParams.get("path"), "folder/a.docx");
    assert.equal(requested.searchParams.get("version"), "new");
    returned = { version: "old", chunk: 4 };
    await assert.rejects(readWordChunk(src, "new", 4, new AbortController().signal), /版本/);
    returned = { version: "new", chunk: 3 };
    await assert.rejects(readWordChunk(src, "new", 4, new AbortController().signal), /版本/);
  } finally { delete global.window; }
});
