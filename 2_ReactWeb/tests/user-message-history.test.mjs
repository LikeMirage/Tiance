import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true },
  plugins: [{ name: "message-history-test", enforce: "pre", transform(code, id) {
    if (id.endsWith("/getProjectConversationMessage.ts")) return "export const getProjectConversationMessage = (...args) => globalThis.readTestMessage(...args);";
    if (id.endsWith("/getConversationNavigation.ts")) return "export const getConversationNavigation = (...args) => globalThis.searchTestMessages(...args);";
    if (id.endsWith("/UserMessageHistoryMenu.tsx")) return code.replace('import { createPortal } from "react-dom";',
      "const createPortal = (children: any, _target: any) => children;");
  } }],
});
const { UserMessageHistoryMenu } = await vite.ssrLoadModule("/src/features/ai-panel/ui/UserMessageHistoryMenu.tsx");
const { useUserMessageDetail } = await vite.ssrLoadModule("/src/features/ai-panel/model/useUserMessageDetail.ts");
const { useUserMessageSearch } = await vite.ssrLoadModule("/src/features/ai-panel/model/useUserMessageSearch.ts");
const { KeywordHighlight } = await vite.ssrLoadModule("/src/features/ai-panel/ui/KeywordHighlight.tsx");
const previous = {};
before(() => {
  for (const key of ["window", "document", "IS_REACT_ACT_ENVIRONMENT", "readTestMessage", "searchTestMessages"]) previous[key] = Object.getOwnPropertyDescriptor(globalThis, key);
  Object.assign(globalThis, { window: Object.assign(new EventTarget(), { innerWidth: 1200, innerHeight: 900 }),
    document: { body: {} }, IS_REACT_ACT_ENVIRONMENT: true });
});
after(async () => {
  await vite.close();
  for (const [key, descriptor] of Object.entries(previous)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
  }
});
const reference = { type: "file", reference: { id: "r", kind: "folder", projectId: null,
  filePath: "C:/work/project", displayPath: "C:/work/project", fileName: "项目（Tiance 项目）", source: "external_path" } };
const stored = (id, session = "s", content = `正文 ${id}`) => ({ message_id: id, session_id: session,
  role: "user", content, references: [reference], status: "done", created_at: "2026-11-10T08:00:00Z" });
const local = id => ({ id, role: "user", content: `本地 ${id}`, references: [reference], createdAt: 1 });
const nodes = () => ({ focus() {}, contains: () => false, scrollIntoView() {},
  getBoundingClientRect: () => ({ right: 1000, top: 600 }) });

test("面板列出完整目录，选中旧提问只取该条正文，定位和引用沿用调用方回调", async () => {
  const calls = [], located = [], opened = [];
  globalThis.readTestMessage = async (...args) => { calls.push(args); return stored(args[2]); };
  const items = Array.from({ length: 150 }, (_, i) => ({ userMessageId: `u${i}`, turnNumber: i + 1, userPreview: `提问 ${i}`, assistantPreview: "" }));
  const history = { projectId: "p", sessionId: "s", resetRevision: 0, messages: [local("u149")],
    navigation: { items, error: null, isLoading: false, retry() {} }, onLocate: item => located.push(item) };
  let view;
  function Harness() {
    const [isOpen, setOpen] = React.useState(true);
    return React.createElement(UserMessageHistoryMenu, { history, isOpen, onOpenChange: setOpen, onOpenReference: payload => opened.push(payload) });
  }
  await act(async () => { view = create(React.createElement(Harness), { createNodeMock: nodes }); });
  try {
    assert.equal(view.root.findAllByProps({ className: "user-message-history__select" }).length, 150);
    assert.equal(calls.length, 0, "已有正文不再请求");
    await act(async () => view.root.findAllByProps({ className: "user-message-history__select" })[0].props.onClick());
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].slice(0, 3), ["p", "s", "u0"]);
    assert.match(JSON.stringify(view.toJSON()), /正文 u0/);
    assert.match(JSON.stringify(view.toJSON()), /项目（Tiance 项目）/);
    assert.equal(located.length, 0, "浏览详情不滚动聊天");
    await act(async () => view.root.findByProps({ "aria-label": "定位第 1 条用户消息" }).props.onClick());
    assert.deepEqual(located, [items[0]]);
    assert.equal(view.root.findAllByProps({ role: "dialog" }).length, 0);
    await act(async () => view.root.findByProps({ "aria-label": "用户消息列表", type: "button" }).props.onClick());
    await act(async () => view.root.findByProps({ title: "查看引用内容" }).props.onClick());
    assert.deepEqual(opened, [{ kind: "file", reference: reference.reference }]);
  } finally { await act(async () => view.unmount()); }
});

async function detailHarness(t) {
  const requests = [];
  globalThis.readTestMessage = (project, session, id, signal) => new Promise((resolve, reject) => requests.push({ project, session, id, signal, resolve, reject }));
  let props = { projectId: "p", sessionId: "a", messageId: "u1", resetRevision: 0, messages: [] }, current, view;
  function Harness(value) { current = useUserMessageDetail(value); return null; }
  await act(async () => { view = create(React.createElement(Harness, props)); });
  t.after(async () => { await act(async () => view.unmount()); });
  return { requests, get current() { return current; }, async update(patch) {
    props = { ...props, ...patch }; await act(async () => view.update(React.createElement(Harness, props)));
  } };
}
test("快速切换提问或会话时取消旧请求，不显示串会话的正文", async t => {
  const h = await detailHarness(t);
  await h.update({ messageId: "u2" });
  assert.equal(h.requests[0].signal.aborted, true);
  await act(async () => h.requests[1].resolve(stored("u2", "a")));
  assert.equal(h.current.message.id, "u2");
  await h.update({ sessionId: "b" });
  assert.equal(h.current.message, null);
  await act(async () => h.requests[0].resolve(stored("u1", "a")));
  assert.equal(h.current.message, null);
  await act(async () => h.requests[2].resolve(stored("u2", "b")));
  assert.equal(h.current.message.id, "u2");
});
test("读取失败可以重试，正文完整保留，历史重置后重读", async t => {
  const h = await detailHarness(t);
  await act(async () => h.requests[0].reject(new Error("offline")));
  assert.equal(h.current.error, "offline");
  await act(async () => h.current.retry());
  const content = "完整长消息\n".repeat(5000);
  await act(async () => h.requests[1].resolve(stored("u1", "a", content)));
  assert.equal(h.current.message.content, content);
  assert.equal(h.current.error, null);
  await h.update({ resetRevision: 1 });
  assert.equal(h.requests.length, 3);
  assert.equal(h.current.message, null);
});
test("流式回复变化不会重取所选用户消息", async t => {
  const h = await detailHarness(t);
  await act(async () => h.requests[0].resolve(stored("u1", "a")));
  for (let i = 0; i < 10; i++) await h.update({ messages: [{ id: "reply", role: "assistant", content: `delta ${i}` }] });
  assert.equal(h.requests.length, 1);
});

test("全文搜索查询未加载的旧消息，右侧高亮正文和引用，定位保留原编号", async () => {
  const items = [1, 2, 3].map(n => ({ userMessageId: `u${n}`, turnNumber: n, userPreview: `普通预览 ${n}`, assistantPreview: "" }));
  const calls = [], located = [];
  globalThis.searchTestMessages = async (...args) => { calls.push(args); return { items: [{
    user_message_id: "u1", turn_number: 1, user_preview: "普通预览 1", assistant_preview: "", assistant_message_id: null,
  }] }; };
  globalThis.readTestMessage = async (_p, _s, id) => stored(id, "s", "项目在全文后面：项目，以及项目");
  const history = { projectId: "p", sessionId: "s", resetRevision: 0, messages: [local("u3")],
    navigation: { items, error: null, isLoading: false, retry() {} }, onLocate: item => located.push(item) };
  let view;
  await act(async () => { view = create(React.createElement(UserMessageHistoryMenu, {
    history, isOpen: true, onOpenChange() {},
  }), { createNodeMock: nodes }); });
  try {
    assert.equal(view.root.findByProps({ role: "dialog" }).props.style.width, 440);
    const input = view.root.findByProps({ "aria-label": "搜索用户消息" });
    await act(async () => input.props.onChange({ target: { value: "项目" } }));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 210)); });
    assert.deepEqual(calls[0].slice(0, 2), ["p", "s"]);
    assert.equal(calls[0][3], "项目");
    assert.equal(view.root.findAllByProps({ className: "user-message-history__select" }).length, 1);
    const detail = view.root.findByProps({ "aria-label": "用户消息详情" });
    assert.equal(detail.findAllByType("mark").length, 5, "正文三处和引用名称两处全部高亮");
    await act(async () => view.root.findByProps({ "aria-label": "定位第 1 条用户消息" }).props.onClick());
    assert.equal(located[0].userMessageId, "u1");
    await act(async () => input.props.onChange({ target: { value: "" } }));
    assert.equal(view.root.findAllByProps({ className: "user-message-history__select" }).length, 3);
  } finally { await act(async () => view.unmount()); }
});

test("关键词按字面匹配而非正则，并保留原文大小写与HTML文字", async () => {
  let view;
  await act(async () => { view = create(React.createElement(KeywordHighlight, { text: "[a.*] <script> [A.*]", keyword: "[a.*]" })); });
  try {
    assert.deepEqual(view.root.findAllByType("mark").map(mark => mark.children.join("")), ["[a.*]", "[A.*]"]);
    assert.equal(view.root.findAllByType("script").length, 0);
  } finally { await act(async () => view.unmount()); }
});

test("搜索取消旧请求，忽略乱序结果；失败可重试，清空立即恢复完整目录", async t => {
  const requests = [];
  globalThis.searchTestMessages = (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject }));
  let props = { projectId: "p", sessionId: "s", resetRevision: 0,
    items: [{ userMessageId: "u", turnNumber: 1, userPreview: "old", assistantPreview: "" }], query: "first" }, current, view;
  function Harness(p) { current = useUserMessageSearch(p); return null; }
  const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 210)); });
  const update = async patch => { props = { ...props, ...patch }; await act(async () => view.update(React.createElement(Harness, props))); };
  await act(async () => { view = create(React.createElement(Harness, props)); });
  t.after(async () => { await act(async () => view.unmount()); });
  await settle();
  await update({ query: "second" });
  assert.equal(requests[0].args[2].aborted, true);
  await settle();
  await act(async () => requests[1].resolve({ items: [] }));
  await act(async () => requests[0].resolve({ items: [{ user_message_id: "stale" }] }));
  assert.deepEqual(current.items, []);
  await update({ query: "third" }); await settle();
  await act(async () => requests[2].reject(new Error("offline")));
  assert.match(current.error, /offline/);
  await act(async () => current.retry()); await settle();
  await act(async () => requests[3].resolve({ items: [] }));
  assert.equal(current.error, null);
  await update({ items: [{ ...props.items[0], assistantPreview: "stream delta" }] }); await settle();
  assert.equal(requests.length, 4, "思考和回复增量不重新搜索用户消息");
  await update({ query: "" });
  assert.equal(current.items[0].userMessageId, "u");
  assert.equal(current.isLoading, false);
});
