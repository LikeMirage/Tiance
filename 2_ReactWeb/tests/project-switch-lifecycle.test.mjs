import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";
import React from "react";
import * as jsx from "react/jsx-runtime";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(path, mocks = {}) {
  const file = new URL(`../src/${path}`, import.meta.url);
  const js = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  const imports = { react: React, "react/jsx-runtime": jsx, ...mocks };
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file.pathname })(
    name => { if (name in imports) return imports[name]; throw new Error(`Unmocked ${name}`); }, module, module.exports);
  return module.exports;
}

const { useWorkspaceConversationSelection } = load("pages/workspace/model/useWorkspaceConversationSelection.ts", {
  "../../../features/ai-panel/model/conversationSelectionMachine": load("features/ai-panel/model/conversationSelectionMachine.ts"),
  "../../../features/ai-panel/model/createDefaultConversation": { createDefaultConversation() { throw new Error("Unexpected creation"); } },
});

async function mountSelection(t, onSelectProject = () => true) {
  let current, renderer;
  const snapshots = [];
  const stable = { onSelectProject, onExpandProject: onSelectProject, onConfirmProjectSession() {} };
  function Harness({ projectId, selectedSessionId }) {
    current = useWorkspaceConversationSelection({ ...stable, projectId, selectedSessionId });
    // Layout effects capture the first commit, before project_changed runs.
    React.useLayoutEffect(() => { snapshots.push({ projectId, visible: current.visibleChatSession }); });
    return null;
  }
  await act(async () => { renderer = create(React.createElement(Harness, { projectId: "a", selectedSessionId: "a-session" })); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  return { snapshots, get current() { return current; }, async update(projectId, selectedSessionId) {
    await act(async () => renderer.update(React.createElement(Harness, { projectId, selectedSessionId })));
  } };
}

test("快速切项目时首帧和后续帧均不向总览暴露旧项目", async t => {
  const h = await mountSelection(t);
  await act(async () => h.current.handleChatActiveSessionChange("a", "a-session"));
  for (const id of ["b", "a", "c", null, "b"]) {
    const before = h.snapshots.length;
    await h.update(id, id ? `${id}-session` : null);
    const frames = h.snapshots.slice(before);
    assert.ok(frames.length > 0);
    for (const frame of frames) assert.equal(frame.visible?.projectId ?? null, id);
    if (id) await act(async () => h.current.handleChatActiveSessionChange(id, `${id}-session`));
  }
});

test("跨项目选择仍保留明确会话请求，旧项目通知不能覆盖新选择", async t => {
  let resolveActivation;
  const h = await mountSelection(t, () => new Promise(resolve => { resolveActivation = resolve; }));
  let completion;
  await act(async () => { completion = h.current.handleSelectOverviewSession("b", "b-selected"); });
  assert.equal(h.current.visibleChatSession.projectId, "a");
  assert.equal(h.current.chatSessionSelectionRequest.projectId, "b");
  await h.update("b", "b-old");
  await act(async () => { resolveActivation(true); });
  await act(async () => h.current.handleChatActiveSessionChange("a", "a-session"));
  assert.deepEqual(h.current.visibleChatSession, { projectId: "b", sessionId: "b-selected" });
  await act(async () => h.current.handleChatActiveSessionChange("b", "b-selected"));
  assert.equal(await completion, true);
  assert.equal(h.current.chatSessionSelectionRequest, null);
});

test("界面异常显示恢复入口，错误记录有上限且存储失败不影响恢复", async t => {
  let saved = "invalid json", reloads = 0, dismissed = 0;
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: { getItem: () => saved, setItem: (_key, value) => { saved = value; } },
    location: { reload: () => { reloads++; } },
  };
  t.after(() => { globalThis.window = previousWindow; });
  t.mock.method(console, "error", () => {});
  const logging = load("app/model/frontendErrorLog.ts");
  for (let index = 0; index < 8; index++) logging.recordFrontendError(new Error(`failure-${index}`), { componentStack: "x".repeat(20000) });
  const records = JSON.parse(saved);
  assert.equal(records.length, 5);
  assert.equal(records[0].message, "failure-3");
  assert.equal(records.at(-1).componentStack.length, 16000);
  globalThis.window.localStorage.setItem = () => { throw new Error("Storage full"); };
  const { WorkspaceErrorBoundary } = load("app/ui/WorkspaceErrorBoundary.tsx", {
    "../../shared/i18n": { useI18n: () => ({ t: key => key }) },
    "../../shared/model/startup-timing/startupTiming": { dismissFrontendBootPlaceholder: () => { dismissed++; } },
    "../model/frontendErrorLog": logging,
    "./workspace-error-boundary.css": {},
  });
  function Crash() { throw new Error("render crash"); }
  let renderer;
  await act(async () => { renderer = create(React.createElement(WorkspaceErrorBoundary, null, React.createElement(Crash))); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  assert.equal(renderer.root.findByProps({ role: "alert" }).type, "section");
  renderer.root.findByType("button").props.onClick();
  assert.equal(reloads, 1);
  assert.equal(dismissed, 1);
});
