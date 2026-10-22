import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../", import.meta.url));

async function mount(t) {
  const requests = [];
  const effects = [];
  const mocks = {
    react: React,
    "../../../services/http/httpErrors": { isAbortError: error => error?.name === "AbortError" },
    "../../../services/project/forkProjectConversation": {
      forkProjectConversation: (projectId, sessionId, input) => new Promise((resolve, reject) => {
        requests.push({ projectId, sessionId, input, resolve, reject });
      }),
    },
    "./conversationForkDraft": {
      buildConversationForkDraft: message => ({ draft: message.content, references: message.references }),
    },
    "./conversationMessageVariants": { resolveMessageVariantNavigation: () => null },
  };
  const file = path.join(root, "src/features/ai-panel/model/useConversationBranching.ts");
  const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file })(
    name => name in mocks ? mocks[name] : require(name), module, module.exports,
  );
  let current;
  let renderer;
  let mounted = true;
  function Harness({ sessionId, projectId }) {
    current = module.exports.useConversationBranching({
      activeSessionId: sessionId, projectId, isActiveSessionBusy: false,
      messageVariants: [], sessions: [], onActivateSession: () => {}, onNavigateToVariant: () => {},
      applyForkResult: result => effects.push(["apply", result.session.session_id]),
      onDraftReferencesChange: refs => effects.push(["references", refs]),
      reloadSessionMessages: async (project, session) => effects.push(["reload", project, session]),
    });
    return null;
  }
  await act(async () => { renderer = create(React.createElement(Harness, { sessionId: "A", projectId: "P" })); });
  const unmount = async () => {
    if (!mounted) return;
    await act(async () => renderer.unmount());
    mounted = false;
  };
  t.after(unmount);
  return {
    requests, effects, unmount,
    get current() { return current; },
    select: async (sessionId, projectId = "P") => {
      await act(async () => renderer.update(React.createElement(Harness, { sessionId, projectId })));
    },
    start: async (id = "message-A") => {
      let completion;
      await act(async () => {
        completion = current.forkUserMessage({
          id, role: "user", status: "done", content: `draft-${id}`, references: [id],
        });
      });
      return { completion };
    },
    finish: async (index, operation, error = null) => {
      await act(async () => {
        if (error) requests[index].reject(error);
        else requests[index].resolve({ session: { session_id: `branch-${index}` } });
        await operation.completion;
      });
    },
  };
}

test("current conversation still opens its new branch and fills its draft references", async t => {
  const editor = await mount(t);
  const operation = await editor.start();
  assert.equal(editor.current.forkingMessageId, "message-A");
  await editor.finish(0, operation);
  assert.deepEqual(editor.effects, [
    ["apply", "branch-0"], ["references", ["message-A"]], ["reload", "P", "branch-0"],
  ]);
  assert.equal(editor.current.forkingMessageId, null);
});

for (const [name, navigate] of [
  ["another conversation", editor => editor.select("B")],
  ["another project with the same session id", editor => editor.select("A", "Q")],
  ["away and back", async editor => { await editor.select("B"); await editor.select("A"); }],
  ["unmounted panel", editor => editor.unmount()],
]) {
  test(`late branch success cannot affect ${name}`, async t => {
    const editor = await mount(t);
    const operation = await editor.start();
    await navigate(editor);
    await editor.finish(0, operation);
    assert.deepEqual(editor.effects, []);
  });
}

test("old success cannot clear a new branch operation in the next conversation", async t => {
  const editor = await mount(t);
  const old = await editor.start();
  await editor.select("B");
  const next = await editor.start("message-B");
  await editor.finish(0, old);
  assert.deepEqual(editor.effects, []);
  assert.equal(editor.current.forkingMessageId, "message-B");
  await editor.finish(1, next);
  assert.equal(editor.effects[0][1], "branch-1");
  assert.deepEqual(editor.effects[1], ["references", ["message-B"]]);
});

test("old failures do not show in a new conversation but current failures remain visible", async t => {
  const editor = await mount(t);
  const old = await editor.start();
  await editor.select("B");
  await editor.finish(0, old, new Error("old failure"));
  assert.equal(editor.current.branchError, null);
  const next = await editor.start("message-B");
  await editor.finish(1, next, new Error("current failure"));
  assert.equal(editor.current.branchError, "current failure");
  assert.equal(editor.current.forkingMessageId, null);
});
