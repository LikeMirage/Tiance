import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { startChatMessageNavigation } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatMessageNavigation.ts");
const { useBodyAutoScroll } = await vite.ssrLoadModule("/src/features/ai-panel/model/useBodyAutoScroll.ts");
const { useVirtualMessageList } = await vite.ssrLoadModule("/src/features/ai-panel/model/useVirtualMessageList.ts");
const { captureChatScrollPosition } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatScrollPosition.ts");

function environment() {
  let sequence = 0;
  let frameTime = 0;
  const frames = new Map();
  globalThis.window = {
    requestAnimationFrame: (callback) => { frames.set(++sequence, callback); return sequence; },
    cancelAnimationFrame: (id) => frames.delete(id),
    setTimeout: () => ++sequence, clearTimeout() {},
    matchMedia: () => ({ matches: true }), addEventListener() {}, removeEventListener() {},
  };
  const resizeObservers = new Set();
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; }
    observe() { resizeObservers.add(this.callback); }
    unobserve() {}
    disconnect() { resizeObservers.delete(this.callback); }
  };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.HTMLElement = class {};
  return {
    resize() { resizeObservers.forEach((callback) => callback()); },
    frame() { frameTime += 16; const pending = [...frames.values()]; frames.clear(); pending.forEach((callback) => callback(frameTime)); },
  };
}

function scrollDom() {
  let top = 0;
  const element = {
    scrollHeight: 10000, clientHeight: 500, clientWidth: 500, offsetWidth: 510,
    nodes: [], listeners: new Map(), contains: () => true,
    addEventListener(type, listener) { this.listeners.set(type, listener); },
    removeEventListener(type, listener) { if (this.listeners.get(type) === listener) this.listeners.delete(type); },
    getBoundingClientRect: () => ({ top: 0, bottom: 500, right: 500 }),
    querySelector: () => null, querySelectorAll() { return this.nodes; },
    get scrollTop() { return top; },
    set scrollTop(value) { top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
    scrollTo({ top: value }) { this.scrollTop = value; },
  };
  const row = (id, offset, height = 900) => ({
    dataset: { chatMessageId: id }, offset, height, busy: false,
    querySelector() { return this.busy ? {} : null; },
    getBoundingClientRect() { return { top: this.offset - top, bottom: this.offset + this.height - top, height: this.height }; },
  });
  return { element, row };
}

test("恢复等待正文完成，并校正虚拟测量后的偏移；底部持续输出不阻塞完成", () => {
  const clock = environment();
  const { element, row } = scrollDom();
  const anchor = row("history", 1000, 2000);
  element.nodes = [anchor];
  let ready = false, handled = 0;
  const stop = startChatMessageNavigation({ scrollElement: element,
    request: { requestId: 1, messageId: "history", viewportOffset: -600 },
    isReady: () => ready, onHandled: () => handled++ });
  clock.frame();
  assert.equal(element.scrollTop, 0);
  ready = true;
  clock.frame();
  assert.equal(element.scrollTop, 1600);
  anchor.offset += 450;
  clock.frame();
  assert.equal(element.scrollTop, 2050);
  assert.equal(handled, 0);
  element.scrollHeight += 200;
  clock.frame();
  element.scrollHeight += 200;
  clock.frame();
  assert.equal(handled, 1);
  assert.equal(anchor.getBoundingClientRect().top, -600);
  stop();
});

test("切换会话或用户接管后，取消的恢复帧不能再滚动页面", () => {
  const clock = environment();
  const { element, row } = scrollDom();
  element.nodes = [row("old", 2000)];
  const stop = startChatMessageNavigation({ scrollElement: element,
    request: { requestId: 1, messageId: "old", viewportOffset: -50 },
    isReady: () => true, onHandled: () => assert.fail("cancelled request") });
  clock.frame();
  stop(); element.scrollTop = 300;
  clock.frame(); clock.frame();
  assert.equal(element.scrollTop, 300);
});

test("视口暂时为空时，不把屏幕外常驻的活动回复误记为阅读位置", () => {
  const { element, row } = scrollDom();
  element.nodes = [row("live", 9000)];
  assert.equal(captureChatScrollPosition(element, false).anchorMessageId, null);
  element.nodes.unshift(row("reading", 100));
  assert.equal(captureChatScrollPosition(element, false).anchorMessageId, "reading");
});

test("正文仍在分片挂载时不提前确认恢复", () => {
  const clock = environment();
  const { element, row } = scrollDom();
  const anchor = row("history", 1000);
  element.nodes = [anchor]; anchor.busy = true;
  let handled = false;
  const stop = startChatMessageNavigation({ scrollElement: element,
    request: { requestId: 1, messageId: "history", viewportOffset: -1200 },
    isReady: () => true, onHandled: () => { handled = true; } });
  clock.frame(); clock.frame(); clock.frame();
  assert.equal(handled, false);
  anchor.busy = false; anchor.height = 4000;
  clock.frame(); clock.frame(); clock.frame();
  assert.equal(handled, true);
  assert.equal(element.scrollTop, 2200);
  stop();
});

test("A→B→A 恢复时的空列表滚动不覆盖书签、不重新开启跟随；旧回调不能串会话", async () => {
  environment();
  const { element, row } = scrollDom();
  let hook, view;
  function Harness({ session, chat = true }) {
    hook = useBodyAutoScroll({ activeSessionKey: session, isChatViewActive: chat });
    return createElement("div", { ref: hook.bodyRef });
  }
  const render = async (session, chat = true) => act(async () => {
    const tree = createElement(Harness, { session, chat });
    if (view) view.update(tree);
    else view = create(tree, { createNodeMock: () => element });
  });
  try {
    element.nodes = [row("a", 1000)];
    await render("A");
    await act(async () => { hook.pauseForUserScroll(); element.scrollTop = 1200; hook.handleBodyScroll(); });
    element.nodes = [row("b", 2000)];
    await render("B");
    await act(async () => { hook.pauseForUserScroll(); element.scrollTop = 2200; hook.handleBodyScroll(); });
    element.nodes = []; element.scrollHeight = 500; element.scrollTop = 0;
    await render("A");
    const target = hook.viewRestoreRequest;
    assert.equal(target.messageId, "a");
    assert.equal(target.viewportOffset, -200);
    await act(async () => { hook.handleBodyScroll(); hook.syncAfterContentReady(); hook.preserveCurrentView(); });
    assert.equal(hook.isFollowingBottom, false);
    assert.equal(hook.viewRestoreRequest, target);
    const oldComplete = hook.onViewRestoreHandled;
    await render("B");
    await act(async () => oldComplete(target.requestId));
    assert.equal(hook.viewRestoreRequest.messageId, "b");
    await render("A");
    assert.equal(hook.viewRestoreRequest.viewportOffset, -200);
    element.scrollHeight = 10000; element.nodes = [row("a", 1800)]; element.scrollTop = 2000;
    await act(async () => hook.onViewRestoreHandled(hook.viewRestoreRequest.requestId));
    assert.equal(hook.viewRestoreRequest, null);
    assert.equal(hook.isFollowingBottom, false);
    await render("B"); await render("A");
    assert.equal(hook.viewRestoreRequest.viewportOffset, -200);
    // Entering settings must preserve an unfinished restore as well.
    await render("A", false); await render("A");
    assert.equal(hook.viewRestoreRequest.viewportOffset, -200);
    await act(async () => element.listeners.get("wheel")({ deltaY: 100 }));
    assert.equal(hook.viewRestoreRequest, null);
  } finally { if (view) await act(async () => view.unmount()); }
});

test("虚拟列表恢复时保留远处目标消息，与活动回复并存，取消后释放", async () => {
  environment();
  const { element } = scrollDom();
  const scrollParentRef = { current: element };
  const messages = Array.from({ length: 250 }, (_, i) => ({ id: `m${i}`, role: "assistant", content: "text" }));
  let hook, view;
  function Harness({ target }) {
    hook = useVirtualMessageList({ enabled: true, messages, scrollParentRef,
      keepLastMessageMounted: true, keepMessageMountedId: "m248", navigationMessageId: target });
    return createElement("div", { ref: hook.listRef });
  }
  try {
    await act(async () => { view = create(createElement(Harness, { target: "m150" }),
      { createNodeMock: () => ({ getBoundingClientRect: () => ({ top: 0 }) }) }); });
    for (const id of ["m150", "m248", "m249"]) assert.ok(hook.virtualItems.some((item) => item.message.id === id));
    await act(async () => view.update(createElement(Harness, { target: null })));
    assert.ok(!hook.virtualItems.some((item) => item.message.id === "m150"));
  } finally { if (view) await act(async () => view.unmount()); }
});

test("阅读位置只在面板内存中保留，重新打开后默认跟随底部", async () => {
  environment();
  const { element, row } = scrollDom();
  element.nodes = [row("history", 1000), row("latest", 9200)];
  let hook, view;
  function Harness() {
    hook = useBodyAutoScroll({ activeSessionKey: "A", isChatViewActive: true });
    return createElement("div", { ref: hook.bodyRef });
  }
  const mount = async () => act(async () => { view = create(createElement(Harness), { createNodeMock: () => element }); });
  try {
    await mount();
    await act(async () => hook.syncAfterContentReady());
    assert.equal(element.scrollTop, 9500);
    await act(async () => { hook.pauseForUserScroll(); element.scrollTop = 1200; hook.handleBodyScroll(); });
    assert.equal(hook.isFollowingBottom, false);
    await act(async () => view.unmount());
    await mount();
    await act(async () => hook.syncAfterContentReady());
    assert.equal(hook.viewRestoreRequest, null);
    assert.equal(hook.isFollowingBottom, true);
    assert.equal(element.scrollTop, 9500);
  } finally { if (view) await act(async () => view.unmount()); }
});

test("未锁定时，滚动条已到底和工具卡片增高期间的书签都不打断跟随", async () => {
  const clock = environment();
  const { element, row } = scrollDom();
  element.nodes = [row("latest", 9200, 3000)];
  let hook, view;
  function Harness() {
    hook = useBodyAutoScroll({ activeSessionKey: "A", isChatViewActive: true });
    return createElement("div", { ref: hook.bodyRef });
  }
  const grow = () => {
    element.scrollHeight += 400;
    hook.preserveCurrentView();
    clock.resize();
    for (let i = 0; i < 60; i++) clock.frame();
  };
  try {
    await act(async () => { view = create(createElement(Harness), { createNodeMock: () => element }); });
    await act(async () => hook.syncAfterContentReady());
    await act(async () => { hook.handleScrollbarScroll(false); grow(); });
    assert.equal(hook.isBottomFollowLocked, false);
    assert.equal(hook.isFollowingBottom, true);
    assert.equal(element.scrollTop, element.scrollHeight - element.clientHeight);
    const readingPosition = element.scrollTop - 200;
    await act(async () => { element.scrollTop = readingPosition; hook.handleScrollbarScroll(true); grow(); });
    assert.equal(hook.isFollowingBottom, false);
    assert.equal(element.scrollTop, readingPosition);
    await act(async () => { element.scrollTop = element.scrollHeight; hook.handleScrollbarScroll(true); grow(); });
    assert.equal(hook.isFollowingBottom, true);
    assert.equal(element.scrollTop, element.scrollHeight - element.clientHeight);
  } finally { if (view) await act(async () => view.unmount()); }
});

test("虚拟消息中的延迟正文保留占位高度，同时工具卡片增高立即计入列表", async () => {
  environment();
  const { element } = scrollDom();
  const scrollParentRef = { current: element };
  const messages = [{ id: "live", role: "assistant", content: "" }];
  let hook, view;
  function Harness() {
    hook = useVirtualMessageList({ enabled: true, messages, estimateSize: 140, scrollParentRef });
    return createElement("div", { ref: hook.listRef });
  }
  try {
    await act(async () => { view = create(createElement(Harness), { createNodeMock: () => element }); });
    for (const [height, pending, expected] of [[60, true, 140], [500, true, 500], [80, true, 500], [80, false, 80]]) {
      await act(async () => hook.measureMessage("live", 0, height, pending));
      assert.equal(hook.totalSize, expected);
    }
  } finally { if (view) await act(async () => view.unmount()); }
});

test("锁定底部后滚动和流式追加仍跟随，锁定按会话保留，解锁和历史定位允许阅读", async () => {
  const clock = environment();
  const { element, row } = scrollDom();
  element.nodes = [row("latest", 9200)];
  let hook, view;
  function Harness({ session, target }) {
    hook = useBodyAutoScroll({ activeSessionKey: session, isChatViewActive: true, navigationTargetSessionKey: target });
    return createElement("div", { ref: hook.bodyRef });
  }
  const render = (session, target = null) => act(async () => {
    const tree = createElement(Harness, { session, target });
    if (view) view.update(tree);
    else view = create(tree, { createNodeMock: () => element });
  });
  try {
    await render("A");
    await act(async () => { hook.syncAfterContentReady(); hook.activateBottomButton(false); });
    assert.equal(hook.isBottomFollowLocked, false);
    await act(async () => hook.activateBottomButton(true));
    assert.equal(hook.isBottomFollowLocked, true);
    await act(async () => {
      element.listeners.get("wheel")({ deltaY: -100 });
      element.scrollTop -= 200;
      hook.handleBodyScroll();
      element.scrollHeight += 600;
      hook.preserveCurrentView();
      for (let i = 0; i < 60; i++) clock.frame();
    });
    assert.equal(hook.isFollowingBottom, true);
    assert.equal(element.scrollTop, element.scrollHeight - element.clientHeight);
    await render("B");
    assert.equal(hook.isBottomFollowLocked, false);
    await render("A");
    assert.equal(hook.isBottomFollowLocked, true);
    await act(async () => hook.activateBottomButton(false));
    assert.equal(hook.isBottomFollowLocked, false);
    await act(async () => {
      element.listeners.get("wheel")({ deltaY: -100 });
      element.scrollTop -= 200;
      hook.handleBodyScroll();
    });
    assert.equal(hook.isFollowingBottom, false);
    await act(async () => hook.activateBottomButton(true));
    await render("A", "A");
    assert.equal(hook.isBottomFollowLocked, false);
    assert.equal(hook.isFollowingBottom, false);
  } finally { if (view) await act(async () => view.unmount()); }
});
