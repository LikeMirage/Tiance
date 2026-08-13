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
const {
  hasRecentCompactionStart,
  hasRunningMemoryCompactionChild,
  resolveActiveSessionLiveReloadMode,
} = await vite.ssrLoadModule(
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

test("只把短时间内的压缩开始消息作为启动过渡信号", () => {
  const message = {
    role: "system",
    name: "memory_compaction",
    status: "running",
    createdAt: 10_000,
  };
  assert.equal(hasRecentCompactionStart([message], 39_999), true);
  assert.equal(hasRecentCompactionStart([message], 40_001), false);
});

test("运行中的压缩功能子会话是持续轮询的权威状态", () => {
  const branchNodes = [{
    session_id: "function-session",
    parent_session_id: "source-session",
    relation_kind: "functional",
    function_type: "memory_compaction",
    deleted_at: null,
  }];
  assert.equal(hasRunningMemoryCompactionChild(
    "source-session",
    branchNodes,
    { "function-session": { runtime_status: "running" } },
  ), true);
  assert.equal(hasRunningMemoryCompactionChild(
    "source-session",
    branchNodes,
    { "function-session": { runtime_status: "idle" } },
  ), false);
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
