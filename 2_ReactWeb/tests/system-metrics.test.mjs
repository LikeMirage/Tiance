import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../", import.meta.url));
function loadHook(name = "useSystemMetrics", resolve = require) {
  const filename = path.join(root, `src/widgets/app-frame/model/${name}.ts`);
  const js = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    fileName: filename, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename })(resolve, module, module.exports);
  return module.exports;
}
const snapshot = time => ({ available: true, sampledAt: new Date(time).toISOString(),
  app: { cpuPercent: 5, memoryBytes: 500, processCount: 3 },
  system: { cpuPercent: 20, memoryAvailableBytes: 6000, memoryTotalBytes: 10000, memoryUsedBytes: 4000, memoryPercent: 40 } });

async function mount(t, detailed = false, storage = false) {
  const previous = { window: globalThis.window, document: globalThis.document, now: Date.now };
  const timers = new Map(), requests = [];
  let time = 1_800_000_000_000, serial = 0, current, renderer, active = detailed;
  Date.now = () => time;
  globalThis.window = { setTimeout: (fn, delay) => { const id = ++serial; timers.set(id, { fn, delay }); return id; }, clearTimeout: id => timers.delete(id),
    pywebview: { api: { get_system_metrics: () => new Promise((resolve, reject) => requests.push({ resolve, reject })) } } };
  globalThis.document = new EventTarget();
  document.visibilityState = "visible";
  const useHook = storage ? loadHook("useWorkspaceStorage", name => name.endsWith("getWorkspaceStorage")
    ? { getWorkspaceStorage: signal => new Promise((resolve, reject) => requests.push({ resolve, reject, signal })) }
    : require(name)).useWorkspaceStorage : loadHook().useSystemMetrics;
  function Harness({ detailed }) { current = storage ? useHook(detailed) : useHook(true, detailed); return null; }
  await act(async () => { renderer = create(React.createElement(Harness, { detailed: active })); });
  const unmount = async () => { if (renderer) { await act(async () => renderer.unmount()); renderer = null; } };
  t.after(async () => { await unmount(); globalThis.window = previous.window; globalThis.document = previous.document; Date.now = previous.now; });
  return { requests, timers, unmount, get current() { return current; },
    get delay() { assert.equal(timers.size, 1); return [...timers.values()][0].delay; },
    advance: ms => { time += ms; },
    fire: async () => { assert.equal(timers.size, 1); const [id, timer] = [...timers.entries()][0]; timers.delete(id); time += timer.delay; await act(async () => timer.fn()); },
    finish: async (index, data) => act(async () => requests[index].resolve(data ?? snapshot(time))),
    reject: async index => act(async () => requests[index].reject(new Error("bridge failed"))),
    update: async detailed => act(async () => { active = detailed; renderer.update(React.createElement(Harness, { detailed: active })); }),
    visibility: async value => act(async () => { document.visibilityState = value; document.dispatchEvent(new Event("visibilitychange")); }),
  };
}

test("性能页 5 秒、其他状态 15 秒，同一时刻仅一个请求", async t => {
  const h = await mount(t);
  assert.equal(h.delay, 0);
  await h.fire();
  assert.equal(h.requests.length, 1);
  await h.update(true);
  await h.update(false);
  assert.equal(h.timers.size, 0);
  assert.equal(h.requests.length, 1);
  await h.finish(0);
  assert.equal(h.delay, 15000);
  h.advance(1000);
  await h.update(true);
  assert.equal(h.delay, 4000);
  await h.fire();
  assert.equal(h.requests.length, 2);
  await h.finish(1);
  assert.equal(h.delay, 5000);
  await h.update(false);
  assert.equal(h.delay, 15000);
});

test("隐藏时停止采样，返回后恢复，隐藏期间忽略迟到结果", async t => {
  const h = await mount(t, true);
  await h.fire();
  await h.visibility("hidden");
  await h.finish(0);
  assert.equal(h.timers.size, 0);
  assert.equal(h.current.status.state, "loading");
  h.advance(60000);
  await h.visibility("visible");
  assert.equal(h.delay, 0);
  await h.fire();
  await h.finish(1);
  assert.equal(h.current.status.state, "ready");
  await h.visibility("hidden");
  assert.equal(h.timers.size, 0);
});

test("桥接错误不会加速重试，卸载后迟到请求不能重启采样", async t => {
  const h = await mount(t, true);
  await h.fire();
  await h.reject(0);
  assert.equal(h.current.status.state, "unavailable");
  assert.equal(h.delay, 5000);
  await h.fire();
  await h.unmount();
  await h.finish(1);
  assert.equal(h.timers.size, 0);
});

const storageData = { total_bytes: 100, database_bytes: 60, other_bytes: 40, complete: true, sampled_at: "2026-10-23T00:00:00Z" };

test("存储只在展开时请求，重复开关复用五分钟缓存，隐藏时无定时器", async t => {
  const h = await mount(t, false, true);
  assert.equal(h.timers.size, 0);
  await h.update(true);
  assert.equal(h.delay, 0);
  await h.fire();
  await h.finish(0, storageData);
  assert.equal(h.delay, 300000);
  assert.deepEqual(h.current.data, storageData);
  await h.update(false);
  assert.equal(h.timers.size, 0);
  h.advance(10000);
  await h.update(true);
  assert.equal(h.delay, 290000);
  assert.equal(h.requests.length, 1);
  await h.visibility("hidden");
  assert.equal(h.timers.size, 0);
  h.advance(300000);
  await h.visibility("visible");
  assert.equal(h.delay, 0);
  await h.fire();
  await h.finish(1, storageData);
  assert.equal(h.requests.length, 2);
});

test("存储关闭时取消请求且忽略迟到结果，失败不会高频重试", async t => {
  const h = await mount(t, true, true);
  await h.fire();
  await h.update(false);
  assert.equal(h.requests[0].signal.aborted, true);
  await h.finish(0, storageData);
  assert.equal(h.current.data, null);
  assert.equal(h.timers.size, 0);
  await h.update(true);
  await h.fire();
  await h.reject(1);
  assert.equal(h.current.error, true);
  assert.equal(h.delay, 300000);
});
