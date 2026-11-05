import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const folds = await vite.ssrLoadModule("/src/features/ai-panel/model/chatProcessFoldState.tsx");
const { AssistantProcessTimeline } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatAssistantProcessTimeline.tsx");
const { ChatMessageItem } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatMessageItem.tsx");
await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");
const wrap = (child, isFollowing = true) => createElement(folds.ChatProcessFoldProvider,
  { sessionKey: "test", isFollowing, visibleMessageKeys: new Set(["assistant"]) },
  createElement(folds.ChatProcessFoldScope, { turnId: "user", messageKey: "assistant", thinkingOffset: 0 }, child));
const message = { id: "assistant", role: "assistant", content: "", thinkingContent: "", status: "running",
  usage: null, isThinkingExpanded: true, thinkingStartedAt: 1000, thinkingFinishedAt: null,
  createdAt: 1000, updatedAt: 1000, processItems: [], toolCalls: [] };
const interactions = { setThinkingContentRef() {}, onThinkingContentScroll() {}, onThinkingContentWheel() {}, onTouchMoveThinkingContent() {} };

test("等待响应只显示外层状态，不预设 Thinking；真实思考到达后才显示标题", () => {
  const props = { autoCollapseProcess: true, clockTick: 1000, interactions, isStreamingMessage: true, message };
  const live = renderToStaticMarkup(wrap(createElement(AssistantProcessTimeline, props)));
  assert.match(live, /chat-msg__processed-toggle/);
  assert.match(live, /处理中/);
  assert.doesNotMatch(live, /Thinking/);
  const thinking = renderToStaticMarkup(wrap(createElement(AssistantProcessTimeline, {
    ...props, message: { ...message, processItems: [{ id: "real-thinking", type: "thinking", content: "真实思考",
      status: "running", startedAt: 1000, finishedAt: null }] },
  })));
  assert.match(thinking, /Thinking/);
  const done = renderToStaticMarkup(wrap(createElement(AssistantProcessTimeline, {
    ...props, isStreamingMessage: false, message: { ...message, status: "done", content: "正式回复" },
  })));
  assert.match(done, /已处理/);
  assert.equal((live.match(/chat-msg__processed-toggle/g) ?? []).length, (done.match(/chat-msg__processed-toggle/g) ?? []).length);
});

test("流式正文下不留操作统计空白，结束时通过统一高度动画展开底栏", () => {
  const props = { autoCollapseAssistantProcess: true, clockTick: 1000, expandedUserMessageIds: new Set(), interactions,
    isLastMessage: true, isSessionStreaming: true, modelSwitchModelId: null, foldTurnId: "user", foldThinkingOffset: 0,
    message: { ...message, content: "正式回复" } };
  const render = (value) => renderToStaticMarkup(createElement(folds.ChatProcessFoldProvider, { sessionKey: "test" }, createElement(ChatMessageItem, value)));
  const live = render(props);
  const done = render({ ...props, isSessionStreaming: false, message: { ...props.message, status: "done" } });
  assert.match(live, /sliding-content chat-msg__footer[^>]*height:0px/);
  for (const className of ["chat-msg__actions", "chat-msg__usage"]) {
    assert.ok(!live.includes(className)); assert.ok(done.includes(className));
  }
});

test("仅当前输出及结束瞬间参与自动收起，历史不补收起；重挂保留，重启重置", async () => {
  let value, view;
  function Harness({ desired, allow, running }) {
    value = folds.useAutomaticProcessFolds("test", desired, running, allow);
    return createElement("div");
  }
  const render = (desired, allow, running, visible = true) => wrap(visible ? createElement(Harness, { desired, allow, running }) : null);
  try {
    await act(async () => { view = create(render("thinking", true, true)); });
    assert.ok(value.has("thinking"));
    await act(async () => view.update(render(null, false, true)));
    assert.ok(value.has("thinking"));
    await act(async () => view.update(render(null, true, true)));
    assert.equal(value.size, 0, "还在输出，恢复跟随后允许收起");
    await act(async () => view.update(render("tools", true, true)));
    await act(async () => view.update(render(null, false, false)));
    await act(async () => view.update(render(null, true, false)));
    assert.ok(value.has("tools"), "已结束的历史不能补做收起");
    await act(async () => view.update(render(null, true, false, false)));
    await act(async () => view.update(render(null, true, false)));
    assert.ok(value.has("tools"), "虚拟行重挂保留内存状态");
    // Unmounted while still live, then completed in the background: returning
    // to history must not invent a visible live→done transition.
    await act(async () => view.update(render("thinking", true, true)));
    await act(async () => view.update(render(null, true, false, false)));
    await act(async () => view.update(render(null, true, false)));
    assert.ok(value.has("thinking"));
    await act(async () => view.unmount());
    await act(async () => { view = create(render("thinking", true, false)); });
    assert.equal(value.size, 0, "新面板的历史默认收起，不继承旧内存或响应数据中的展开标记");
  } finally { if (view) await act(async () => view.unmount()); }
});

test("外层和内层均服从跟随状态，手动展开子项后外层不能自动藏起它", async () => {
  globalThis.window = { matchMedia: () => ({ matches: true }), requestAnimationFrame: () => 1, cancelAnimationFrame() {} };
  globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", borderTopWidth: "0", borderBottomWidth: "0" });
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  const options = { createNodeMock: () => ({ style: {}, dataset: {}, getBoundingClientRect: () => ({ height: 100 }) }) };
  const tool = { id: "tool", type: "tool_preparing", startedAt: 1000 };
  let view, following = true, running = true;
  const render = () => wrap(createElement(AssistantProcessTimeline, { autoCollapseProcess: true, clockTick: 1000,
    interactions, isStreamingMessage: running, message: { ...message, processItems: [tool] } }), following);
  const button = (name) => view.root.findAll((n) => n.type === "button" && n.props.className === name)[0];
  try {
    await act(async () => { view = create(render(), options); });
    const originalOuter = button("chat-msg__processed-toggle");
    following = false; running = false;
    await act(async () => view.update(render()));
    assert.equal(button("chat-msg__processed-toggle"), originalOuter);
    assert.equal(originalOuter.props["aria-expanded"], true);
    assert.equal(button("chat-msg__tools-toggle").props["aria-expanded"], true);
    following = true;
    await act(async () => view.update(render()));
    assert.equal(originalOuter.props["aria-expanded"], true, "历史外层不补收起");
    assert.equal(button("chat-msg__tools-toggle").props["aria-expanded"], true, "历史工具组不补收起");
    // Explicitly pin the child open, then resume follow.
    await act(async () => button("chat-msg__tools-toggle").props.onClick());
    await act(async () => button("chat-msg__tools-toggle").props.onClick());
    following = true;
    await act(async () => view.update(render()));
    assert.equal(originalOuter.props["aria-expanded"], true);
    await act(async () => originalOuter.props.onClick());
    assert.equal(originalOuter.props["aria-expanded"], false, "手动收起始终生效");
  } finally { if (view) await act(async () => view.unmount()); }
});

test("查看旧历史时屏外的新回复仍自动收起，手动展开跨会话和虚拟卸载保留", async () => {
  globalThis.window = { matchMedia: () => ({ matches: true }), requestAnimationFrame: () => 1, cancelAnimationFrame() {} };
  globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", borderTopWidth: "0", borderBottomWidth: "0" });
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  const options = { createNodeMock: () => ({ style: {}, dataset: {}, getBoundingClientRect: () => ({ height: 100 }) }) };
  let view, session = "A", following = true, running = true, showHistory = true;
  const timeline = (id, live) => createElement(folds.ChatProcessFoldScope, { key: id, turnId: id, thinkingOffset: 0 },
    createElement("section", { "data-test-turn": id }, createElement(AssistantProcessTimeline, {
      autoCollapseProcess: true, clockTick: 1000, interactions, isStreamingMessage: live,
      message: { ...message, id, status: live ? "running" : "done", processItems: [{ id: `${id}-tool`, type: "tool_preparing", startedAt: 1000 }] },
    })));
  const render = () => createElement(folds.ChatProcessFoldProvider,
    { sessionKey: session, isFollowing: following, visibleMessageKeys: new Set(["history"]) },
    showHistory ? timeline("history", false) : null, timeline("active", running));
  const button = (turn, name) => view.root.findByProps({ "data-test-turn": turn })
    .findAll((n) => n.type === "button" && n.props.className === name)[0];
  const outer = (turn) => button(turn, "chat-msg__processed-toggle");
  const tools = (turn) => button(turn, "chat-msg__tools-toggle");
  try {
    await act(async () => { view = create(render(), options); });
    assert.equal(outer("history").props["aria-expanded"], false);
    await act(async () => outer("history").props.onClick());
    await act(async () => tools("history").props.onClick());
    following = false;
    await act(async () => view.update(render()));
    running = false;
    await act(async () => view.update(render()));
    assert.equal(outer("active").props["aria-expanded"], false, "正在查看旧历史时，屏外新回复结束也应自动收起");
    assert.equal(outer("history").props["aria-expanded"], true);
    assert.equal(tools("history").props["aria-expanded"], true);
    showHistory = false; await act(async () => view.update(render()));
    showHistory = true; await act(async () => view.update(render()));
    assert.equal(tools("history").props["aria-expanded"], true);
    session = "B"; await act(async () => view.update(render()));
    assert.equal(outer("history").props["aria-expanded"], false);
    session = "A"; await act(async () => view.update(render()));
    assert.equal(tools("history").props["aria-expanded"], true);
    await act(async () => view.unmount());
    await act(async () => { view = create(render(), options); });
    assert.equal(outer("history").props["aria-expanded"], false);
  } finally { if (view) await act(async () => view.unmount()); }
});
