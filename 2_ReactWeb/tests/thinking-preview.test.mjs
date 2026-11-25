import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement, useCallback } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const folds = await vite.ssrLoadModule("/src/features/ai-panel/model/chatProcessFoldState.tsx");
const { AssistantProcessTimeline } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatAssistantProcessTimeline.tsx");
const { useThinkingAutoScroll } = await vite.ssrLoadModule("/src/features/ai-panel/model/useThinkingAutoScroll.ts");
const { createChatBottomFollower } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatBottomFollower.ts");
await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");

function environment(reduced = true) {
  const frames = new Map(), observers = new Set(); let serial = 0, now = 0;
  globalThis.window = { matchMedia: () => ({ matches: reduced }),
    requestAnimationFrame(fn) { frames.set(++serial, fn); return serial; },
    cancelAnimationFrame(id) { frames.delete(id); } };
  globalThis.getComputedStyle = () => ({ paddingTop: "0", paddingBottom: "0", borderTopWidth: "0", borderBottomWidth: "0" });
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; }
    observe() { observers.add(this.callback); }
    disconnect() { observers.delete(this.callback); }
  };
  return { frames, observers, resize() { observers.forEach((fn) => fn()); },
    tick(ms = 1000 / 60) { now += ms; const batch = [...frames.values()]; frames.clear(); batch.forEach((fn) => fn(now)); },
    createNodeMock: () => ({ style: {}, dataset: {}, getBoundingClientRect: () => ({ height: 300 }) }) };
}
const initial = { id: "assistant", role: "assistant", content: "", thinkingContent: "思考中", status: "running",
  usage: null, isThinkingExpanded: true, thinkingStartedAt: 1000, thinkingFinishedAt: null,
  createdAt: 1000, updatedAt: 1000, toolCalls: [] };
const thinking = { id: "thinking", type: "thinking", content: "正在思考。\n\n".repeat(20),
  status: "running", startedAt: 1000, finishedAt: null };
const interactions = { setThinkingContentRef() {}, onThinkingContentScroll() {}, onThinkingContentWheel() {}, onTouchMoveThinkingContent() {} };
const find = (view, className) => view.root.findAll((n) => typeof n.type === "string" && n.props.className?.split(" ").includes(className));

for (const paused of [false, true]) test(`自动展开仅预览，思考结束${paused ? "暂停跟随时保留预览" : "跟随时全部收起"}`, async () => {
  const env = environment(); let view, body = "", running = true;
  const render = () => createElement(folds.ChatProcessFoldProvider, { sessionKey: "A", isFollowing: !paused },
    createElement(folds.ChatProcessFoldScope, { turnId: "user", thinkingOffset: 0 },
      createElement(AssistantProcessTimeline, { autoCollapseProcess: true, clockTick: 2000, interactions,
        isStreamingMessage: running, message: { ...initial, content: body,
          processItems: [{ ...thinking, status: body ? "done" : "running", finishedAt: body ? 2000 : null }] } })));
  try {
    await act(async () => { view = create(render(), env); });
    assert.equal(find(view, "chat-msg__thinking-content--preview").length, 1);
    assert.equal(find(view, "chat-msg__thinking-expand").length, 1);
    assert.equal(find(view, "chat-msg__thinking-content--full").length, 0);
    body = "正式回复开始";
    await act(async () => view.update(render()));
    assert.equal(find(view, "chat-msg__thinking-toggle")[0].props["aria-expanded"], paused);
    assert.equal(find(view, "chat-msg__thinking-content").length, paused ? 1 : 0);
    running = false;
    await act(async () => view.update(render()));
    assert.equal(find(view, "chat-msg__processed-toggle")[0].props["aria-expanded"], paused);
  } finally { if (view) await act(async () => view.unmount()); }
});

test("手动完全展开复用折叠记忆，流式更新不重绑引用，结束和切换会话不会收起", async () => {
  const env = environment(); let view, running = true, session = "A", content = thinking.content;
  const refs = [];
  const actions = { ...interactions, setThinkingContentRef: (...args) => refs.push(args) };
  const render = () => createElement(folds.ChatProcessFoldProvider, { sessionKey: session },
    createElement(folds.ChatProcessFoldScope, { turnId: "user", thinkingOffset: 0 },
      createElement(AssistantProcessTimeline, { autoCollapseProcess: true, clockTick: 2000, interactions: actions,
        isStreamingMessage: running, message: { ...initial, content: running ? "" : "正式回复",
          processItems: [{ ...thinking, content, status: running ? "running" : "done" }] } })));
  try {
    await act(async () => { view = create(render(), env); });
    const before = refs.length;
    content += "新内容";
    await act(async () => view.update(render()));
    assert.equal(refs.length, before, "每次流式渲染不能清除用户的暂停状态");
    await act(async () => find(view, "chat-msg__thinking-expand")[0].props.onClick());
    assert.equal(find(view, "chat-msg__thinking-content--full").length, 1);
    assert.equal(find(view, "chat-msg__thinking-expand").length, 0);
    running = false; await act(async () => view.update(render()));
    assert.equal(find(view, "chat-msg__processed-toggle")[0].props["aria-expanded"], true);
    assert.equal(find(view, "chat-msg__thinking-content--full").length, 1);
    session = "B"; await act(async () => view.update(render()));
    assert.equal(find(view, "chat-msg__thinking-content").length, 0);
    session = "A"; await act(async () => view.update(render()));
    assert.equal(find(view, "chat-msg__thinking-content--full").length, 1);
    await act(async () => find(view, "chat-msg__thinking-toggle")[0].props.onClick());
    assert.equal(find(view, "chat-msg__thinking-content").length, 0);
    await act(async () => find(view, "chat-msg__thinking-toggle")[0].props.onClick());
    assert.equal(find(view, "chat-msg__thinking-content--full").length, 1, "历史手动展开仍显示完整内容");
  } finally { if (view) await act(async () => view.unmount()); }
});

test("思考滚动平滑跟随，向上查看立即取消动画，内容更新不夺回滚动，卸载无残留帧", async () => {
  const env = environment(false); let hook, view, pauses = 0;
  const onPause = () => pauses++;
  const node = { scrollHeight: 1000, clientHeight: 96, scrollTop: 0, querySelector: () => null };
  function Harness() {
    hook = useThinkingAutoScroll(onPause);
    const { setThinkingContentRef } = hook;
    const setRef = useCallback((el) => setThinkingContentRef("assistant", el), [setThinkingContentRef]);
    return createElement("div", { ref: setRef });
  }
  try {
    await act(async () => { view = create(createElement(Harness), { createNodeMock: () => node }); });
    env.tick(); assert.ok(node.scrollTop > 0 && node.scrollTop < 904);
    hook.handleThinkingContentWheel("assistant", { deltaY: -1 });
    assert.equal(pauses, 1); assert.equal(env.frames.size, 0);
    const stopped = node.scrollTop;
    node.scrollHeight += 500;
    await act(async () => view.update(createElement(Harness)));
    env.resize(); env.tick();
    assert.equal(node.scrollTop, stopped);
    node.scrollTop = node.scrollHeight - node.clientHeight;
    hook.handleThinkingContentScroll("assistant");
    node.scrollHeight += 200;
    env.resize();
    for (let i = 0; i < 40; i++) env.tick();
    assert.equal(node.scrollTop, node.scrollHeight - node.clientHeight);
    assert.equal(env.frames.size, 0);
    node.scrollHeight += 200; env.resize();
    await act(async () => view.unmount()); view = null;
    assert.equal(env.frames.size, 0);
    assert.equal(env.observers.size, 0);
  } finally { if (view) await act(async () => view.unmount()); }
});

test("逐行增高的正文与思考框在不同刷新率和像素精度下均能跟到底并停止", () => {
  for (const hz of [60, 120, 144]) {
    for (const scale of [1, 1.25, 2]) {
      const env = environment(false);
      let top = 0;
      const node = { clientHeight: 96, scrollHeight: 96, get scrollTop() { return top; },
        set scrollTop(value) { top = Math.round(value * scale) / scale; } };
      const follower = createChatBottomFollower({ getScrollElement: () => node, canFollow: () => true });
      for (let i = 0; i < 150; i++) {
        if (i < 60 && i % 4 === 0) { node.scrollHeight += 24; follower.request(); }
        const before = top;
        env.tick(1000 / hz);
        assert.ok(top >= before && top <= 360);
      }
      assert.equal(top, 360);
      assert.equal(follower.isActive(), false);
      assert.equal(env.frames.size, 0);
    }
  }
});

test("系统关闭动画时聊天仍逐帧跟随，手动暂停能取消后续帧", () => {
  const env = environment(true);
  const node = { scrollTop: 0, scrollHeight: 1000, clientHeight: 100 };
  let following = true;
  const follower = createChatBottomFollower({
    getScrollElement: () => node, canFollow: () => following,
  });
  follower.request();
  env.tick();
  assert.ok(node.scrollTop > 0 && node.scrollTop < 900);
  assert.equal(follower.isActive(), true);
  const pausedTop = node.scrollTop;
  following = false;
  env.tick();
  assert.equal(node.scrollTop, pausedTop);
  assert.equal(env.frames.size, 0);
  following = true;
  follower.request();
  for (let i = 0; i < 60; i++) env.tick();
  assert.equal(node.scrollTop, 900);
  assert.equal(env.frames.size, 0);
});
