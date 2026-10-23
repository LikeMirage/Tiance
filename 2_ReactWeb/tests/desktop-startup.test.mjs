import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

const source = readFileSync(
  new URL("../../3_PyWebView/assets/startup/startup.js", import.meta.url),
  "utf8",
);

async function createStartup({ health = [true], app = [true], dev = false, backendOk = true, desktopAuth = true } = {}) {
  const statuses = [];
  const probes = [];
  const navigations = [];
  const timers = [];
  const listeners = new Map();
  let backendCalls = 0;
  let desktopAuthCalls = 0;
  const elements = new Map();
  const state = {
    apiUrl: "http://127.0.0.1:18000",
    gatewayHealthUrl: "http://127.0.0.1:18000/gateway/health",
    devUrl: "http://127.0.0.1:18100",
    appUrl: "http://127.0.0.1:18000/app/",
    distExists: true,
    bootTheme: {},
  };
  const next = (results) => results.length > 1 ? results.shift() : results[0];
  const context = {
    URL,
    URLSearchParams,
    __TIANCE_STARTUP_STATE__: state,
    __TIANCE_STARTUP_CONFIG__: {
      initialDelayMs: 80, fastRetryAttempts: 25, fastRetryDelayMs: 200,
      retryDelayMs: 900, maxAttempts: 3, defaultTimeoutMs: 260,
      apiTimeoutMs: 300, appTimeoutMs: 700, devTimeoutMs: 180,
    },
    document: {
      body: { dataset: {} },
      getElementById(id) {
        if (!elements.has(id)) {
          elements.set(id, {
            get textContent() { return this.text; },
            set textContent(value) {
              this.text = value;
              if (id === "summary") statuses.push(value);
            },
            setAttribute() {},
            addEventListener(event, callback) { listeners.set(`${id}:${event}`, callback); },
          });
        }
        return elements.get(id);
      },
    },
    window: {
      pywebview: { api: {
        reveal_window: async () => {},
        ensure_backend_running: async () => { backendCalls += 1; return { ok: backendOk }; },
        prepare_gateway_access: async () => { desktopAuthCalls += 1; return desktopAuth; },
        check_url_available: async (url) => {
          probes.push(url);
          if (url === state.gatewayHealthUrl) return next(health);
          if (url === state.appUrl) return next(app);
          return dev;
        },
      } },
      location: { href: "http://127.0.0.1/startup", replace: (url) => navigations.push(url) },
      setTimeout: (callback) => { timers.push(callback); return timers.length; },
    },
  };
  runInNewContext(source, context);
  await new Promise(setImmediate);
  return {
    statuses, probes, navigations, timers,
    get backendCalls() { return backendCalls; },
    get desktopAuthCalls() { return desktopAuthCalls; },
    async tick() { assert.ok(timers.length); await timers.shift()(); },
    async retry() {
      listeners.get("open-target:click")();
      await new Promise(setImmediate);
    },
    async checkAgain() { await context.runStartupCheck(); },
  };
}

test("local page waits do not replay completed startup stages or announce entry early", async () => {
  const startup = await createStartup({ app: [false, false, true] });
  await startup.tick();
  assert.equal(startup.navigations.length, 0);
  assert.ok(!startup.statuses.includes("正在进入本地页面"));
  const waitingStatus = startup.statuses.at(-1);
  const statusCount = startup.statuses.length;
  await startup.tick();
  assert.equal(startup.statuses.at(-1), waitingStatus);
  assert.equal(startup.statuses.length, statusCount);
  await startup.tick();
  assert.equal(startup.backendCalls, 1);
  assert.equal(startup.desktopAuthCalls, 1);
  assert.equal(startup.probes.filter((url) => url.endsWith("/gateway/health")).length, 1);
  assert.equal(startup.probes.filter((url) => url.endsWith("/@vite/client")).length, 1);
  assert.equal(startup.statuses.filter((text) => text === "正在进入本地页面").length, 1);
  assert.equal(startup.navigations.length, 1);
  await startup.checkAgain();
  assert.equal(startup.navigations.length, 1);
});

test("gateway waits keep one startup operation and only proceed after readiness", async () => {
  const startup = await createStartup({ health: [false, true] });
  await startup.tick();
  assert.equal(startup.probes.length, 1);
  assert.equal(startup.desktopAuthCalls, 0);
  await startup.tick();
  assert.equal(startup.backendCalls, 1);
  assert.equal(startup.navigations.length, 1);
  assert.equal(startup.desktopAuthCalls, 1);
});

test("desktop identity failure prevents opening either frontend", async () => {
  const startup = await createStartup({ dev: true, desktopAuth: false });
  await startup.tick();
  assert.equal(startup.statuses.at(-1), "启动失败");
  assert.equal(startup.navigations.length, 0);
  assert.equal(startup.probes.length, 1);
  assert.equal(startup.timers.length, 0);
});

test("development frontend remains preferred when available", async () => {
  const startup = await createStartup({ dev: true });
  await startup.tick();
  assert.ok(startup.navigations[0].startsWith("http://127.0.0.1:18100/"));
  assert.ok(!startup.probes.some((url) => url.endsWith("/app/")));
});

test("page failure settles at the configured attempt limit and manual retry can recover", async () => {
  const app = [false];
  const startup = await createStartup({ app });
  await startup.tick();
  await startup.tick();
  await startup.tick();
  assert.equal(startup.statuses.at(-1), "启动失败");
  assert.equal(startup.timers.length, 0);
  assert.equal(startup.navigations.length, 0);
  app[0] = true;
  await startup.retry();
  assert.equal(startup.navigations.length, 1);
});

test("overlapping checks cannot duplicate probes or navigation", async () => {
  const startup = await createStartup();
  await Promise.all([startup.tick(), startup.checkAgain(), startup.retry()]);
  assert.equal(startup.backendCalls, 1);
  assert.equal(startup.navigations.length, 1);
});

test("backend startup failure does not schedule an automatic restart", async () => {
  const startup = await createStartup({ backendOk: false });
  await startup.tick();
  assert.equal(startup.statuses.at(-1), "启动失败");
  assert.equal(startup.timers.length, 0);
  assert.equal(startup.probes.length, 0);
});
