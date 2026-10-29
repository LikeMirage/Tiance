import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const shell = await vite.ssrLoadModule("/src/features/desktop-shell/model/desktopShellStore.ts");
const closeRequests = await vite.ssrLoadModule("/src/features/desktop-shell/model/desktopCloseRequest.ts");
after(() => vite.close());

const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const turn = () => new Promise(setImmediate);

function setup(t, overrides = {}) {
  const calls = [], timers = new Map();
  let sequence = 0;
  const api = {
    get_window_state: async () => ({ maximized: false, frameless: true, minWidth: 800, minHeight: 600 }),
    get_window_bounds: async () => ({ width: 1000, height: 750 }),
    close_window: async () => calls.push("close"),
    hide_window_to_tray: async () => { calls.push("hide"); return true; },
    ...overrides,
  };
  t.mock.method(console, "warn", () => {});
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.document = { addEventListener() {} };
  globalThis.window = {
    pywebview: { api },
    addEventListener() {},
    setTimeout: (fn, ms) => { const id = ++sequence; timers.set(id, { fn, ms }); return id; },
    clearTimeout: (id) => timers.delete(id),
  };
  t.after(() => { globalThis.window = previousWindow; globalThis.document = previousDocument; });
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    calls.push("save");
    return new Response(JSON.stringify({ ...JSON.parse(init.body), version: 1 }));
  });
  return { calls, timers, expire() {
    assert.equal(timers.size, 1);
    const timer = [...timers.values()][0];
    assert.equal(timer.ms, 2500);
    timer.fn();
  } };
}

// Define the browser surface once so node:test can restore its mocked value.
globalThis.window = undefined;
after(() => { delete globalThis.window; });

test("退出和收起托盘正常保存尺寸后执行原生操作", async (t) => {
  const { calls, timers } = setup(t);
  await shell.closeDesktopShell("request-1");
  assert.equal(await shell.hideDesktopShellToTray(), true);
  assert.deepEqual(calls, ["save", "close", "save", "hide"]);
  assert.equal(timers.size, 0);
});

test("保存尺寸请求卡住时中止请求并继续退出，不无限等待", async (t) => {
  const context = setup(t);
  let signal;
  t.mock.method(globalThis, "fetch", (_url, init) => {
    signal = init.signal;
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
  });
  const exiting = shell.closeDesktopShell("request-1");
  await turn();
  assert.ok(signal);
  assert.deepEqual(context.calls, []);
  context.expire();
  await exiting;
  assert.ok(signal.aborted);
  assert.deepEqual(context.calls, ["close"]);
  assert.equal(context.timers.size, 0);
});

test("原生尺寸查询卡住也有界限，迟到结果不再发保存请求", async (t) => {
  const bounds = deferred();
  const context = setup(t, { get_window_bounds: () => bounds.promise });
  const hiding = shell.hideDesktopShellToTray();
  await turn();
  context.expire();
  assert.equal(await hiding, true);
  bounds.resolve({ width: 1100, height: 800 });
  await turn();
  assert.deepEqual(context.calls, ["hide"]);
});

test("偏好等待超时不越过后端安装收尾，原生关闭失败向调用方报告", async (t) => {
  const commit = deferred();
  const context = setup(t, { close_window: () => commit.promise });
  let settled = false;
  const exiting = shell.closeDesktopShell().then(() => { settled = true; });
  await turn();
  assert.equal(context.timers.size, 0);
  assert.equal(settled, false);
  commit.resolve();
  await exiting;
  window.pywebview.api.close_window = async () => { throw new Error("退出准备失败"); };
  await assert.rejects(shell.closeDesktopShell(), /退出准备失败/);
});

test("标题栏请求交给壳统一处理，完成时携带对应请求 ID", async (t) => {
  const requests = [], completed = [];
  setup(t, {
    request_window_close: async (intent) => { requests.push(intent); return "request-1"; },
    close_window: async (id) => { completed.push(id); return true; },
  });
  assert.equal(await closeRequests.requestDesktopWindowClose(), true);
  assert.deepEqual(requests, ["close"]);
  assert.equal(await shell.closeDesktopShell("request-1"), true);
  assert.deepEqual(completed, ["request-1"]);
  await closeRequests.requestDesktopWindowClose("exit");
  assert.deepEqual(requests, ["close", "exit"]);
  delete window.pywebview.api.request_window_close;
  await assert.rejects(closeRequests.requestDesktopWindowClose(), TypeError);
});

function closeHeartbeat(t, overrides = {}) {
  const reports = [], intervals = new Map();
  setup(t, {
    report_window_close: async (...args) => { reports.push(args); return true; },
    ...overrides,
  });
  let sequence = 0;
  t.mock.method(globalThis, "setInterval", (fn, delay) => {
    assert.equal(delay, 1000);
    const id = ++sequence;
    intervals.set(id, fn);
    return id;
  });
  t.mock.method(globalThis, "clearInterval", (id) => intervals.delete(id));
  return { reports, intervals, tick: async () => {
    for (const fn of intervals.values()) fn();
    await turn();
  } };
}

test("仅关闭过程中回报等待和保存状态，取消后停止", async (t) => {
  const context = closeHeartbeat(t);
  assert.equal(context.intervals.size, 0);
  const request = closeRequests.observeDesktopCloseRequest("one");
  await turn();
  request.setState("saving");
  await turn();
  await context.tick();
  request.cancel();
  await turn();
  assert.equal(context.intervals.size, 0);
  assert.deepEqual(context.reports, [
    ["one", "waiting"], ["one", "saving"], ["one", "saving"], ["one", "cancelled"],
  ]);
  request.cancel();
  assert.equal(context.reports.length, 4);
});

test("壳已接管或旧请求失效时停止回报，组件卸载不冒充用户取消", async (t) => {
  const context = closeHeartbeat(t);
  const old = closeRequests.observeDesktopCloseRequest("old");
  await turn();
  old.stop();
  assert.deepEqual(context.reports, [["old", "waiting"]]);
  assert.equal(context.intervals.size, 0);
  window.pywebview.api.report_window_close = async (...args) => {
    context.reports.push(args);
    return false;
  };
  const next = closeRequests.observeDesktopCloseRequest("new");
  await turn();
  next.cancel();
  assert.equal(context.intervals.size, 0);
  assert.deepEqual(context.reports, [["old", "waiting"], ["new", "waiting"]]);
});

test("回报调用卡住时不堆积请求，壳侧超时仍独立处理", async (t) => {
  const pending = deferred();
  let count = 0;
  const context = closeHeartbeat(t, { report_window_close: () => { count += 1; return pending.promise; } });
  const request = closeRequests.observeDesktopCloseRequest("one");
  for (let i = 0; i < 20; i += 1) await context.tick();
  assert.equal(count, 1);
  request.stop();
  pending.resolve(false);
  await turn();
  assert.equal(context.intervals.size, 0);
});
