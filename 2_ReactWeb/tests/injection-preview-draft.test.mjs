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
let requests = [], mutations = [], renderer, props;
const mocks = {
  react: React,
  "../../../entities/project/model/projectFileMutation": {
    publishProjectFileMutation: (mutation) => mutations.push(mutation),
  },
  "../../../services/llm/updateChatInjectionPreview": {
    updateChatInjectionPreview(input, { signal }) {
      return new Promise((resolve, reject) => requests.push({ input, signal, resolve, reject }));
    },
  },
  "../../../services/http/httpErrors": { isAbortError: (error) => error.name === "AbortError" },
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
const { useChatInjectionPreviewDraft } = load(fileURLToPath(new URL(
  "../src/features/ai-panel/model/useChatInjectionPreviewDraft.ts", import.meta.url,
)));
function Harness(options) { useChatInjectionPreviewDraft(options); return null; }
function initial() {
  return {
    projectId: "p", activeSessionId: "s", historyRevision: 1, roleProjectId: null,
    activeModel: { providerId: "provider", modelId: "model", label: "Model" },
    activeReasoningMode: "high", isActiveSessionStreaming: false, supportsImageInput: true,
    settledDraft: { projectId: "p", sessionId: "s", draft: "hello", version: 1 },
    references: [], activeSessionSettings: { max_output_tokens: 4096, temperature: null, top_p: null,
      max_tool_calls: 10, malformed_tool_call_recovery_enabled: true,
      system_prompt: "prompt", tools_enabled: true, enabled_tool_names: ["tool_a"] },
  };
}
async function setup(patch = {}) {
  requests = []; mutations = []; props = { ...initial(), ...patch };
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
}
async function update(patch = {}) {
  props = { ...props, ...patch };
  await act(async () => { renderer.update(React.createElement(Harness, props)); });
}
async function respond(index, result = { ok: true }) {
  await act(async () => { requests[index].resolve(result); });
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

test("500 idle list refreshes do not repeat preview save or abort the pending save", async () => {
  await setup();
  for (let index = 0; index < 500; index++) {
    await update({
      activeModel: { ...props.activeModel, label: `display-only ${index}` },
      activeSessionSettings: Object.fromEntries(Object.entries(props.activeSessionSettings).reverse()),
      references: [...props.references],
      settledDraft: { ...props.settledDraft, version: index + 2 },
    });
    if (index === 100) await respond(0);
  }
  assert.equal(requests.length, 1);
  assert.equal(requests[0].signal.aborted, false);
  assert.equal(mutations.length, 1);
});

test("real draft, settings, references, history, model and role changes update previews", async () => {
  await setup(); await respond(0);
  const patches = [
    { settledDraft: { ...props.settledDraft, draft: "changed" } },
    { activeSessionSettings: { ...props.activeSessionSettings, enabled_tool_names: ["tool_b"] } },
    { references: [{ type: "file", reference: { fileName: "chart.png", filePath: "charts/chart.png", kind: "file" } }] },
    { historyRevision: 2 },
    { activeModel: { ...props.activeModel, modelId: "another-model" } },
    { roleProjectId: "role-b" },
  ];
  for (const [index, patch] of patches.entries()) {
    await update(patch);
    assert.equal(requests.length, index + 2);
    await respond(index + 1);
  }
  assert.equal(requests[1].input.messages[0].content, "changed");
  assert.equal(requests[3].input.messages[0].content_parts[0].image_ref.path, "charts/chart.png");
  assert.equal(mutations.length, 7);
});

test("history loading and model output suspend draft previews; idle resume rebuilds once", async () => {
  await setup({ historyRevision: null });
  assert.equal(requests.length, 0);
  await update({ historyRevision: 0 });
  assert.equal(requests.length, 1);
  await update({ isActiveSessionStreaming: true });
  assert.equal(requests[0].signal.aborted, true);
  await respond(0);
  assert.equal(mutations.length, 0);
  await update({ historyRevision: 10 });
  assert.equal(requests.length, 1);
  await update({ isActiveSessionStreaming: false });
  assert.equal(requests.length, 2);
  await respond(1);
  assert.equal(mutations.length, 1);
});

test("switching sessions ignores a late result and waits for the matching draft", async () => {
  await setup();
  await update({ activeSessionId: "next" });
  await respond(0);
  assert.equal(requests[0].signal.aborted, true);
  assert.equal(requests.length, 1);
  assert.equal(mutations.length, 0);
  await update({ settledDraft: { ...props.settledDraft, sessionId: "next" } });
  assert.equal(requests.length, 2);
  await respond(1);
  assert.ok(mutations[0].node.path.includes("/next/"));
});

test("failed or unavailable previews do not emit a file change or cause a retry loop", async () => {
  await setup();
  await act(async () => { requests[0].reject(new Error("unavailable")); });
  await update({ activeSessionSettings: { ...props.activeSessionSettings } });
  assert.equal(requests.length, 1);
  assert.equal(mutations.length, 0);
  await update({ settledDraft: { ...props.settledDraft, draft: "retry with new content" } });
  await respond(1, { ok: false });
  assert.equal(mutations.length, 0);
});
