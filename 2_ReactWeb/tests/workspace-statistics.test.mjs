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
function loader(mocks = {}) {
  const cache = new Map();
  function load(relative) {
    let file = path.resolve(root, relative);
    if (!fs.existsSync(file)) file += fs.existsSync(file + ".ts") ? ".ts" : ".tsx";
    if (cache.has(file)) return cache.get(file);
    const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    const module = { exports: {} };
    vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file })(
      name => name in mocks ? mocks[name] : name.startsWith(".") ? load(path.resolve(path.dirname(file), name)) : require(name),
      module, module.exports,
    );
    cache.set(file, module.exports);
    return module.exports;
  }
  return load;
}

const modelPath = "src/widgets/app-frame/model/useWorkspaceUsageSummary.ts";
const statistics = total => ({ total, daily: [], ranking: [], conversation_count: 2, sent_message_count: 3 });
async function mount(t, initial = {}) {
  const requests = [], timers = new Map();
  let serial = 0, current, renderer, listener;
  const previousWindow = globalThis.window, previousDocument = globalThis.document;
  globalThis.window = { setTimeout: fn => { const id = ++serial; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id) };
  globalThis.document = new EventTarget();
  document.visibilityState = "visible";
  const { useWorkspaceUsageSummary } = loader({
    "../../../entities/llm-usage/model/usageRefreshEvents": { subscribeLlmUsageChanged: fn => { listener = fn; return () => { listener = null; }; } },
    "../../../services/workspace/getWorkspaceStatistics": { getWorkspaceStatistics: (kind, month, signal) => new Promise((resolve, reject) => requests.push({ kind, month, signal, resolve, reject })) },
  })(modelPath);
  let props = { kind: "tokens", month: "2026-10", enabled: true, ...initial };
  function Harness(values) { current = useWorkspaceUsageSummary(values.kind, values.month, values.enabled); return null; }
  await act(async () => { renderer = create(React.createElement(Harness, props)); });
  t.after(async () => {
    await act(async () => renderer.unmount());
    globalThis.window = previousWindow;
    globalThis.document = previousDocument;
  });
  return {
    requests, timers, get current() { return current; },
    update: async patch => act(async () => { props = { ...props, ...patch }; renderer.update(React.createElement(Harness, props)); }),
    finish: async (index, total) => act(async () => requests[index].resolve(statistics(total))),
    changed: async () => act(async () => listener?.()),
  };
}

test("隐藏时不取数，展开与再次展开都刷新", async t => {
  const h = await mount(t, { enabled: false });
  assert.equal(h.requests.length, 0);
  await h.update({ enabled: true });
  await h.finish(0, 10);
  assert.equal(h.current.data.total, 10);
  assert.equal(h.timers.size, 1);
  await h.update({ enabled: false });
  assert.equal(h.timers.size, 0);
  await h.update({ enabled: true });
  assert.equal(h.requests.length, 2);
  await h.finish(1, 20);
  assert.equal(h.current.data.total, 20);
});

test("切换月份取消旧请求，迟到数据不会覆盖新月份", async t => {
  const h = await mount(t);
  await h.update({ month: "2026-09" });
  assert.equal(h.requests[0].signal.aborted, true);
  await h.finish(1, 30);
  await h.finish(0, 999);
  assert.equal(h.current.data.total, 30);
  assert.equal(h.requests[1].month, "2026-09");
});

test("切换统计种类不会把 Token 数展示为耗时", async t => {
  const h = await mount(t);
  await h.finish(0, 999999);
  await h.update({ kind: "runtime" });
  assert.equal(h.current.data, null);
  await h.finish(1, 1000);
  assert.equal(h.current.data.total, 1000);
});

test("刷新不重叠，错误保留已有数值并允许重试", async t => {
  const h = await mount(t);
  await h.changed();
  assert.equal(h.requests.length, 1);
  await h.finish(0, 42);
  await h.changed();
  await act(async () => h.requests[1].reject(new Error("offline")));
  assert.equal(h.current.error, true);
  assert.equal(h.current.data.total, 42);
  await act(async () => h.current.refresh());
  await h.finish(2, 50);
  assert.equal(h.current.error, false);
  assert.equal(h.current.data.total, 50);
});

test("关闭后未完成请求不会写回，页面隐藏时暂停采样", async t => {
  const h = await mount(t);
  await h.update({ enabled: false });
  await h.finish(0, 999);
  assert.equal(h.current.data, null);
  document.visibilityState = "hidden";
  await h.update({ enabled: true });
  assert.equal(h.requests.length, 1);
  document.visibilityState = "visible";
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  assert.equal(h.requests.length, 2);
});

test("清零或同步计数后旧请求不能覆盖新值", async t => {
  const h = await mount(t);
  await h.finish(0, 10);
  await h.changed();
  await act(async () => h.current.setConversationTotal(0));
  assert.equal(h.requests[1].signal.aborted, true);
  await h.finish(1, 99);
  assert.equal(h.current.data.conversation_count, 0);
  await act(async () => h.requests[2].resolve({ ...statistics(10), conversation_count: 0 }));
  assert.equal(h.current.data.conversation_count, 0);
});

test("柱状图逐日显示，包含零值，月份缩短时移除多余日期", async t => {
  const { UsageDailyChart } = loader()("src/widgets/app-frame/ui/UsageDailyChart.tsx");
  const daily = count => Array.from({ length: count }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, value: i === 0 ? 0 : i * 1000 }));
  let renderer;
  await act(async () => { renderer = create(React.createElement(UsageDailyChart, { daily: daily(31), duration: false, language: "zh-CN", label: "每日 Token" })); });
  t.after(async () => act(async () => renderer.unmount()));
  const bars = () => renderer.root.findAllByProps({ className: "usage-daily-chart__bar" });
  assert.equal(bars().length, 31);
  assert.equal(bars()[0].props.height, 0);
  await act(async () => renderer.update(React.createElement(UsageDailyChart, { daily: daily(28), duration: false, language: "zh-CN", label: "每日 Token" })));
  assert.equal(bars().length, 28);
  assert.equal(renderer.root.findAllByProps({ role: "img" }).length, 28);
});
