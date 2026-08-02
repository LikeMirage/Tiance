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
const { DesktopFileDropCoordinator } = await vite.ssrLoadModule(
  "/src/features/desktop-shell/model/desktopFileDropBridge.ts",
);

after(async () => {
  await vite.close();
});

test("带相同 dropId 的原生路径先到时仍能建立引用", () => {
  const harness = createHarness("composer");

  harness.coordinator.receiveNativeDrop(drop("drop-1", "composer", "early.md"));
  harness.coordinator.beginTargetDrop("drop-1");

  assert.deepEqual(harness.receivedNames, ["early.md"]);
  harness.advance(1_000);
  assert.deepEqual(harness.unavailableReasons, []);
});

test("目标 drop 先到时只接收相同 dropId 的原生路径", () => {
  const harness = createHarness("composer");

  harness.coordinator.beginTargetDrop("drop-current");
  harness.coordinator.receiveNativeDrop(drop("drop-other", "composer", "wrong.md"));
  assert.deepEqual(harness.receivedNames, []);

  harness.coordinator.receiveNativeDrop(drop("drop-current", "composer", "current.md"));
  assert.deepEqual(harness.receivedNames, ["current.md"]);
  harness.advance(1_000);
  assert.deepEqual(harness.unavailableReasons, []);
});

test("其他拖拽目标的路径不会进入当前目标缓冲区", () => {
  const harness = createHarness("composer");

  harness.coordinator.receiveNativeDrop(drop("drop-1", "project-tree", "other.md"));
  harness.coordinator.beginTargetDrop("drop-1");
  harness.advance(1_000);

  assert.deepEqual(harness.receivedNames, []);
  assert.deepEqual(harness.unavailableReasons, ["native_path_timeout"]);
});

test("页面没有注入 dropId 时立即报告桌面桥不可用", () => {
  const harness = createHarness("composer");

  harness.coordinator.beginTargetDrop(null);

  assert.deepEqual(harness.unavailableReasons, ["native_bridge_unavailable"]);
});

test("有 dropId 但原生路径未返回时才报告超时", () => {
  const harness = createHarness("composer");

  harness.coordinator.beginTargetDrop("drop-timeout");
  harness.advance(999);
  assert.deepEqual(harness.unavailableReasons, []);
  harness.advance(1);
  assert.deepEqual(harness.unavailableReasons, ["native_path_timeout"]);
});

function createHarness(targetId) {
  let now = 0;
  let nextTimerId = 0;
  const receivedNames = [];
  const timers = new Map();
  const unavailableReasons = [];
  const coordinator = new DesktopFileDropCoordinator({
    bufferLifetimeMs: 1_000,
    targetId,
    onFileDrop: (event) => {
      if (event.kind === "resolved") {
        receivedNames.push(...event.entries.map((entry) => entry.name));
      } else {
        unavailableReasons.push(event.reason);
      }
    },
    schedule: (callback, delayMs) => {
      const timerId = ++nextTimerId;
      timers.set(timerId, { callback, dueAt: now + delayMs });
      return timerId;
    },
    cancel: (timerId) => timers.delete(timerId),
    waitTimeoutMs: 1_000,
  });
  const advance = (durationMs) => {
    now += durationMs;
    const dueTimers = [...timers.entries()]
      .filter(([, timer]) => timer.dueAt <= now)
      .sort((left, right) => left[1].dueAt - right[1].dueAt);
    for (const [timerId, timer] of dueTimers) {
      if (!timers.delete(timerId)) continue;
      timer.callback();
    }
  };
  return {
    advance,
    coordinator,
    receivedNames,
    unavailableReasons,
  };
}

function drop(dropId, targetId, name) {
  return {
    dropId,
    targetId,
    entries: [{ kind: "file", name, path: `C:\\Temp\\${name}` }],
  };
}
