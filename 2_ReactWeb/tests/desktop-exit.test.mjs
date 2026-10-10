import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const shell = await vite.ssrLoadModule("/src/features/desktop-shell/model/desktopShellStore.ts");
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
  await shell.closeDesktopShell();
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
  const exiting = shell.closeDesktopShell();
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
