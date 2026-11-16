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
const { useRendererDiagnostics } = await vite.ssrLoadModule("/src/features/desktop-shell/model/useRendererDiagnostics.ts");
const { registerRendererDiagnosticSource, collectRendererSourceMetrics } = await vite.ssrLoadModule("/src/shared/diagnostics/rendererDiagnostics.ts");

test("sources report numeric counters, isolate failures and release references", () => {
  const stop = [
    registerRendererDiagnosticSource(() => ({ cached_messages: 2, largest_session_chars: 8, mobile_poll_age_ms: 5, content: "secret" })),
    registerRendererDiagnosticSource(() => ({ cached_messages: 3, largest_session_chars: 4, mobile_poll_age_ms: 9, bad: NaN })),
    registerRendererDiagnosticSource(() => { throw new Error("private"); }),
  ];
  try {
    assert.deepEqual(collectRendererSourceMetrics(), { cached_messages: 5, largest_session_chars: 8,
      mobile_poll_age_ms: 9, diagnostic_source_errors: 1 });
  } finally { stop.forEach(fn => fn()); }
  assert.deepEqual(collectRendererSourceMetrics(), { diagnostic_source_errors: 0 });
});

async function mount(t, bridgeAvailable = true) {
  const previous = { window: globalThis.window, document: globalThis.document };
  const timers = new Map(), requests = [], listeners = new Map();
  let serial = 0, view;
  globalThis.window = {
    pywebview: { api: bridgeAvailable ? { record_renderer_diagnostics: metrics => new Promise((resolve, reject) => requests.push({ metrics, resolve, reject })) } : {} },
    setTimeout: (fn, delay) => { const id = ++serial; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
  };
  globalThis.document = { visibilityState: "visible", getElementsByTagName: () => ({ length: 42 }) };
  function Probe() { useRendererDiagnostics(true); return null; }
  await act(async () => { view = create(createElement(Probe)); });
  const unmount = async () => { if (view) { await act(async () => view.unmount()); view = null; } };
  t.after(async () => { await unmount(); globalThis.window = previous.window; globalThis.document = previous.document; });
  return { timers, requests, listeners, unmount,
    fire: async () => { assert.equal(timers.size, 1); const [id, timer] = [...timers][0]; timers.delete(id); await act(async () => timer.fn()); },
    resolve: async index => { await act(async () => requests[index].resolve(true)); },
    reject: async index => { await act(async () => requests[index].reject(new Error("dead bridge"))); },
  };
}

test("sampling stays serial when bridge hangs and unmount cancels late rescheduling", async t => {
  const h = await mount(t);
  h.listeners.get("error")({ message: "private message" });
  h.listeners.get("unhandledrejection")({ reason: "private reason" });
  await h.fire();
  assert.equal(h.requests.length, 1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.requests[0].metrics.dom_nodes, 42);
  assert.equal(h.requests[0].metrics.js_errors, 1);
  assert.equal(h.requests[0].metrics.unhandled_rejections, 1);
  assert.ok(Object.values(h.requests[0].metrics).every(n => typeof n === "number" && Number.isFinite(n)));
  assert.ok(!JSON.stringify(h.requests[0].metrics).includes("private"));
  await h.resolve(0);
  assert.equal([...h.timers.values()][0].delay, 30_000);
  await h.fire();
  await h.unmount();
  await h.resolve(1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.listeners.size, 0);
});

test("failed bridge retries at normal interval, hidden page remains observable", async t => {
  const h = await mount(t);
  document.visibilityState = "hidden";
  await h.fire();
  assert.equal(h.requests[0].metrics.visible, 0);
  await h.reject(0);
  assert.equal([...h.timers.values()][0].delay, 30_000);
  await h.unmount();
  assert.equal(h.timers.size, 0);
});

test("browser or older running shell does not start bridge diagnostics", async t => {
  const h = await mount(t, false);
  assert.equal(h.timers.size, 0);
  assert.equal(h.listeners.size, 0);
});
