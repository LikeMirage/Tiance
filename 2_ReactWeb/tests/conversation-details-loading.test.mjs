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
let requests = [], saves = [], lists = [], renderer, value, props;
const mocks = {
  react: React,
  "./chatPanelRequestErrors": { isNotFoundRequestError: () => false },
  "../../../entities/llm-chat/model/projectConversationEvents": { dispatchProjectConversationUpdated() {} },
  "../../project-entry/model/projectEntryWarmup": { getCachedProjectEntryWarmup: () => null },
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
async function setup() {
  requests = []; saves = []; lists = [];
  props = { projectId: "p", activeProjectIdRef: { current: null }, activeSessionIdRef: { current: null },
    abortProjectStreams() {}, showChatView() {} };
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
  await act(async () => { lists[0].resolve(response()); });
  assert.equal(value.draft, "draft-a");
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

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
});
