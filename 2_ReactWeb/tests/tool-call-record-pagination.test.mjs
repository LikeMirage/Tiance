import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const file = new URL("../src/features/tool-call-records-dashboard/ui/ToolCallRecordsDashboard.tsx", import.meta.url);

function loadDashboard(api) {
  const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    fileName: file.pathname,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`)((name) => {
    if (name.endsWith(".css")) return {};
    if (name.endsWith("/toolCallRecords")) return api;
    if (name === "@phosphor-icons/react") return { ArrowClockwise: () => null, CaretDown: () => null, CaretRight: () => null };
    return require(name);
  }, module, module.exports);
  return module.exports.ToolCallRecordsDashboard;
}

function summary(id) {
  return { record_id: id, tool_project_id: "tool-a", tool_name: "read_file", call_id: id,
    source_project_id: "p", source_project_name: "项目", session_id: "s", session_title: "会话",
    ok: true, created_at: "2026-10-29T08:00:00Z", elapsed_ms: 10, dynamic: true };
}
function page(ids = ["record-a", "record-b"], extra = {}) {
  return { category_id: "tools", project_id: "tool-a", count: 102, offset: 0, limit: 50,
    snapshot: "snapshot:123", items: ids.map(summary), ...extra };
}
function detail(id, text = "完整返回内容") {
  return { ...summary(id), arguments_text: '{"path":"example.txt"}', result_text: text, error: null };
}

async function harness(t) {
  const lists = [], details = [];
  const enqueue = (requests, fields) => new Promise((resolve, reject) => requests.push({ ...fields, resolve, reject }));
  const Dashboard = loadDashboard({
    getToolFolderCallRecords: (toolsetId, folderId, options) => enqueue(lists, { toolsetId, folderId, ...options }),
    getToolFolderCallRecord: (toolsetId, folderId, recordId, options) => enqueue(details, { toolsetId, folderId, recordId, ...options }),
  });
  let renderer;
  await act(async () => { renderer = create(React.createElement(Dashboard, { toolsetId: "tools", folderId: "tool-a" })); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  const buttons = () => renderer.root.findAllByType("button");
  return { renderer, lists, details,
    rows: () => buttons().filter(button => "aria-expanded" in button.props),
    button: text => buttons().find(button => button.children.includes(text) || button.props["aria-label"] === text),
    text: () => JSON.stringify(renderer.toJSON()),
    select: async folderId => act(async () => renderer.update(React.createElement(Dashboard, { toolsetId: "tools", folderId }))),
  };
}

test("initial page requests summaries only; detail loads on expansion and is released on collapse", async t => {
  const h = await harness(t);
  assert.equal(h.lists.length, 1);
  assert.equal(h.lists[0].offset, 0);
  assert.equal(h.details.length, 0);
  await act(async () => h.lists[0].resolve(page()));
  assert.equal(h.rows().length, 2);
  assert.equal(h.details.length, 0);
  await act(async () => h.rows()[0].props.onClick());
  assert.equal(h.details[0].recordId, "record-a");
  assert.match(h.text(), /正在读取调用详情/);
  await act(async () => h.details[0].resolve(detail("record-a")));
  assert.match(h.text(), /完整返回内容/);
  await act(async () => h.rows()[0].props.onClick());
  assert.equal(h.details[0].signal.aborted, true);
  assert.doesNotMatch(h.text(), /完整返回内容/);
  await act(async () => h.rows()[0].props.onClick());
  assert.equal(h.details.length, 2); // No accumulating full-result cache.
});

test("next/previous pages share snapshot, replace rows, and refresh starts a new snapshot", async t => {
  const h = await harness(t);
  await act(async () => h.lists[0].resolve(page()));
  assert.equal(h.button("上一页").props.disabled, true);
  await act(async () => h.rows()[0].props.onClick());
  await act(async () => h.button("下一页").props.onClick());
  assert.equal(h.details[0].signal.aborted, true);
  assert.equal(h.lists[1].offset, 50);
  assert.equal(h.lists[1].snapshot, "snapshot:123");
  assert.equal(h.button("下一页").props.disabled, true);
  await act(async () => h.lists[1].resolve(page(["record-c"], { offset: 50 })));
  assert.equal(h.rows().length, 1);
  await act(async () => h.button("上一页").props.onClick());
  assert.equal(h.lists[2].offset, 0);
  assert.equal(h.lists[2].snapshot, "snapshot:123");
  await act(async () => h.lists[2].resolve(page()));
  await act(async () => h.button("刷新调用记录").props.onClick());
  assert.equal(h.lists[3].offset, 0);
  assert.equal(h.lists[3].snapshot, undefined);
});

test("switching tools cancels old list and detail, and delayed old responses cannot replace new tool", async t => {
  const h = await harness(t);
  await act(async () => h.lists[0].resolve(page()));
  await act(async () => h.rows()[0].props.onClick());
  await act(async () => h.button("下一页").props.onClick());
  await h.select("tool-b");
  assert.equal(h.lists[1].signal.aborted, true);
  assert.equal(h.details[0].signal.aborted, true);
  assert.equal(h.rows().length, 0);
  assert.equal(h.lists[2].folderId, "tool-b");
  await act(async () => h.lists[2].resolve(page(["record-b-only"], { count: 1 })));
  await act(async () => { h.lists[1].resolve(page()); h.details[0].resolve(detail("record-a", "过期内容")); });
  assert.equal(h.rows().length, 1);
  assert.doesNotMatch(h.text(), /过期内容/);
  await act(async () => h.rows()[0].props.onClick());
  assert.equal(h.details[1].folderId, "tool-b");
  assert.equal(h.details[1].recordId, "record-b-only");
});

test("switching expanded rows ignores prior detail and failed detail supports retry", async t => {
  const h = await harness(t);
  await act(async () => h.lists[0].resolve(page()));
  await act(async () => h.rows()[0].props.onClick());
  await act(async () => h.rows()[1].props.onClick());
  assert.equal(h.details[0].signal.aborted, true);
  await act(async () => h.details[0].resolve(detail("record-a", "过期内容")));
  assert.doesNotMatch(h.text(), /过期内容/);
  await act(async () => h.details[1].reject(new Error("暂时读取失败")));
  assert.match(h.text(), /暂时读取失败/);
  await act(async () => h.button("重试").props.onClick());
  await act(async () => h.details[2].resolve(detail("record-b", "重试成功")));
  assert.match(h.text(), /重试成功/);
  assert.doesNotMatch(h.text(), /暂时读取失败/);
});

test("failed page preserves current rows, shows error, and can refresh", async t => {
  const h = await harness(t);
  await act(async () => h.lists[0].resolve(page()));
  await act(async () => h.button("下一页").props.onClick());
  await act(async () => h.lists[1].reject(new Error("调用记录已变化，请刷新列表。")));
  assert.equal(h.rows().length, 2);
  assert.match(h.text(), /请刷新列表/);
  assert.equal(h.button("刷新调用记录").props.disabled, false);
  await act(async () => h.button("刷新调用记录").props.onClick());
  await act(async () => h.lists[2].resolve(page([], { count: 0 })));
  assert.equal(h.rows().length, 0);
  assert.match(h.text(), /暂无调用记录/);
  assert.equal(h.button("下一页").props.disabled, true);
});
