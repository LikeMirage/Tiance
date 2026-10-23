import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import ts from "typescript";

const source = readFileSync(new URL("../src/services/security/gatewaySessionLifecycle.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

function fixture() {
  const listeners = new Map(), intervals = new Map(), requests = [], beacons = [];
  let now = 100_000, next = 0, expired = 0, status = 200;
  const exports = {};
  const context = vm.createContext({
    exports, crypto: webcrypto, AbortController, Blob, Uint8Array,
    Date: class extends Date { static now() { return now; } },
    require: (name) => name.endsWith("/env") ? { env: { apiBaseUrl: "http://127.0.0.1:18000" } }
      : { notifyGatewayAuthenticationRequired: () => expired++ },
    window: {
      addEventListener: (event, callback) => listeners.set(event, callback),
      removeEventListener: (event) => listeners.delete(event),
    },
    navigator: { sendBeacon: (url, body) => { beacons.push({ url, body }); return true; } },
    setInterval: (callback) => { intervals.set(++next, callback); return next; },
    clearInterval: (id) => intervals.delete(id),
    setTimeout: () => ++next, clearTimeout: () => {},
    fetch: async (url, options) => { requests.push({ url, ...options, json: JSON.parse(options.body) }); return { status, ok: status === 200 }; },
  });
  vm.runInContext(code, context);
  return { ...exports, requests, beacons, listeners, intervals,
    advance: (ms) => { now += ms; },
    tick: async () => { for (const callback of intervals.values()) callback(); await settle(); },
    dispatch: async (name, event = { isTrusted: true }) => { listeners.get(name)?.(event); await settle(); },
    expire: () => { status = 401; }, get expired() { return expired; },
  };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("presence heartbeats do not invent user activity; trusted input is reported once", async () => {
  const app = fixture();
  await app.configureGatewaySession("browser");
  assert.equal(app.requests[0].json.activity, false);
  app.advance(30_000); await app.tick();
  assert.equal(app.requests.at(-1).json.activity, false);
  await app.dispatch("keydown", { isTrusted: false });
  app.advance(30_000); await app.tick();
  assert.equal(app.requests.at(-1).json.activity, false);
  // Browser-generated scroll events also occur during AI auto-scroll.
  assert.equal(app.listeners.has("scroll"), false);
  app.advance(30_000); await app.dispatch("wheel");
  assert.equal(app.requests.at(-1).json.activity, true);
  app.advance(30_000); await app.tick();
  assert.equal(app.requests.at(-1).json.activity, false);
});

test("closing leaves only this page; bfcache restore uses a new page identity", async () => {
  const app = fixture();
  await app.configureGatewaySession("browser");
  const first = app.requests.at(-1).json.pageId;
  assert.equal(app.listeners.has("visibilitychange"), false);
  await app.dispatch("pagehide");
  assert.equal(app.intervals.size, 0);
  assert.equal(JSON.parse(await app.beacons[0].body.text()).pageId, first);
  await app.dispatch("pageshow");
  assert.notEqual(app.requests.at(-1).json.pageId, first);
  assert.equal(app.intervals.size, 1);
});

test("server expiry stops polling and requests one login recovery", async () => {
  const app = fixture();
  await app.configureGatewaySession("browser");
  app.expire(); await app.tick();
  assert.equal(app.expired, 1);
  assert.equal(app.intervals.size, 0);
  assert.equal(app.listeners.size, 0);
});

test("native desktop sessions and password-free mode need no browser polling", async () => {
  const app = fixture();
  await app.configureGatewaySession("desktop");
  await app.configureGatewaySession("none");
  assert.equal(app.requests.length, 0);
  await app.configureGatewaySession("browser");
  await app.configureGatewaySession("desktop");
  assert.equal(app.intervals.size, 0);
  assert.equal(app.listeners.size, 0);
});
