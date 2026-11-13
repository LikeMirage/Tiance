import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const noop = () => {};
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
let streams, history, lists, renderer, result, controllers, leases, options, messages, status;
let nextId = 0;
const mockStream = (_request, handlers, { signal }) => {
  const stream = deferred();
  streams.push({ ...stream, signal, handlers });
  signal.addEventListener("abort", () => stream.reject(new DOMException("aborted", "AbortError")), { once: true });
  return stream.promise;
};
const mocks = {
  react: React,
  "../../../entities/llm-usage/model/usageRefreshEvents": { emitLlmUsageChanged: noop },
  "../../../entities/llm-chat/model/projectConversationEvents": { dispatchProjectConversationUpdated: noop },
  "../../../services/project/createProjectConversation": {},
  "../../../services/llm/streamChatCompletion": { streamChatCompletion: mockStream },
  "../../../services/llm/resumeChatCompletionStream": { resumeChatCompletionStream: (p, s, cb, signal) => mockStream({}, {}, { signal }) },
  "../../../services/llm/conversationStreamErrors": { isConversationStreamResyncRequired: () => false },
  "../../../services/http/httpClient": { HttpRequestError: class extends Error {
    constructor(message, status, code) { super(message); this.status = status; this.code = code; }
  } },
  "../../../services/http/httpErrors": { isAbortError: e => e.name === "AbortError" },
  "../../../shared/model/createUuid": { createUuid: () => String(++nextId) },
  "./sessionKey": { buildSessionKey: (p, s) => `${p}:${s}` },
  "../../conversation-runtime/model/conversationRunRequest": { buildConversationRunRequest: x => x },
  "./conversationReferences": { hasConversationReferences: () => false },
  "./conversationDraftReferences": { emptyConversationDraftReferences: () => ({}), toConversationDraftReferences: x => x },
  "./chatStreamAccumulator": { createChatStreamAccumulator: ({ assistantId }) => ({
    clearFlushTimer: noop, finalizeCancelled: noop, finalizeCompleted: noop, flushNow: noop, handleEvent: noop,
    hadError: () => false, getAssistantId: () => assistantId,
  }) },
  "../../conversation-runtime/model/chatStreamEventSideEffects": { processChatStreamEventSideEffects: async () => true },
  "./chatStreamEventSequence": { clearChatStreamEventSequence: noop, processSequencedChatStreamEvent: async (_key, _event, _state, fn) => fn() },
  "./conversationStreamResume": {
    prepareConversationStreamResume: (messages, id) => ({ assistantMessage: { id }, messages, checkpointMessageId: null }),
  },
};
function loadSource(relativePath) {
  const path = fileURLToPath(new URL(`../src/${relativePath}.ts`, import.meta.url));
  const source = ts.transpileModule(fs.readFileSync(path, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename: path })(
    (name) => { assert.ok(name in mocks, name); return mocks[name]; }, module, module.exports);
  return module.exports;
}
const load = name => loadSource(`features/ai-panel/model/${name}`);
const runtimeModule = loadSource("entities/llm-chat/model/conversationRuntime");
mocks["../../../entities/llm-chat/model/conversationRuntime"] = runtimeModule;
const { useChatGeneration } = load("useChatGeneration");
const { useDetachedConversationStream } = load("useDetachedConversationStream");
const { useChatStreamControllers } = load("useChatStreamControllers");
const { SessionStreamingRegistry } = load("sessionStreamingRegistry");
function Harness({ detached }) {
  controllers = useChatStreamControllers();
  result = useChatGeneration({ ...options, ...controllers });
  useDetachedConversationStream({ ...options, ...controllers, isActive: detached,
    activeSessionKey: "p:s", streamingEnabled: true, streamingSessionKeys: leases.keys(), runtimeStatus: "running" });
  return null;
}
async function setup(detached = false) {
  streams = []; history = []; lists = []; messages = []; status = "idle";
  runtimeModule.conversationRuntime = new runtimeModule.ConversationRuntimeStore();
  leases = new SessionStreamingRegistry();
  globalThis.window = { setTimeout: noop };
  const model = { providerId: "provider", modelId: "model" };
  options = {
    activeModel: model, models: [model], projectId: "p", activeSessionId: "s",
    activeProjectIdRef: { current: "p" }, activeSessionIdRef: { current: "s" },
    unavailableProjectIdRef: { current: null }, stoppingSessionKeysRef: { current: new Set() },
    canStartConversation: true, draft: "hello", references: {}, isActiveSessionBusy: false,
    sessions: [{ session_id: "s", provider_id: "provider", model_id: "model", settings: { streaming_enabled: true } }],
    markSessionStreaming: key => leases.acquire(key), unmarkSessionStreaming: (key, lease) => leases.release(key, lease),
    setSessionRuntimeStatus: (_p, _s, value) => { status = value; },
    updateSessionMessages: (_p, _s, fn) => { messages = fn(messages); },
    reloadSessionMessages: () => { const task = deferred(); history.push(task); return task.promise; },
    reloadSessions: () => { const task = deferred(); lists.push(task); return task.promise; },
    reloadSessionUsageSummary: () => new Promise(() => {}),
    isSessionMessagesPresented: () => true, isThinkingStuckToBottom: () => false,
    setDraft: noop, saveSessionState: noop, restoreUnsentInput: noop, preserveCurrentView: noop, showChatView: noop,
    publishCurrentDraftSnapshot: noop, scrollThinkingContentToBottom: noop,
    streamEventSequenceState: {}, isNotFoundRequestError: () => false,
  };
  await act(async () => { renderer = create(React.createElement(Harness, { detached })); });
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

test("aborted send releases stream ownership before a slow list refresh and late cleanup cannot erase a new send", async () => {
  await setup();
  let first, second;
  await act(async () => { first = result.send(); });
  assert.equal(leases.has("p:s"), true);
  assert.equal(runtimeModule.conversationRuntime.status("p", "s", "idle"), "running");
  await act(async () => controllers.abortSessionStream("p:s"));
  assert.equal(lists.length, 1);
  assert.equal(leases.has("p:s"), false);
  assert.equal(runtimeModule.conversationRuntime.status("p", "s", "idle"), "idle");
  assert.equal(status, "running", "transport abort alone is not a server stop acknowledgement");
  await act(async () => { second = result.send(); });
  assert.equal(streams.length, 2, "the old send lock cannot remain held by history refresh");
  await act(async () => { lists[0].resolve(); await first; });
  assert.equal(leases.has("p:s"), true);
  assert.equal(runtimeModule.conversationRuntime.status("p", "s", "idle"), "running");
  assert.equal(streams[1].signal.aborted, false);
  await act(async () => controllers.abortSessionStream("p:s"));
  await act(async () => { lists[1].resolve(); await second; });
});

test("completed stream publishes idle without waiting for history and usage reloads", async () => {
  await setup();
  let sending;
  await act(async () => { sending = result.send(); });
  await act(async () => streams[0].resolve());
  assert.equal(history.length, 1);
  assert.equal(status, "idle");
  assert.equal(leases.has("p:s"), false);
  await act(async () => history[0].resolve(true));
  await act(async () => { lists[0].resolve(); await sending; });
});

test("resumed stream uses the same stop controller and does not wait for usage statistics", async () => {
  await setup(true);
  await act(async () => history[0].resolve(true));
  assert.equal(streams.length, 1, "usage request is still unresolved");
  assert.equal(leases.has("p:s"), true);
  await act(async () => controllers.abortSessionStream("p:s"));
  assert.equal(streams[0].signal.aborted, true);
  assert.equal(leases.has("p:s"), false);
});

test("pre-acceptance stream error restores input and survives authoritative history replacement", async () => {
  await setup();
  const recovered = [];
  options.restoreUnsentInput = (...args) => recovered.push(args);
  options.reloadSessionMessages = async () => { messages = []; return true; };
  options.reloadSessionUsageSummary = async () => {};
  options.reloadSessions = async () => {};
  await act(async () => renderer.update(React.createElement(Harness, { detached: false })));
  let sending;
  await act(async () => { sending = result.send(); });
  await act(async () => {
    await streams[0].handlers.onEvent({ kind: "error", error: "会话生成任务异常终止。", error_code: "conversation_run_failed" });
    streams[0].resolve();
    await sending;
  });
  assert.deepEqual(recovered, [["p", "s", "hello", {}]]);
  assert.equal(messages.length, 0, "no false sent user message remains");
  assert.equal(result.sendError, "会话生成任务异常终止。");
  assert.equal(leases.has("p:s"), false);
  assert.equal(status, "error");
});

test("a rejected request restores its original session after navigation", async () => {
  await setup();
  const recovered = [];
  options.restoreUnsentInput = (...args) => recovered.push(args);
  options.reloadSessionMessages = async () => true;
  options.reloadSessionUsageSummary = async () => {};
  options.reloadSessions = async () => {};
  await act(async () => renderer.update(React.createElement(Harness, { detached: false })));
  let sending;
  await act(async () => { sending = result.send(); });
  options.activeProjectIdRef.current = "other-project";
  options.activeSessionIdRef.current = "other-session";
  await act(async () => {
    streams[0].reject(new Error("connection failed"));
    await sending;
  });
  assert.equal(recovered.length, 1);
  assert.deepEqual(recovered[0].slice(0, 3), ["p", "s", "hello"]);
  assert.equal(result.sendError, "connection failed");
});

test("an accepted failed run is not put back into the composer as an unsent draft", async () => {
  await setup();
  let recovered = false;
  options.restoreUnsentInput = () => { recovered = true; };
  options.reloadSessionMessages = async () => true;
  options.reloadSessionUsageSummary = async () => {};
  options.reloadSessions = async () => {};
  await act(async () => renderer.update(React.createElement(Harness, { detached: false })));
  let sending;
  await act(async () => { sending = result.send(); });
  await act(async () => {
    await streams[0].handlers.onEvent({ kind: "conversation_run_started", user_message_id: "u", run_id: "run" });
    await streams[0].handlers.onEvent({ kind: "error", error: "upstream failed" });
    streams[0].resolve();
    await sending;
  });
  assert.equal(recovered, false);
  assert.equal(result.sendError, null);
});
