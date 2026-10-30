import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const key = (p, s) => `${p}/${s}`;
let requests, state, watch, result, renderer, intervals, timeouts, nextTimer;
const refs = { activeProjectIdRef: { current: "p" }, activeSessionIdRef: { current: "s" }, isPresentationVisibleRef: { current: true } };
const fakeWindow = () => ({
  setTimeout(fn) { const id = ++nextTimer; timeouts.set(id, fn); return id; },
  clearTimeout(id) { timeouts.delete(id); },
  setInterval(fn) { const id = ++nextTimer; intervals.set(id, fn); return id; },
  clearInterval(id) { intervals.delete(id); },
});
let stopped = 0;
const mocks = {
  react: React,
  "./sessionKey": { buildSessionKey: key },
  "../../../services/project/getProjectConversationMessages": {
    CONVERSATION_MESSAGE_PAGE_SIZE: 80,
    getProjectConversationMessages(p, s, options) {
      return new Promise((resolve, reject) => {
        const request = { p, s, options, resolve, reject, aborted: false };
        requests.push(request);
        options.signal.addEventListener("abort", () => { request.aborted = true; reject(new Error("abort")); }, { once: true });
      });
    },
  },
  "../../../services/project/watchConversationChanges": {
    getConversationMessageState: async () => state,
    watchConversationChanges(_p, _s, handlers) { watch = handlers; return () => { stopped++; }; },
  },
  "../../project-entry/model/projectEntryWarmup": { getCachedProjectEntryWarmup: () => null },
  "./chatMessage": { mapConversationMessages: (items) => items },
  "./chatNotifications": {
    mergeLiveChatNotifications: (old, next) => [...old, ...next.filter((m) => m.role === "system" && !old.some((p) => p.id === m.id))],
    reuseChatMessageRevisions: (_old, next) => next,
  },
};
function load(name) {
  const path = fileURLToPath(new URL(`../src/features/ai-panel/model/${name}.ts`, import.meta.url));
  const source = ts.transpileModule(fs.readFileSync(path, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename: path })(
    (name) => { assert.ok(name in mocks, name); return mocks[name]; }, module, module.exports);
  return module.exports;
}
const { useSessionMessages, mergeHistoryPage } = load("useSessionMessages");
const { useActiveSessionMessagesLoader, useActiveSessionLiveReload } = load("useChatPanelLifecycleEffects");
const reloadSessions = async () => {};
const isSessionStreaming = () => false;
const isNotFoundRequestError = () => false;
function Harness({ active = true, childRunning = true, sync = false }) {
  result = useSessionMessages(refs);
  const options = { activeSessionId: "s", projectId: "p", isActive: active, isSessionStreaming,
    isNotFoundRequestError, reloadSessions, reloadSessionMessages: result.reloadSessionMessages };
  useActiveSessionMessagesLoader(options);
  useActiveSessionLiveReload({ ...options, isActive: active && sync });
  return React.createElement("span", null, String(childRunning));
}
const msg = (id, role = "assistant") => ({ id, message_id: id, role, status: "done", createdAt: Number(id.replace(/\D/g, "")) || 1,
  updatedAt: 1, content: id, thinkingContent: "", isThinkingExpanded: false });
const page = (items, revision = 1, extras = {}) => ({ items, revision, reset_revision: 0,
  has_more: false, next_before_message_id: null, run_outcomes: [], run_attempt_failures: [], ...extras });
async function setup(props = {}) {
  requests = []; state = { revision: 0, reset_revision: 0, project_revision: 0 };
  intervals = new Map(); timeouts = new Map(); nextTimer = 0; stopped = 0;
  globalThis.window = fakeWindow();
  globalThis.document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {} };
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
}
async function respond(index, response) {
  state = { revision: response.revision, reset_revision: response.reset_revision, project_revision: response.revision };
  await act(async () => { requests[index].resolve(response); });
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

test("slow initial history is not cancelled by repeated refreshes or a child becoming idle", async () => {
  await setup();
  await act(async () => {
    for (let i = 0; i < 10; i++) void result.reloadSessionMessages("p", "s", { forceRefresh: true });
    renderer.update(React.createElement(Harness, { childRunning: false }));
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].aborted, false);
  assert.equal(requests[0].options.limit, 80);
  await respond(0, page([msg("m1")]));
  assert.equal(result.sessionMessages["p/s"].length, 1);
  assert.equal(result.loadingSessionKeys.has("p/s"), false);
});

test("stopping a stream attachment releases its wait without cancelling the view's shared history read", async () => {
  await setup();
  const controller = new AbortController();
  let settled = false;
  await act(async () => {
    void result.reloadSessionMessages("p", "s", { signal: controller.signal })
      .then(value => { assert.equal(value, false); settled = true; });
    controller.abort();
  });
  assert.equal(settled, true);
  assert.equal(requests[0].aborted, false);
  await respond(0, page([msg("m1")]));
  assert.equal(result.sessionMessages["p/s"].length, 1);
});

test("idle main conversation receives completion after its child has ended; reconnect deduplicates", async () => {
  await setup({ sync: true });
  await respond(0, page([msg("m1")]));
  await act(async () => {
    state = { revision: 2, reset_revision: 0, project_revision: 2 };
    watch.onChange(state, true);
    renderer.update(React.createElement(Harness, { sync: true, childRunning: false }));
  });
  assert.equal(stopped, 0);
  assert.equal(requests[1].options.afterMessageId, "m1");
  await respond(1, page([msg("m2", "system")], 2, { next_after_message_id: "m2" }));
  await act(async () => { watch.onChange(state, true); });
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m1", "m2"]);
  assert.equal(requests.length, 2);
  assert.equal(intervals.size, 0);
});

test("older pages merge without losing the live tail or acknowledging unseen updates", async () => {
  await setup();
  await respond(0, page([msg("m10"), msg("m11")], 2, { has_more: true, next_before_message_id: "m10" }));
  await act(async () => { void result.loadOlderSessionMessages("p", "s"); });
  assert.equal(requests[1].options.beforeMessageId, "m10");
  await respond(1, page([msg("m8"), msg("m9")], 3));
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m8", "m9", "m10", "m11"]);
  assert.equal(result.historyPages["p/s"].revision, 2);
  assert.equal(result.historyPages["p/s"].after, "m11");
});

test("history reset replaces stale content, while append preserves earlier loaded pages", async () => {
  await setup();
  await respond(0, page([msg("m1"), msg("m2")]));
  state = { revision: 3, reset_revision: 3, project_revision: 3 };
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true }); });
  assert.equal(requests[1].options.afterMessageId, null);
  await respond(1, page([msg("m3")], 3, { reset_revision: 3 }));
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m3"]);
});

test("read failure is visible and retry populates the history", async () => {
  await setup();
  await act(async () => { requests[0].reject(new Error("network")); });
  assert.ok(result.messageLoadErrors["p/s"]);
  assert.equal(result.loadingSessionKeys.size, 0);
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true }); });
  await respond(1, page([msg("m1")]));
  assert.equal(result.messageLoadErrors["p/s"], undefined);
  assert.equal(result.sessionMessages["p/s"].length, 1);
});

test("bounded tail reconciliation preserves older loaded history and removes transient fragments", () => {
  const merged = mergeHistoryPage([msg("m1"), msg("m2"), msg("optimistic3")], [msg("m2"), msg("m3")], { tail: true });
  assert.deepEqual(merged.map((m) => m.id), ["m1", "m2", "m3"]);
});


test("history replacement during a cursor read recovers with a bounded latest page", async () => {
  await setup();
  await respond(0, page([msg("m1")]));
  state = { revision: 2, reset_revision: 0, project_revision: 2 };
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true }); });
  await act(async () => { requests[1].reject(Object.assign(new Error("cursor removed"), { status: 400 })); });
  assert.equal(requests[2].options.limit, 80);
  assert.equal(requests[2].options.afterMessageId, undefined);
  await respond(2, page([msg("m3")], 3, { reset_revision: 3 }));
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m3"]);
});

test("new-message invalidation queued during older-page loading is not lost", async () => {
  await setup();
  await respond(0, page([msg("m10")], 1, { has_more: true, next_before_message_id: "m10" }));
  await act(async () => { void result.loadOlderSessionMessages("p", "s"); });
  state = { revision: 2, reset_revision: 0, project_revision: 2 };
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true }); });
  await respond(1, page([msg("m9")], 2));
  assert.equal(requests[2].options.afterMessageId, "m10");
  await respond(2, page([msg("m11", "system")], 2, { next_after_message_id: "m11" }));
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m9", "m10", "m11"]);
});

test("prepend preserves the visible reading offset in a virtual list", async () => {
  await setup();
  await act(async () => renderer.unmount()); renderer = null;
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  Object.assign(window, { addEventListener() {}, removeEventListener() {}, requestAnimationFrame() { return 1; }, cancelAnimationFrame() {} });
  const parent = { scrollTop: 300, clientHeight: 500, getBoundingClientRect: () => ({ top: 0 }), addEventListener() {}, removeEventListener() {} };
  const list = { getBoundingClientRect: () => ({ top: -parent.scrollTop }) };
  const scrollParentRef = { current: parent };
  const { useVirtualMessageList } = load("useVirtualMessageList");
  function List({ messages }) {
    const view = useVirtualMessageList({ enabled: true, messages, scrollParentRef });
    view.listRef.current = list;
    return null;
  }
  const messages = Array.from({ length: 30 }, (_, i) => msg(`m${i + 10}`));
  await act(async () => { renderer = create(React.createElement(List, { messages })); });
  await act(async () => { renderer.update(React.createElement(List, { messages: [msg("m8"), msg("m9"), ...messages] })); });
  assert.equal(parent.scrollTop, 580);
});


test("stream starting during history read retains live content; idle reconciliation replaces it", async () => {
  await setup();
  await respond(0, page([msg("m1", "user")]));
  let streaming = false;
  state = { revision: 2, reset_revision: 0, project_revision: 2 };
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true, shouldPreserveLocal: () => streaming }); });
  await act(async () => {
    streaming = true;
    result.updateSessionMessages("p", "s", (items) => [...items, { ...msg("optimistic2"), status: "running", content: "still typing" }]);
  });
  await respond(1, page([msg("m2")], 2, { next_after_message_id: "m2" }));
  assert.equal(result.sessionMessages["p/s"].at(-1).content, "still typing");
  streaming = false;
  await act(async () => { void result.reloadSessionMessages("p", "s", { forceRefresh: true, shouldPreserveLocal: () => streaming }); });
  assert.equal(requests[2].options.afterMessageId, null);
  await respond(2, page([msg("m1", "user"), msg("m2")], 2));
  assert.deepEqual(result.sessionMessages["p/s"].map((m) => m.id), ["m1", "m2"]);
});


test("navigation releases an abandoned first-page request and its loading flag", async () => {
  await setup();
  await act(async () => {
    result.pruneSessionMessages({ activeProjectId: "other", activeSessionId: "other", streamingSessionKeys: new Set() });
  });
  assert.equal(requests[0].aborted, true);
  assert.equal(result.loadingSessionKeys.size, 0);
  assert.equal(result.messageLoadErrors["p/s"], undefined);
});
