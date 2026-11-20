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
const {
  createEditorTabsClientToolRegistration,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/editorTabsClientTool.ts",
);

after(async () => {
  await vite.close();
});

test("打开 Office 文件后直接读取已提交快照，不依赖 React 重新渲染", async () => {
  const harness = createTabsHarness();
  const registration = createRegistration(harness.capability);

  const first = await registration.execute(request({
    action: "open_file",
    path: "reports/result.docx",
  }));
  const repeated = await registration.execute(request({
    action: "open_file",
    path: "reports/result.docx",
  }));

  assert.equal(first.ok, true, first.error);
  assert.equal(first.content.opened_tab.path, "reports/result.docx");
  assert.equal(first.content.opened_tab.is_active, true);
  assert.equal(repeated.ok, true, repeated.error);
  assert.equal(repeated.content.opened_tab.is_active, true);
  assert.equal(harness.snapshot().tabs.length, 1);
});

test("聚焦文件根据标签页内部最新状态返回成功", async () => {
  const harness = createTabsHarness([
    tab("docs/a.md"),
    tab("docs/b.md"),
  ], "tab:docs/a.md");
  const registration = createRegistration(harness.capability);

  const result = await registration.execute(request({
    action: "focus_file",
    path: "docs/b.md",
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.focused_tab.path, "docs/b.md");
  assert.equal(result.content.focused_tab.is_active, true);
  assert.equal(harness.snapshot().activeTabId, "tab:docs/b.md");
});

test("关闭标签后根据标签页内部最新状态返回成功", async () => {
  const harness = createTabsHarness([
    tab("docs/a.md"),
    tab("docs/b.md"),
    tab("docs/c.md"),
  ], "tab:docs/a.md");
  const registration = createRegistration(harness.capability);

  const result = await registration.execute(request({
    action: "close_clean_tabs",
    paths: ["docs/a.md", "docs/b.md"],
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.closed_count, 2);
  assert.deepEqual(
    harness.snapshot().tabs.map((item) => item.projectFilePath),
    ["docs/c.md"],
  );
  assert.equal(harness.snapshot().activeTabId, "tab:docs/c.md");
});

test("关闭其它标签只保留 path 指定的标签", async () => {
  const harness = createTabsHarness([
    tab("docs/a.md"),
    tab("docs/b.md"),
    tab("docs/c.md"),
  ], "tab:docs/c.md");
  const registration = createRegistration(harness.capability);

  const result = await registration.execute(request({
    action: "close_others_clean",
    path: "docs/a.md",
  }));

  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.kept_tab.path, "docs/a.md");
  assert.equal(result.content.kept_tab.is_active, true);
  assert.equal(result.content.closed_count, 2);
  assert.deepEqual(
    harness.snapshot().tabs.map((item) => item.projectFilePath),
    ["docs/a.md"],
  );
});

test("网页与文件按打开顺序列出，同一网址复用标签，按持久 ID 切换", async () => {
  const harness = createTabsHarness([tab("report.md")], "tab:report.md");
  const registration = createRegistration(harness.capability);
  const run = args => registration.execute(request(args));
  const url = "https://example.test/report?year=2026#summary";
  const first = await run({ action: "open_url", url });
  assert.equal(first.ok, true, first.error);
  const web = first.content.opened_tab;
  assert.equal(web.kind, "web");
  assert.equal(web.path, null);
  assert.equal(web.url, url);
  assert.equal(web.is_active, true);
  await run({ action: "open_url", url: "https://other.example.test/" });
  assert.equal((await run({ action: "focus_web", tab_id: web.id })).content.focused_tab.id, web.id);
  assert.equal((await run({ action: "open_url", url })).content.opened_tab.id, web.id);
  const list = await run({ action: "list_tabs" });
  assert.deepEqual(list.content.tabs.map(item => item.kind), ["text", "web", "web"]);
  assert.equal(list.content.active_tab_id, web.id);
  assert.equal((await run({ action: "focus_web", tab_id: "missing" })).ok, false);
  assert.equal((await run({ action: "focus_file", path: url })).ok, false);
  for (const invalid of ["file:///a", "javascript:void(0)", "https://me:pass@example.test", ""]) {
    assert.equal((await run({ action: "open_url", url: invalid })).content.error_code, "INVALID_URL");
  }
  harness.capability.canOpenWebTab = () => false;
  assert.equal((await run({ action: "open_url", url })).content.error_code, "WEB_VIEW_UNAVAILABLE");
});

test("后台列表和选中结果使用持久网页 ID，并兼容只有文件列表的旧工作区", async (t) => {
  const id = crypto.randomUUID();
  const web = { kind: "web", id, title: "报告", url: "https://example.test/report", active: true };
  const state = {
    project_id: "project-b", open_file_paths: ["report.md"], active_file_path: null,
    open_tabs: [web, { kind: "file", path: "report.md" }], closed_file_paths: [], missing_file_paths: [],
  };
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.match(String(url), /project-b\/workspace-state\/editor-tabs$/);
    const payload = JSON.parse(init.body);
    if (payload.action === "focus_web") assert.equal(payload.tab_id, id);
    return Response.json({ ...state, action: payload.action });
  });
  const registration = createRegistration(createTabsHarness().capability);
  const run = args => registration.execute({ ...request(args), project_id: "project-b" });
  const list = await run({ action: "list_tabs" });
  assert.equal(list.ok, true, list.error);
  assert.deepEqual(list.content.tabs.map(tab => tab.kind), ["web", "text"]);
  assert.equal(list.content.active_tab_id, id);
  const focus = await run({ action: "focus_web", tab_id: id });
  assert.equal(focus.content.execution_scope, "background_workspace");
  assert.deepEqual(focus.content.focused_tab, list.content.tabs[0]);
  delete state.open_tabs;
  state.active_file_path = "report.md";
  const legacy = await run({ action: "list_tabs" });
  assert.equal(legacy.content.tabs[0].path, "report.md");
  assert.equal(legacy.content.active_tab_id, legacy.content.tabs[0].id);
});

function createRegistration(capability) {
  return createEditorTabsClientToolRegistration({
    getEditorTabs: () => capability,
    getProjectId: () => "project-a",
  });
}

function createTabsHarness(initialTabs = [], initialActiveTabId = null) {
  let state = {
    activeTabId: initialActiveTabId,
    tabs: initialTabs,
  };
  const capability = {
    closeTab: (tabId) => {
      const index = state.tabs.findIndex((item) => item.id === tabId);
      if (index < 0) return;
      const tabs = state.tabs.filter((item) => item.id !== tabId);
      state = {
        activeTabId: state.activeTabId === tabId
          ? tabs[Math.min(index, tabs.length - 1)]?.id ?? null
          : state.activeTabId,
        tabs,
      };
    },
    getSnapshot: () => state,
    canOpenWebTab: () => true,
    openWebTab: (url, projectId) => {
      const id = `web:projects:${projectId}:${crypto.randomUUID()}`;
      const web = { ...tab("", projectId), id, title: new URL(url).hostname, displayPath: url, kind: "web", projectFilePath: null };
      state = { activeTabId: id, tabs: [...state.tabs, web] };
      return id;
    },
    openProjectFile: async (projectId, path) => {
      const existing = state.tabs.find((item) => item.projectFilePath === path);
      const opened = existing ?? tab(path, projectId);
      state = {
        activeTabId: opened.id,
        tabs: existing ? state.tabs : [...state.tabs, opened],
      };
    },
    selectTab: (tabId) => {
      if (state.tabs.some((item) => item.id === tabId)) {
        state = { ...state, activeTabId: tabId };
      }
    },
  };
  return {
    capability,
    snapshot: () => state,
  };
}

function tab(path, projectId = "project-a") {
  return {
    id: `tab:${path}`,
    title: path.split("/").at(-1),
    projectFilePath: path,
    projectId,
    kind: path.endsWith(".docx") ? "word" : "text",
    isDirty: false,
    isMissing: false,
    saveState: "idle",
  };
}

function request(argumentsValue) {
  return {
    request_id: "request-tabs",
    call_id: "call-tabs",
    name: "editor_tabs_manager",
    arguments: JSON.stringify(argumentsValue),
    project_id: "project-a",
    session_id: "session-a",
    client_capability: { name: "editor.tabs", min_version: 1 },
  };
}
