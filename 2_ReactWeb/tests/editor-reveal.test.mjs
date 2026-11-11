import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import TestRenderer, { act } from "react-test-renderer";
import { EditorState } from "@codemirror/state";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { parseDocumentRevealTarget, resolveTextReveal, resolveTextReveals, createDocumentRevealRequest } = await vite.ssrLoadModule("/src/entities/editor/model/documentReveal.ts");
const { useDocumentReveal } = await vite.ssrLoadModule("/src/features/document-tabs/model/useDocumentReveal.ts");
const { usePdfReveal } = await vite.ssrLoadModule("/src/features/pdf-preview/model/usePdfReveal.ts");
const { DocumentRevealContext } = await vite.ssrLoadModule("/src/entities/editor/model/documentRevealContext.tsx");
const { createEditorTabsClientToolRegistration } = await vite.ssrLoadModule("/src/features/client-tools/model/editorTabsClientTool.ts");
const lineTarget = { type: "line_range", start_line: 1, end_line: 1 };
const signal = () => new AbortController().signal;

test("text selection preserves whitespace, Unicode and normalized newlines; line bounds include both lines", () => {
  const doc = EditorState.create({ doc: "首行\r\n 目标🙂 \r\n末行\r\n" }).doc;
  const selected = resolveTextReveal(doc, { type: "text", text: " 目标🙂 \r\n末行" });
  assert.equal(doc.sliceString(selected.from, selected.to), " 目标🙂 \n末行");
  assert.equal(selected.start_line, 2);
  assert.equal(selected.end_line, 3);
  assert.equal(selected.end_column, 3);
  const lines = resolveTextReveal(doc, { type: "line_range", start_line: 2, end_line: 3 });
  assert.equal(lines.from, selected.from);
  assert.equal(lines.to, selected.to);
  assert.throws(() => resolveTextReveal(doc, { type: "text", text: "目标🙂\n末行" }), { code: "TEXT_NOT_FOUND" });
  assert.throws(() => resolveTextReveal(doc, { type: "line_range", start_line: 1, end_line: 5 }), { code: "LINE_OUT_OF_RANGE" });
});

test("ambiguous text requires occurrence and counts overlapping matches", () => {
  const doc = EditorState.create({ doc: "banana banana" }).doc;
  assert.throws(() => resolveTextReveal(doc, { type: "text", text: "ana" }), (e) => e.code === "AMBIGUOUS_TEXT" && e.details.match_count === 4);
  assert.equal(resolveTextReveal(doc, { type: "text", text: "ana", occurrence: 2 }).from, 3);
  assert.throws(() => resolveTextReveal(doc, { type: "text", text: "ana", occurrence: 5 }), { code: "OCCURRENCE_OUT_OF_RANGE" });
  for (const target of [null, {}, { type: "text", text: "" }, { type: "text", text: "x", occurrence: 0 },
    { type: "pdf_page", page: 1.5 }, { type: "pdf_page", page: 0 }, { type: "pdf_page", page: 1, text: "x" },
    { type: "line_range", start_line: 3, end_line: 2 }]) {
    assert.throws(() => parseDocumentRevealTarget(target), { code: "INVALID_TARGET" });
  }
});

test("renderer acknowledgement, cancellation and timeout settle once and invalidate late effects", async () => {
  const source = new AbortController();
  const pending = createDocumentRevealRequest(lineTarget, source.signal);
  const rejected = assert.rejects(pending.result, { code: "CANCELLED" });
  source.abort();
  pending.request.complete({ type: "pdf_page", page: 1, total_pages: 1 });
  await rejected;
  assert.equal(pending.request.signal.aborted, true);
  const expired = createDocumentRevealRequest(lineTarget, signal(), 5);
  await assert.rejects(expired.result, { code: "REVEAL_TIMEOUT" });
  const completed = createDocumentRevealRequest(lineTarget, signal());
  const expected = resolveTextReveal(EditorState.create({ doc: "ok" }).doc, lineTarget);
  completed.request.complete(expected);
  completed.request.fail(new Error("late"));
  assert.deepEqual(await completed.result, expected);
});

test("multiple text targets mix lines and literals in input order with no count cap; errors identify the range", () => {
  const doc = EditorState.create({ doc: "first\nsecond\nthird\nfourth" }).doc;
  const target = parseDocumentRevealTarget({ type: "text_ranges", ranges: [
    { type: "text", text: "third" }, { type: "line_range", start_line: 1, end_line: 1 },
  ] });
  const result = resolveTextReveals(doc, target);
  assert.equal(result.type, "text_selections");
  assert.deepEqual(result.ranges.map(range => range.start_line), [3, 1]);
  const many = parseDocumentRevealTarget({ type: "text_ranges", ranges: Array.from({ length: 2048 }, () => lineTarget) });
  assert.equal(resolveTextReveals(doc, many).ranges.length, 2048);
  assert.throws(() => resolveTextReveals(doc, { type: "text_ranges", ranges: [lineTarget, { type: "text", text: "missing" }] }),
    error => error.code === "TEXT_NOT_FOUND" && error.details.range_index === 2);
  assert.throws(() => resolveTextReveals(doc, { type: "text_ranges", ranges: [lineTarget, { type: "line_range", start_line: 1, end_line: 5 }] }),
    error => error.code === "LINE_OUT_OF_RANGE" && error.details.range_index === 2);
  for (const ranges of [[], [{ type: "pdf_page", page: 1 }], [{ type: "text_ranges", ranges: [lineTarget] }], [lineTarget, null]]) {
    assert.throws(() => parseDocumentRevealTarget({ type: "text_ranges", ranges }), { code: "INVALID_TARGET" });
  }
});

function tab(path, extra = {}) {
  return { id: `project:p:${path}`, kind: "text", content: "live", textContentLoaded: true,
    projectId: "p", projectFilePath: path, isDirty: false, isMissing: false, ...extra };
}
async function harness(initial) {
  let current, opens = 0;
  function Harness() {
    const [tabs, setTabs] = useState(initial);
    const [activeTabId, setActive] = useState(initial[0]?.id ?? null);
    const state = useRef({ tabs, activeTabId });
    useLayoutEffect(() => { state.current = { tabs, activeTabId }; }, [tabs, activeTabId]);
    const getSnapshot = useCallback(() => state.current, []);
    const selectTab = useCallback((id) => {
      state.current = { ...state.current, activeTabId: id };
      setActive(id);
    }, []);
    const openNode = useCallback(async (node) => {
      opens++;
      const next = tab(node.path, { textContentLoaded: false });
      state.current = { tabs: [...state.current.tabs, next], activeTabId: next.id };
      setTabs(state.current.tabs); setActive(next.id);
    }, []);
    const { revealProjectFile: reveal } = useDocumentReveal({ getSnapshot, openNode, selectTab, tabs, activeTabId, setTabs });
    current = { reveal, tabs, activeTabId, setTabs, selectTab };
    return null;
  }
  let root;
  await act(async () => { root = TestRenderer.create(React.createElement(Harness)); });
  return { get current() { return current; }, get opens() { return opens; }, root };
}

test("existing dirty tabs are reused without rereading; repeated commands each await their renderer", async () => {
  const h = await harness([tab("a.txt"), tab("b.txt", { isDirty: true })]);
  for (let i = 0; i < 2; i++) {
    let promise;
    await act(async () => { promise = h.current.reveal("p", "b.txt", lineTarget, signal()); });
    assert.equal(h.opens, 0);
    assert.equal(h.current.activeTabId, "project:p:b.txt");
    const pending = h.current.tabs[1].revealRequest;
    assert.ok(pending);
    assert.equal(pending.signal.aborted, false);
    const result = resolveTextReveal(EditorState.create({ doc: "live" }).doc, lineTarget);
    await act(async () => { pending.complete(result); await promise; });
    assert.equal(h.current.tabs[1].revealRequest, undefined);
    assert.equal(h.current.tabs[1].isDirty, true);
    assert.equal(h.current.tabs[1].content, "live");
  }
  await act(async () => h.root.unmount());
});

test("Office previews reject text reveals without opening tabs and report supported actions", async () => {
  const h = await harness([tab("a.txt")]);
  for (const path of ["review.docx", "report.xlsx", "slides.pptx", "table.csv"]) {
    await assert.rejects(h.current.reveal("p", path, { type: "text", text: "target" }, signal()), error => {
      assert.equal(error.code, "UNSUPPORTED_TARGET");
      assert.equal(error.details.file_kind, "office");
      assert.deepEqual(error.details.supported_target_types, []);
      assert.equal(error.details.suggested_action, "open_file");
      return true;
    });
  }
  assert.equal(h.opens, 0);
  assert.equal(h.current.activeTabId, "project:p:a.txt");
  await act(async () => h.root.unmount());
});

test("new file waits for renderer, and switching tabs, missing files or a new request cannot report success", async () => {
  const h = await harness([tab("a.txt")]);
  let promise;
  await act(async () => { promise = h.current.reveal("p", "b.txt", lineTarget, signal()); });
  assert.equal(h.opens, 1);
  assert.equal(h.current.tabs[1].textContentLoaded, false);
  const interrupted = assert.rejects(promise, { code: "NAVIGATION_INTERRUPTED" });
  await act(async () => h.current.selectTab("project:p:a.txt"));
  await interrupted;
  await act(async () => { promise = h.current.reveal("p", "b.txt", lineTarget, signal()); });
  const missing = assert.rejects(promise, { code: "FILE_NOT_FOUND" });
  await act(async () => h.current.setTabs((tabs) => tabs.map(t => t.id.endsWith("b.txt") ? { ...t, isMissing: true } : t)));
  await missing;
  await act(async () => { promise = h.current.reveal("p", "a.txt", lineTarget, signal()); });
  const replaced = assert.rejects(promise, { code: "SUPERSEDED" });
  const controller = new AbortController();
  let next;
  await act(async () => { next = h.current.reveal("p", "a.txt", lineTarget, controller.signal); });
  await replaced;
  const cancelled = assert.rejects(next, { code: "CANCELLED" });
  await act(async () => controller.abort());
  await cancelled;
  await act(async () => h.root.unmount());
});

test("bridge validates targets and foreground scope, propagates signal and waits for display acknowledgement", async () => {
  let finish, calls = 0;
  const controller = new AbortController();
  const registration = createEditorTabsClientToolRegistration({ getProjectId: () => "p", getEditorTabs: () => ({
    getSnapshot: () => ({ activeTabId: "project:p:a.txt", tabs: [tab("a.txt")] }),
    revealProjectFile: (_project, _path, _target, received) => {
      calls++;
      assert.equal(received, controller.signal);
      return new Promise(resolve => { finish = resolve; });
    },
  }) });
  assert.equal(registration.capability.version, 3);
  const request = (target, project = "p") => ({ project_id: project, arguments: JSON.stringify({ action: "reveal_file", path: "a.txt", target }) });
  assert.equal((await registration.execute(request({ type: "pdf_page", page: 0 }))).content.error_code, "INVALID_TARGET");
  assert.equal((await registration.execute(request(lineTarget, "background"))).content.error_code, "PROJECT_NOT_ACTIVE");
  assert.equal(calls, 0);
  let settled = false;
  const result = registration.execute(request(lineTarget), { signal: controller.signal }).then(value => { settled = true; return value; });
  await Promise.resolve();
  assert.equal(settled, false);
  finish(resolveTextReveal(EditorState.create({ doc: "live" }).doc, lineTarget));
  assert.equal((await result).content.displayed, true);
});

test("PDF jumps only after loading, validates page bounds and acknowledges the actual rendered page (including repeated jumps)", async () => {
  const frames = new Map(); let nextFrame = 0;
  globalThis.requestAnimationFrame = (callback) => { frames.set(++nextFrame, callback); return nextFrame; };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  const flushFrames = async () => {
    for (let i = 0; i < 2; i++) await act(async () => { const batch = [...frames.values()]; frames.clear(); batch.forEach(f => f()); });
  };
  const pdf = { numPages: 8 };
  const element = { scrollHeight: 1000, clientHeight: 400, scrollWidth: 800, clientWidth: 600 };
  const viewport = { current: element };
  const selections = [];
  let restoreStops = 0;
  const common = { errorMessage: null, scale: 1, viewport, stopReadingRestore: () => restoreStops++, selectPage: page => selections.push(page) };
  function Reader(props) { usePdfReveal({ ...common, ...props }); return null; }
  const view = (request, props) => React.createElement(DocumentRevealContext.Provider, { value: request }, React.createElement(Reader, props));
  const pending = createDocumentRevealRequest({ type: "pdf_page", page: 4 }, signal());
  let root;
  await act(async () => { root = TestRenderer.create(view(pending.request, { pdfDocument: null, currentPage: 1, rendered: null })); });
  assert.deepEqual(selections, []);
  await act(async () => root.update(view(pending.request, { pdfDocument: pdf, currentPage: 1, rendered: null })));
  assert.deepEqual(selections, [4]);
  const ready = { pdfDocument: pdf, currentPage: 4, rendered: { document: pdf, page: 4, scale: 1, state: "ready" } };
  await act(async () => root.update(view(pending.request, ready)));
  await flushFrames();
  assert.equal((await pending.result).page, 4);
  assert.equal(element.scrollTop, 300);
  assert.equal(element.scrollLeft, 100);
  const repeat = createDocumentRevealRequest({ type: "pdf_page", page: 4 }, signal());
  element.scrollTop = 0;
  await act(async () => root.update(view(repeat.request, ready)));
  await flushFrames();
  await repeat.result;
  assert.equal(element.scrollTop, 300);
  assert.ok(restoreStops >= 4);
  const invalid = createDocumentRevealRequest({ type: "pdf_page", page: 9 }, signal());
  const invalidResult = assert.rejects(invalid.result, { code: "PAGE_OUT_OF_RANGE" });
  await act(async () => root.update(view(invalid.request, ready)));
  await invalidResult;
  assert.deepEqual(selections, [4, 4]);
  await act(async () => root.unmount());
  delete globalThis.requestAnimationFrame;
  delete globalThis.cancelAnimationFrame;
});
