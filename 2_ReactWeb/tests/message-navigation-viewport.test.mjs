import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createElement } from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { buildMessageTurnNumbers, readMessageViewport, resolveViewportTurnNumber, useMessageNavigatorActiveTurn } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/useMessageNavigatorActiveTurn.ts");

test("只有回复正文的末页也能用完整目录定位所属提问", () => {
  const map = buildMessageTurnNumbers([{ id: "reply-120", role: "assistant" }], [
    { userMessageId: "user-120", turnNumber: 120, assistantMessageId: "reply-120" },
  ]);
  assert.equal(map.get("reply-120"), 120);
});

test("未索引的新提问不会被归到上一个提问", () => {
  const map = buildMessageTurnNumbers([
    { id: "old", role: "user" }, { id: "new", role: "user" }, { id: "new-reply", role: "assistant" },
  ], [{ userMessageId: "old", turnNumber: 2 }]);
  assert.equal(map.get("old"), 2);
  assert.equal(map.has("new-reply"), false);
});

test("可见内容检测独立于目录是否加载，使用稳定行标识保护阅读中的回复", () => {
  const row = (id, key, top, bottom) => ({ dataset: { chatMessageId: id, chatMessageKey: key },
    getBoundingClientRect: () => ({ top, bottom }) });
  const body = { getBoundingClientRect: () => ({ top: 100, bottom: 500 }),
    querySelectorAll: () => [row("above", "above-key", 0, 100), row("reply", "stable-live-key", 100, 600),
      row("new", "new-key", 600, 900)] };
  const withoutIndex = readMessageViewport(body, new Map(), new Map());
  assert.deepEqual([...withoutIndex.visibleMessageKeys], ["stable-live-key"]);
  assert.equal(withoutIndex.turnNumber, null);
  const withIndex = readMessageViewport(body, new Map([["reply", 120]]), new Map());
  assert.equal(withIndex.turnNumber, 120);
});

test("提问进入可视区域时导航高亮跟随该提问", () => {
  assert.equal(resolveViewportTurnNumber(100, 500, [
    { top: 0, bottom: 200, turnNumber: 5, isUserMessage: false },
    { top: 200, bottom: 300, turnNumber: 6, isUserMessage: true },
  ]), 6);
});

test("连续流式更新不反复取消可视区域测量，单回合或目录尚未加载时也能保护阅读", async t => {
  const previousWindow = globalThis.window;
  const frames = new Map();
  let frameId = 0;
  globalThis.window = { requestAnimationFrame(callback) { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame(id) { frames.delete(id); } };
  let value, view;
  const bodyRef = { current: { getBoundingClientRect: () => ({ top: 0, bottom: 500 }),
    querySelectorAll: () => [{ dataset: { chatMessageId: "reply", chatMessageKey: "stable" },
      getBoundingClientRect: () => ({ top: 0, bottom: 700 }) }] } };
  function Harness({ messages, sessionKey = "one" }) {
    value = useMessageNavigatorActiveTurn({ bodyRef, enabled: true, items: [], messages, sessionKey });
    return null;
  }
  t.after(async () => { if (view) await act(async () => view.unmount()); globalThis.window = previousWindow; });
  await act(async () => { view = create(createElement(Harness, { messages: [] })); });
  const firstFrame = frames.keys().next().value;
  for (let i = 0; i < 5; i++) await act(async () => view.update(createElement(Harness,
    { messages: [{ id: "reply", role: "assistant", content: String(i) }] })));
  assert.equal(frames.size, 1);
  assert.equal(frames.keys().next().value, firstFrame, "新输出不应饿死已有测量帧");
  const flush = async () => { const [id, callback] = frames.entries().next().value;
    frames.delete(id); await act(async () => callback()); };
  await flush(); await flush();
  assert.deepEqual([...value.visibleMessageKeys], ["stable"]);
  await act(async () => view.update(createElement(Harness, { sessionKey: "two", messages: [] })));
  assert.equal(value.visibleMessageKeys, null, "旧会话可视区域不能影响新会话");
});
