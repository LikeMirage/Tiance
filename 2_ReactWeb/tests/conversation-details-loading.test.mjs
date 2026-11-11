import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.window = { setTimeout, clearTimeout, setInterval, clearInterval };
let requests = [], saves = [], lists = [], renderer, value, props, warmup = null;
let serverChangeListener;
const mocks = {
  react: React,
  "./chatPanelRequestErrors": { isNotFoundRequestError: () => false },
  "../../../entities/llm-chat/model/projectConversationEvents": { dispatchProjectConversationUpdated() {},
    listenProjectConversationUpdated(listener) { serverChangeListener = listener; return () => { serverChangeListener = null; }; } },
  "../../project-entry/model/projectEntryWarmup": { getCachedProjectEntryWarmup: () => warmup },
  "../../../services/project/saveProjectConversationState": {
    async saveProjectConversationState(pid, input) { saves.push({ pid, input }); },
  },
  "../../../services/project/getProjectConversationDetail": {
    getProjectConversationDetail(pid, sid, signal) {
      return new Promise((resolve, reject) => {
        requests.push({ pid, sid, signal, resolve, reject });
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    },
  },
  "../../../services/project/getProjectConversationSummaries": {
    loadSelectedConversationList(pid, selectedId, states) {
      return new Promise((resolve, reject) => lists.push({ pid, selectedId, states, resolve, reject }));
    },
  },
};
const modules = new Map();
function load(filename) {
  if (modules.has(filename)) return modules.get(filename);
  const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename })(
    (name) => {
      if (name in mocks) return mocks[name];
      assert.ok(name.startsWith("."), name);
      return load(path.resolve(path.dirname(filename), `${name}.ts`));
    }, module, module.exports);
  modules.set(filename, module.exports);
  return module.exports;
}
const { useConversationSessions } = load(fileURLToPath(new URL(
  "../src/features/ai-panel/model/useConversationSessions.ts", import.meta.url,
)));
const session = (id, full = true) => ({ session_id: id, title: id, updated_at: "now",
  ...(full ? { settings: { system_prompt: `prompt-${id}` } } : {}) });
const state = (draft) => ({ draft, runtime_status: "idle", updated_at: "now", references: [] });
function response(id = "a") { return { project_id: "p", revision: 1, active_session_id: id,
  items: [session("a", id === "a"), session("b", id === "b"), session("c", id === "c")],
  session_states: { a: state(id === "a" ? "draft-a" : ""), b: state(id === "b" ? "draft-b" : ""), c: state("") },
  branch_nodes: [], message_variants: [] }; }
function detail(id) { return { project_id: "p", revision: 2, session: session(id), state: state(`draft-${id}`) }; }
function Harness(options) { value = useConversationSessions(options); return null; }
async function setup(preferredSessionId = null, loaded = response(), cached = null) {
  requests = []; saves = []; lists = [];
  warmup = cached;
  props = { projectId: "p", preferredSessionId, activeProjectIdRef: { current: null }, activeSessionIdRef: { current: null },
    abortProjectStreams() {}, showChatView() {} };
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
  await act(async () => { lists[0]?.resolve(loaded); });
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

test("手机新会话通知刷新列表，保留桌面会话和未发送草稿，不回写手机选择", async () => {
  await setup();
  await act(async () => value.setDraft("desktop typing"));
  const saveCount = saves.length;
  await act(async () => serverChangeListener({ source: "server", kind: "structure", projectId: "p" }));
  const refreshed = response("b");
  refreshed.items.push(session("phone-new", false));
  await act(async () => lists.at(-1).resolve(refreshed));
  assert.equal(value.activeSessionId, "a");
  assert.equal(value.draft, "desktop typing");
  assert.ok(value.sessions.some(s => s.session_id === "phone-new"));
  assert.equal(saves.length, saveCount);
  const count = lists.length;
  await act(async () => {
    serverChangeListener({ source: "server", kind: "structure", projectId: "other" });
    serverChangeListener({ kind: "structure", projectId: "p" });
  });
  assert.equal(lists.length, count, "other projects and local events must not cause a reload loop");
});

test("stale remembered session resolves against the actual list without losing the selected draft", async () => {
  await setup("removed-session");
  assert.equal(value.activeSessionId, "a");
  assert.equal(value.draft, "draft-a");
  assert.equal(requests.some(request => request.sid === "removed-session"), false);
});

test("selection hydrates settings and draft before switching; summaries never overwrite an unloaded draft", async () => {
  await setup();
  await act(async () => { void value.activateSession("b"); });
  assert.equal(value.activeSessionId, "a");
  assert.equal(value.draft, "draft-a");
  assert.equal(saves.some(({ input }) => input.session_drafts?.b === ""), false);
  await act(async () => { requests[0].resolve(detail("b")); });
  assert.equal(value.activeSessionId, "b");
  assert.equal(value.draft, "draft-b");
  assert.equal(value.sessions.find((item) => item.session_id === "b").settings.system_prompt, "prompt-b");
});

test("rapid selection cancels older detail and keeps the latest selected draft", async () => {
  await setup();
  await act(async () => { void value.activateSession("b"); });
  await act(async () => { void value.activateSession("c"); });
  assert.equal(requests[0].signal.aborted, true);
  await act(async () => { requests[1].resolve(detail("c")); requests[0].resolve(detail("b")); });
  assert.equal(value.activeSessionId, "c");
  assert.equal(value.draft, "draft-c");
});

test("a pending list refresh cannot replace newly selected details with a summary", async () => {
  await setup();
  await act(async () => { void value.reloadSessions("p"); void value.activateSession("b"); });
  await act(async () => { requests[0].resolve(detail("b")); });
  await act(async () => { lists[1].resolve(response("a")); });
  assert.equal(value.activeSessionId, "b");
  assert.equal(value.draft, "draft-b");
  assert.equal(lists[2].selectedId, "b");
  await act(async () => { lists[2].resolve(response("b")); });
  assert.equal(value.sessions.find((item) => item.session_id === "b").settings.system_prompt, "prompt-b");
});

test("failure leaves previous session intact and never writes an empty draft for the target", async () => {
  await setup();
  await act(async () => { void value.activateSession("b"); });
  await act(async () => { requests[0].reject(new Error("offline")); });
  assert.equal(value.activeSessionId, "a");
  assert.equal(value.sessionLoadError, "offline");
  assert.equal(saves.some(({ input }) => Object.hasOwn(input.session_drafts ?? {}, "b")), false);
  assert.equal(saves.some(({ input }) => input.active_session_id === "b"), false);
});

test("ordinary project entry restores its own active conversation without a global session hint", async () => {
  await setup(null, response("b"));
  assert.equal(lists[0].selectedId, null);
  assert.equal(value.activeSessionId, "b");
  assert.equal(value.draft, "draft-b");
  assert.equal(saves.some(({ input }) => input.active_session_id), false);
});

test("explicit overview target selected during initial loading is persisted in that project", async () => {
  await setup("b", response("b"));
  assert.equal(lists[0].selectedId, "b");
  assert.equal(value.activeSessionId, "b");
  assert.ok(saves.some(({ pid, input }) => pid === "p" && input.active_session_id === "b"));
  await act(async () => renderer.unmount());
  renderer = null;
  await setup(null, response("b"));
  assert.equal(value.activeSessionId, "b");
  assert.equal(value.draft, "draft-b");
});

test("warmup-selected overview target is persisted even when its cached active ID already matches", async () => {
  await setup("b", response("b"), { conversations: response("b") });
  assert.equal(value.activeSessionId, "b");
  assert.ok(saves.some(({ pid, input }) => pid === "p" && input.active_session_id === "b"));
});

test("late initial response from a previous project cannot persist its selection into the new project", async () => {
  await setup();
  await act(async () => renderer.update(React.createElement(Harness, { ...props, projectId: "q", preferredSessionId: "b" })));
  const pending = lists.find(item => item.pid === "q");
  await act(async () => renderer.update(React.createElement(Harness, { ...props, projectId: "r" })));
  await act(async () => pending.resolve({ ...response("b"), project_id: "q" }));
  assert.equal(saves.some(({ input }) => input.active_session_id === "b"), false);
  assert.equal(value.activeSessionId, null);
});

test("rejected input recovery preserves new typing and references and persists the combined draft", async () => {
  await setup();
  const ref = (id) => ({ type: "file", reference: { id } });
  await act(async () => { value.setDraft("new typing"); });
  await act(async () => {
    const references = value.restoreUnsentInput("p", "a", "rejected message", [ref("old"), ref("shared")], [ref("shared"), ref("new")]);
    assert.deepEqual(references.map(item => item.reference.id), ["old", "shared", "new"]);
    value.publishCurrentDraftSnapshot("p", "a");
  });
  assert.equal(value.draft, "rejected message\n\nnew typing");
  assert.equal(value.settledDraft.draft, value.draft, "finally cannot publish a stale empty draft");
  assert.equal(saves.at(-1).input.session_drafts.a, value.draft);
  assert.deepEqual(saves.at(-1).input.session_references.a.map(item => item.reference.id), ["old", "shared", "new"]);
});

test("rejected input is saved to its original session without replacing the newly selected composer", async () => {
  await setup();
  await act(async () => { value.setDraft(""); value.saveSessionState("p", "a", { draft: "", references: [] }); });
  await act(async () => { void value.activateSession("b"); });
  await act(async () => { requests[0].resolve(detail("b")); });
  await act(async () => { value.restoreUnsentInput("p", "a", "unsent", []); });
  assert.equal(value.draft, "draft-b");
  assert.equal(value.activeSessionId, "b");
  assert.equal(saves.at(-1).input.session_drafts.a, "unsent");
  assert.equal(value.sessionStates.a.draft, "unsent");
});
