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
const { resolveActiveSessionLiveReloadMode } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/useChatPanelLifecycleEffects.ts",
);

after(async () => {
  await vite.close();
});

test("前台 WebSocket 流式会话只同步会话状态", () => {
  assert.equal(resolveMode({
    activeRuntimeStatus: "running",
    isActiveSessionStreaming: true,
  }), "session-only");
});

test("后台运行会话读取消息以追赶后端进度", () => {
  assert.equal(resolveMode({
    activeRuntimeStatus: "running",
    isActiveSessionStreaming: false,
  }), "messages-and-session");
});

test("后台压缩同样读取消息以同步压缩状态", () => {
  assert.equal(resolveMode({
    activeRuntimeStatus: "idle",
    isActiveSessionStreaming: false,
    isCompactionRunning: true,
  }), "messages-and-session");
});

test("空闲、隐藏或没有活动会话时停止轮询", () => {
  assert.equal(resolveMode({ activeRuntimeStatus: "idle" }), "off");
  assert.equal(resolveMode({ activeRuntimeStatus: "running", isActive: false }), "off");
  assert.equal(resolveMode({ activeRuntimeStatus: "running", hasActiveTarget: false }), "off");
});

function resolveMode(overrides = {}) {
  return resolveActiveSessionLiveReloadMode({
    activeRuntimeStatus: null,
    hasActiveTarget: true,
    isActive: true,
    isActiveSessionStreaming: false,
    isCompactionRunning: false,
    ...overrides,
  });
}
