import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function load(name, mocks) {
  const file = new URL(`../src/features/ai-panel/model/${name}.ts`, import.meta.url);
  const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file.pathname })(
    name => { if (name in mocks) return mocks[name]; throw new Error(`Unmocked ${name}`); }, module, module.exports);
  return module.exports;
}
const navigation = load("userMessageNavigation", { "./userMessageReferences": { resolveUserMessageContent: m => m.content } });
const user = id => ({ id, role: "user", content: id });
const response = (ids, reset = 0) => ({ revision: 1, reset_revision: reset,
  items: ids.map((id, i) => ({ user_message_id: id, user_preview: id,
    assistant_message_id: null, assistant_preview: "", turn_number: i + 1 })) });

async function mount(t, initial = {}) {
  const requests = [];
  const { useConversationNavigation } = load("useConversationNavigation", { react: React,
    "./userMessageNavigation": navigation,
    "../../../services/project/getConversationNavigation": {
      getConversationNavigation: (project, session, signal) => new Promise((resolve, reject) => {
        requests.push({ project, session, signal, resolve, reject });
      }),
    },
  });
  let props = { projectId: "p", sessionId: "a", revision: 1, resetRevision: 0, running: false, messages: [], ...initial };
  let current, renderer;
  function Harness(value) { current = useConversationNavigation(value); return null; }
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  return { requests, get current() { return current; }, async update(patch) {
    props = { ...props, ...patch };
    await act(async () => renderer.update(React.createElement(Harness, props)));
  } };
}

test("完整目录不依赖正文页数，流式每段输出不重新请求目录，结束后刷新预览", async t => {
  const h = await mount(t, { running: true, messages: [user("u119")] });
  assert.equal(h.current.items.length, 0, "目录未读取时不能把末页当完整目录");
  await act(async () => h.requests[0].resolve(response(Array.from({ length: 120 }, (_, i) => `u${i}`))));
  assert.equal(h.current.items.length, 120);
  for (let i = 0; i < 8; i++) await h.update({ revision: i + 2, messages: [user("u119"),
    { id: "reply", role: "assistant", status: "running", content: `delta ${i}` }] });
  assert.equal(h.requests.length, 1);
  await h.update({ messages: [user("u119"), user("new")] });
  assert.equal(h.current.items.at(-1).turnNumber, 121);
  await h.update({ running: false });
  assert.equal(h.requests.length, 2);
});

test("快速切会话时忽略旧目录响应，失败可重试", async t => {
  const h = await mount(t);
  await h.update({ sessionId: "b", messages: [user("b-user")] });
  assert.equal(h.requests[0].signal.aborted, true);
  await act(async () => h.requests[1].resolve(response(["b-user"])));
  await act(async () => h.requests[0].resolve(response(["a-user"])));
  assert.deepEqual(h.current.items.map(x => x.userMessageId), ["b-user"]);
  await h.update({ sessionId: "c", messages: [] });
  await act(async () => h.requests[2].reject(new Error("offline")));
  assert.match(h.current.error, /offline/);
  assert.equal(h.current.items.length, 0);
  await act(async () => h.current.retry());
  await act(async () => h.requests[3].resolve(response(["c-user"])));
  assert.equal(h.current.error, null);
  assert.deepEqual(h.current.items.map(x => x.userMessageId), ["c-user"]);
});

test("历史重置与正文刷新存在先后时不把被删除提问加回目录", async t => {
  const h = await mount(t, { messages: [user("old")] });
  await act(async () => h.requests[0].resolve(response(["old"])));
  await h.update({ revision: 2 });
  await act(async () => h.requests[1].resolve(response(["replacement"], 2)));
  assert.deepEqual(h.current.items.map(x => x.userMessageId), ["replacement"]);
  await h.update({ resetRevision: 2, messages: [user("replacement")] });
  assert.deepEqual(h.current.items.map(x => x.userMessageId), ["replacement"]);
});
