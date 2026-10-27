import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";

function fixture(bridge, fetchError) {
  const events = [], requests = [], timers = new Map(), cache = new Map();
  const root = fileURLToPath(new URL("../src/", import.meta.url));
  const context = {
    window: bridge === undefined ? {} : { pywebview: { api: { prepare_file_explorer: bridge } } },
    setTimeout: (callback, ms) => { const timer = {}; timers.set(timer, { callback, ms }); return timer; },
    clearTimeout: (timer) => timers.delete(timer),
  };
  const fetchNoContent = async (url, init) => {
    events.push("request");
    requests.push({ url, ...init });
    if (fetchError) throw fetchError;
  };
  function load(relative) {
    const filename = path.resolve(root, relative.endsWith(".ts") ? relative : `${relative}.ts`);
    if (cache.has(filename)) return cache.get(filename);
    const exports = {};
    cache.set(filename, exports);
    const code = ts.transpileModule(readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    vm.runInNewContext(code, {
      ...context, exports,
      require: (name) => name.endsWith("/httpClient") ? { fetchNoContent }
        : load(path.resolve(path.dirname(filename), name)),
    });
    return exports;
  }
  return { load, events, requests, timers };
}

test("foreground grant completes before exactly one reveal request", async () => {
  let grant;
  const app = fixture(() => { app.events.push("bridge"); return new Promise((resolve) => { grant = resolve; }); });
  const call = app.load("services/desktop/localPathApi").revealDesktopLocalPath("C:/测试, 文件夹");
  await new Promise(setImmediate);
  assert.deepEqual(app.events, ["bridge"]);
  grant(true);
  await call;
  assert.deepEqual(app.events, ["bridge", "request"]);
  assert.deepEqual(app.requests, [{ url: "/api/desktop/local-path/reveal", method: "POST", body: '{"path":"C:/测试, 文件夹"}' }]);
  assert.equal(app.timers.size, 0);
});

for (const [label, bridge] of [
  ["browser/old shell", undefined],
  ["denied permission", () => false],
  ["rejected bridge", () => Promise.reject(new Error("unavailable"))],
  ["throwing bridge", () => { throw new Error("unavailable"); }],
]) {
  test(`${label} still opens through the existing backend`, async () => {
    const app = fixture(bridge);
    await app.load("services/desktop/localPathApi").revealDesktopLocalPath("C:/folder");
    assert.equal(app.requests.length, 1);
    assert.equal(app.timers.size, 0);
  });
}

test("unresponsive bridge is bounded and a late response never opens twice", async () => {
  let grant;
  const app = fixture(() => new Promise((resolve) => { grant = resolve; }));
  const call = app.load("services/desktop/localPathApi").revealDesktopLocalPath("C:/folder");
  await new Promise(setImmediate);
  assert.equal(app.requests.length, 0);
  const [timer] = app.timers.values();
  assert.equal(timer.ms, 500);
  timer.callback();
  await call;
  grant(true);
  await new Promise(setImmediate);
  assert.equal(app.requests.length, 1);
  assert.equal(app.timers.size, 0);
});

test("backend reveal failures still propagate", async () => {
  const error = new Error("path unavailable");
  const app = fixture(() => true, error);
  await assert.rejects(app.load("services/desktop/localPathApi").revealDesktopLocalPath("C:/missing"), error);
});

test("all reveal services share the grant and preserve endpoint payloads", async () => {
  let grants = 0;
  const app = fixture(() => { grants++; return true; });
  await app.load("services/project/revealProjectFile").revealProjectFile("project/id", { path: "file.txt" });
  await app.load("services/tools/revealToolFolder").revealToolFolder("set/id", "folder/id");
  await app.load("services/llm/revealProviderCatalogEntry").revealProviderCatalogEntry("provider/id");
  await app.load("services/tools/toolFolderFileWorkspaceApi").revealToolFolderFile("set/id", "folder/id", { path: "file.txt" });
  assert.equal(grants, 4);
  assert.deepEqual(app.requests.map((request) => [request.url, request.method, request.body]), [
    ["/api/projects/project%2Fid/files/reveal", "POST", '{"path":"file.txt"}'],
    ["/api/tools/categories/set%2Fid/projects/folder%2Fid/reveal", "POST", undefined],
    ["/api/llm/catalog/providers/provider%2Fid/reveal", "POST", undefined],
    ["/api/tools/categories/set%2Fid/projects/folder%2Fid/files/reveal", "POST", '{"path":"file.txt"}'],
  ]);
});

test("default application opening does not acquire Explorer foreground permission", async () => {
  let grants = 0;
  const app = fixture(() => { grants++; return true; });
  await app.load("services/desktop/localPathApi").openDesktopLocalPath("C:/file.txt");
  assert.equal(grants, 0);
  assert.equal(app.requests[0].url, "/api/desktop/local-path/open-default");
});
