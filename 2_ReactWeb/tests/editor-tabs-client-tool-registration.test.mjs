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
