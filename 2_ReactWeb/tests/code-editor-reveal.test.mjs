import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const { Facet, StateEffect } = require("@codemirror/state");
function load(relative, mocks = {}) {
  const file = new URL(`../src/${relative}`, import.meta.url);
  const code = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: file.pathname })(
    name => name in mocks ? mocks[name] : require(name), module, module.exports,
  );
  return module.exports;
}

test("CodeEditor selects its live buffer, centers it and acknowledges without editing; changed selections fail", async t => {
  const originals = { window: globalThis.window, requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame };
  let root;
  t.after(async () => {
    if (root) await act(async () => root.unmount());
    Object.assign(globalThis, originals);
  });
  const timers = new Map(), frames = new Map();
  let serial = 0;
  globalThis.window = {
    setTimeout: callback => { timers.set(++serial, callback); return serial; },
    clearTimeout: id => timers.delete(id),
  };
  globalThis.requestAnimationFrame = callback => { frames.set(++serial, callback); return serial; };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  const flushFrames = async () => {
    for (let i = 0; i < 2; i++) await act(async () => {
      const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback());
    });
  };
  const scrolling = StateEffect.define();
  const centers = [];
  let view, dirty = 0, stops = 0;
  const commits = [];
  const stopRestore = () => stops++;
  class TestEditorView {
    static updateListener = Facet.define();
    static scrollIntoView(position, options) { return scrolling.of({ position, options }); }
    constructor({ state }) {
      this.state = state;
      this.scrollDOM = this.dom = this.contentDOM = { addEventListener() {}, removeEventListener() {} };
      view = this;
    }
    dispatch(spec) {
      const transaction = this.state.update(spec);
      this.state = transaction.state;
      for (const effect of transaction.effects) if (effect.is(scrolling)) centers.push(effect.value);
      for (const listener of this.state.facet(TestEditorView.updateListener)) listener(transaction);
    }
    focus() { this.focused = true; }
    destroy() {}
  }
  const reveal = load("entities/editor/model/documentReveal.ts");
  const context = load("entities/editor/model/documentRevealContext.tsx");
  const { CodeEditor } = load("features/editor/ui/CodeEditor.tsx", {
    "@codemirror/view": { EditorView: TestEditorView },
    "../../../entities/editor/model/documentReadingState": { useDocumentReadingScroll: () => stopRestore },
    "../../../entities/editor/model/documentRevealContext": context,
    "../../../entities/editor/model/documentReveal": reveal,
    "./editor-config": { createEditorExtensions: () => [] },
    "../../file-preview/model/previewPolicy": { needsPlainTextMode: () => false },
    "./editor.css": {},
  });
  const render = request => React.createElement(context.DocumentRevealContext.Provider, { value: request },
    React.createElement(CodeEditor, { value: "saved text", languageId: "plaintext",
      onChange: value => commits.push(value), onDirty: () => dirty++ }));
  await act(async () => { root = create(render(null), { createNodeMock: () => ({}) }); });
  await act(async () => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: "unsaved\n选择这一行\nend" } }));
  assert.equal(dirty, 1);
  assert.deepEqual(commits, []); // React still holds the old value during the 220 ms debounce.
  const liveDocument = view.state.doc;
  const pending = reveal.createDocumentRevealRequest({ type: "text", text: "选择这一行" }, new AbortController().signal);
  let completed = false;
  pending.result.then(() => { completed = true; });
  await act(async () => root.update(render(pending.request)));
  assert.equal(completed, false);
  assert.equal(view.state.sliceDoc(view.state.selection.main.from, view.state.selection.main.to), "选择这一行");
  assert.equal(view.state.doc, liveDocument);
  assert.equal(view.focused, true);
  assert.deepEqual(centers, [{ position: 10, options: { y: "center" } }]);
  assert.equal(stops, 1);
  assert.equal(dirty, 1);
  assert.deepEqual(commits, []);
  await flushFrames();
  assert.equal((await pending.result).start_line, 2);

  // Input order, not document order, controls the displayed primary range.
  const multiple = reveal.createDocumentRevealRequest({ type: "text_ranges", ranges: [
    { type: "text", text: "end" }, { type: "line_range", start_line: 1, end_line: 1 },
  ] }, new AbortController().signal);
  await act(async () => root.update(render(multiple.request)));
  assert.equal(view.state.selection.ranges.length, 2);
  assert.equal(view.state.sliceDoc(view.state.selection.main.from, view.state.selection.main.to), "end");
  assert.deepEqual(centers.at(-1), { position: 15, options: { y: "center" } });
  await flushFrames();
  assert.deepEqual((await multiple.result).ranges.map(range => range.start_line), [3, 1]);

  const beforeInvalid = view.state.selection;
  const invalid = reveal.createDocumentRevealRequest({ type: "text_ranges", ranges: [
    { type: "text", text: "选择这一行" }, { type: "text", text: "does not exist" },
  ] }, new AbortController().signal);
  const invalidResult = assert.rejects(invalid.result, error => error.code === "TEXT_NOT_FOUND" && error.details.range_index === 2);
  await act(async () => root.update(render(invalid.request)));
  await invalidResult;
  assert.equal(view.state.selection, beforeInvalid);

  const overlapping = reveal.createDocumentRevealRequest({ type: "text_ranges", ranges: [
    { type: "text", text: "选择" }, { type: "line_range", start_line: 2, end_line: 2 },
    { type: "text", text: "end" },
  ] }, new AbortController().signal);
  await act(async () => root.update(render(overlapping.request)));
  assert.equal(view.state.selection.ranges.length, 2);
  await flushFrames();
  assert.equal((await overlapping.result).ranges.length, 3);
  assert.equal(view.state.doc, liveDocument);
  assert.equal(dirty, 1);

  const interrupted = reveal.createDocumentRevealRequest({ type: "line_range", start_line: 1, end_line: 1 }, new AbortController().signal);
  const rejected = assert.rejects(interrupted.result, { code: "SELECTION_CHANGED" });
  await act(async () => root.update(render(interrupted.request)));
  view.dispatch({ selection: { anchor: 0 } });
  await flushFrames();
  await rejected;
});
