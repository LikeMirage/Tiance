import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const { ChatSocketEventBuffer } = await vite.ssrLoadModule(
  "/src/services/llm/chatSocketEventBuffer.ts",
);

after(async () => {
  await vite.close();
});

test("前端会话流待处理事件达到数量上限后明确拒绝继续堆积", () => {
  const buffer = new ChatSocketEventBuffer(2, 1_000);

  assert.equal(buffer.tryPush({ kind: "delta", content: "a" }), true);
  assert.equal(buffer.tryPush({ kind: "delta", content: "b" }), true);
  assert.equal(buffer.tryPush({ kind: "delta", content: "c" }), false);

  const first = buffer.take();
  assert.ok(first);
  buffer.release(first);
  assert.equal(buffer.tryPush({ kind: "delta", content: "c" }), true);
});

test("前端会话流按内容体积限流，但允许单个超大持久化事件通过", () => {
  const buffer = new ChatSocketEventBuffer(10, 20);

  assert.equal(buffer.tryPush({ content: "x".repeat(100) }), true);
  assert.equal(buffer.tryPush({ content: "next" }), false);

  const oversized = buffer.take();
  assert.ok(oversized);
  buffer.release(oversized);
  assert.equal(buffer.tryPush({ content: "next" }), true);
});
