import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true },
  plugins: [{ name: "file-reference-test", enforce: "pre", transform(code, id) {
    if (id.endsWith("/httpClient.ts")) return `
      export class HttpRequestError extends Error { constructor(message, status) { super(message); this.status = status; } }
      export const fetchJson = (...args) => globalThis.fileReferenceFetch(...args);
      export const fetchNoContent = fetchJson;
      export const parseHttpErrorPayload = value => value;`;
    if (id.endsWith("/watchProjectFileEvents.ts")) return "export const watchProjectFileEvents = () => () => {};";
  } }],
});
const { useDocumentTabs } = await vite.ssrLoadModule("/src/features/document-tabs/model/useDocumentTabs.ts");
const { useWorkspaceDocumentActions } = await vite.ssrLoadModule("/src/pages/workspace/model/useWorkspaceDocumentActions.ts");
const { useToolWorkspacePersistence } = await vite.ssrLoadModule("/src/pages/workspace/model/useToolWorkspacePersistence.ts");
const { createToolFolderDocumentSource } = await vite.ssrLoadModule("/src/features/document-tabs/model/documentFileSources.ts");
const { createLocalDocumentSource } = await vite.ssrLoadModule("/src/features/document-tabs/model/localDocumentFileSource.ts");
const { resolveDocumentPreview } = await vite.ssrLoadModule("/src/features/document-tabs/model/documentPreviewResolver.ts");
const { buildWorkspaceFileTab } = await vite.ssrLoadModule("/src/features/document-tabs/model/documentFileTabs.ts");
const { createMarkdownAssetUrlResolver } = await vite.ssrLoadModule("/src/features/document-editor-canvas/model/markdownPreviewAssets.ts");
const { resolveDocumentAssetUrl } = await vite.ssrLoadModule("/src/features/document-editor-canvas/model/documentAssetUrls.ts");
const { getEditorDocumentPath } = await vite.ssrLoadModule("/src/entities/editor/model/editorWorkspaceFileReference.ts");
const { HttpRequestError } = await vite.ssrLoadModule("/src/services/http/httpClient.ts");
const database = await vite.ssrLoadModule("/src/services/project/projectDatabase.ts");

const previous = new Map(["window", "IS_REACT_ACT_ENVIRONMENT", "fileReferenceFetch"].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
globalThis.window = new EventTarget();
globalThis.window.setTimeout = setTimeout;
globalThis.window.clearTimeout = clearTimeout;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
after(async () => {
  await vite.close();
  for (const [key, value] of previous) {
    if (value) Object.defineProperty(globalThis, key, value); else delete globalThis[key];
  }
});

const ref = (path, extra = {}) => ({ kind: "file", reference: { id: path, kind: "file", source: "external_path",
  projectId: null, filePath: path, displayPath: path, fileName: path.split("/").at(-1), ...extra } });
const node = path => ({ kind: "file", id: path, path, name: path.split("/").at(-1), mtimeMs: 1 });
const flush = () => new Promise(resolve => setImmediate(resolve));
async function mount(options = {}) {
  let state, root;
  function Harness({ projectId = "p", sessionId = "s" }) {
    const tabs = useDocumentTabs();
    const actions = useWorkspaceDocumentActions({ documentTabs: tabs, projectId, sessionId, onLayoutPreferenceChange() {}, ...options });
    state = { tabs, actions };
    return null;
  }
  await act(async () => { root = create(React.createElement(Harness)); });
  return { get state() { return state; },
    click: payload => act(async () => { state.actions.handleOpenReference(payload); await flush(); }),
    change: props => act(async () => root.update(React.createElement(Harness, props))),
    close: () => act(async () => root.unmount()),
  };
}

test("所有外部格式复用正常预览分类、资源入口，标签不伪装成项目文件", () => {
  const source = createLocalDocumentSource("C:/", "p").source;
  for (const [name, kind] of [["a.md", "text"], ["a.py", "text"], ["a.png", "image"], ["a.pdf", "pdf"],
      ["a.docx", "office"], ["a.xlsx", "office"], ["a.pptx", "office"], ["a.csv", "office"],
      ["a.db", "database"], ["a.unknown", "unsupported"]]) {
    const file = node(`外部/${name}`);
    const tab = buildWorkspaceFileTab(file, source, file.path, resolveDocumentPreview(file));
    assert.equal(tab.kind, kind);
    assert.equal(tab.projectId, "p", "仅用于当前画布显示");
    assert.equal(tab.projectFilePath, null, "现有文件树逻辑自然跳过");
    assert.equal(getEditorDocumentPath(tab), `C:/外部/${name}`);
    assert.equal(new URL(resolveDocumentAssetUrl(tab)).searchParams.get("path"), `C:/外部/${name}`);
  }
});

test("当前项目整文件引用打开普通标签，重复打开保留未保存内容", async () => {
  globalThis.fileReferenceFetch = async path => path.endsWith("/resolve")
    ? { kind: "project", root: "C:/project", path: "doc.md", name: "doc.md", mtime_ms: 1 }
    : { path: "doc.md", content: "original", mtime_ms: 1 };
  const view = await mount();
  try {
    await view.click(ref("doc.md", { source: "project_file", projectId: "p" }));
    const id = view.state.tabs.activeTab.id;
    assert.equal(view.state.tabs.activeTab.projectFilePath, "doc.md");
    await act(async () => view.state.tabs.updateTabContent(id, "unsaved"));
    await view.click(ref("C:/project/doc.md"));
    assert.equal(view.state.tabs.tabs.length, 1);
    assert.equal(view.state.tabs.activeTab.content, "unsaved");
    assert.equal(view.state.tabs.activeTab.isDirty, true);
  } finally { await view.close(); }
});

test("进入工作区后再打开引用，工具文件复用已有标签；切换会话取消等待中的打开", async () => {
  let finish, preparedSignal;
  globalThis.fileReferenceFetch = async path => path.endsWith("/resolve")
    ? { kind: "project", path: "doc.md", name: "doc.md", mtime_ms: 1 }
    : { path: "doc.md", content: "original", mtime_ms: 1 };
  const source = createToolFolderDocumentSource("tools", "p", "tool", "p");
  const view = await mount({ projectFileSource: source,
    onPrepareFileOpen: signal => { preparedSignal = signal; return new Promise(resolve => { finish = resolve; }); } });
  try {
    await view.click(ref("doc.md", { source: "project_file", projectId: "p" }));
    assert.equal(view.state.tabs.tabs.length, 0);
    // Simulate restoration finishing with this file already open and edited.
    await act(async () => view.state.tabs.openNode(node("doc.md"), { fileSource: source }));
    await act(async () => view.state.tabs.updateTabContent(view.state.tabs.activeTab.id, "unsaved"));
    await act(async () => { finish(true); await flush(); });
    assert.equal(view.state.tabs.tabs.length, 1);
    assert.equal(view.state.tabs.activeTab.content, "unsaved");
    assert.equal(view.state.tabs.activeTab.fileSource.key, source.source.key);
    await view.click(ref("doc.md", { source: "project_file", projectId: "p" }));
    await view.change({ sessionId: "other" });
    assert.equal(preparedSignal.aborted, true);
    await act(async () => { finish(true); await flush(); });
    assert.equal(view.state.tabs.activeTab.content, "unsaved");
  } finally { await view.close(); }
});

test("工具工作区等待完整标签恢复，切换或取消会释放等待", async () => {
  let state, root, restore, restored = false;
  const browser = { restoreExpandedPaths() {}, userExpandedNodeIds: new Set() };
  const tabs = { tabs: [], activeTab: null, closeAllTabs() {}, ensureProjectConversationOverview() {},
    restoreWorkspaceTabs: () => new Promise(resolve => { restore = () => { restored = true; resolve(); }; }),
    async openToolDashboard() { assert.equal(restored, true); } };
  globalThis.fileReferenceFetch = async () => ({ project_id: "p", open_file_paths: [], expanded_paths: [], active_file_path: null });
  function Harness({ open = false }) {
    state = useToolWorkspacePersistence({ activeToolFolder: open ? { project_id: "p", name: "tool" } : null,
      activeToolsetId: "tools", browser, documentTabs: tabs });
    return null;
  }
  const key = createToolFolderDocumentSource("tools", "p", "tool", "p").source.key;
  await act(async () => { root = create(React.createElement(Harness)); });
  try {
    let settled = false;
    const waiting = state.waitForWorkspaceReady(key, new AbortController().signal).then(ready => { settled = true; return ready; });
    await act(async () => { root.update(React.createElement(Harness, { open: true })); await flush(); });
    assert.equal(settled, false);
    await act(async () => { restore(); await flush(); });
    assert.equal(await waiting, true);
    assert.equal(await state.waitForWorkspaceReady(key, new AbortController().signal), true);
    await act(async () => root.update(React.createElement(Harness)));
    const controller = new AbortController();
    const cancelled = state.waitForWorkspaceReady(key, controller.signal);
    controller.abort();
    assert.equal(await cancelled, false);
    restored = false;
    const switched = state.waitForWorkspaceReady(key, new AbortController().signal);
    await act(async () => { root.update(React.createElement(Harness, { open: true })); await flush(); });
    await act(async () => root.update(React.createElement(Harness)));
    assert.equal(await switched, false);
    await act(async () => { restore(); await flush(); });
    assert.equal(restored, true);
    const afterSwitch = new AbortController();
    let oldRestoreReady = false;
    const stale = state.waitForWorkspaceReady(key, afterSwitch.signal).then(ready => { oldRestoreReady = ready; });
    afterSwitch.abort();
    await stale;
    assert.equal(oldRestoreReady, false);
  } finally { await act(async () => root.unmount()); }
});

test("外部文本读写真实路径，重复点击不清除草稿，磁盘变化保留冲突处理", async () => {
  let disk = "original", stamp = 1;
  const calls = [];
  globalThis.fileReferenceFetch = async (path, init = {}) => {
    calls.push([path, init]);
    if (path.endsWith("/resolve")) return { kind: "local", root: "C:/", path: "外部/a.md", name: "a.md", mtime_ms: stamp };
    if (init.method === "PUT") {
      const payload = JSON.parse(init.body);
      assert.equal(payload.expected_mtime_ms, stamp);
      disk = payload.content; stamp++;
      return { ...node("a.md"), mtime_ms: stamp };
    }
    return { path: "C:/外部/a.md", content: disk, mtime_ms: stamp };
  };
  const view = await mount();
  try {
    await view.click(ref("C:/外部/a.md"));
    const id = view.state.tabs.activeTab.id;
    await act(async () => view.state.tabs.updateTabContent(id, "mine"));
    await view.click(ref("C:/外部/a.md"));
    assert.equal(view.state.tabs.tabs.length, 1);
    assert.equal(view.state.tabs.activeTab.content, "mine");
    await act(async () => { assert.equal(await view.state.tabs.saveTab(id), true); });
    assert.equal(disk, "mine");
    assert.equal(view.state.tabs.activeTab.displayPath, "C:/外部/a.md");
    await act(async () => view.state.tabs.updateTabContent(id, "pending"));
    disk = "other editor"; stamp++;
    await view.click(ref("C:/外部/a.md"));
    assert.equal(view.state.tabs.activeTab.content, "pending");
    assert.equal(view.state.tabs.activeTab.externalChange.kind, "conflict");
    for (const [url] of calls.filter(([url]) => !url.endsWith("/resolve"))) {
      assert.equal(new URL(url, "http://localhost").searchParams.get("path"), "C:/外部/a.md");
    }
  } finally { await view.close(); }
});

test("附件传递所在会话；解析失败明确显示，切换项目后旧响应不能打开标签", async () => {
  let submitted, finish;
  globalThis.fileReferenceFetch = async (path, init) => {
    submitted = JSON.parse(init.body);
    throw new HttpRequestError("找不到附件。", 404);
  };
  const view = await mount();
  try {
    await view.click(ref("tiance-attachment://att_123", { projectId: "p", source: "project_file" }));
    assert.equal(submitted.session_id, "s");
    assert.equal(view.state.actions.referenceOpenError, null);
    assert.equal(view.state.tabs.activeTab.referenceResolution.kind, "missing");
    const before = view.state.tabs.tabs.length;
    globalThis.fileReferenceFetch = () => new Promise(resolve => { finish = resolve; });
    await view.click(ref("C:/slow.pdf"));
    await view.change({ projectId: "q", sessionId: "s2" });
    await act(async () => { finish({ kind: "local", root: "C:/", path: "slow.pdf", name: "slow.pdf", mtime_ms: 1 }); await flush(); });
    assert.equal(view.state.tabs.tabs.length, before);
    assert.equal(view.state.actions.referenceOpenError, null);
  } finally { await view.close(); }
});

test("文件夹解析原路径并显示共用打开页面", async () => {
  globalThis.fileReferenceFetch = async () => ({ kind: "folder", path: "C:/folder", name: "folder", project: null });
  const view = await mount();
  try {
    await view.click(ref("C:/folder", { kind: "folder" }));
    assert.match(view.state.tabs.activeTab.id, /reference/);
    assert.equal(view.state.actions.referenceOpenError, null);
  } finally { await view.close(); }
});

test("外部 Markdown 图片以文件目录解析，包括中文、空格、上层目录与 UNC", () => {
  for (const root of ["C:/", "//server/share/", "/"]) {
    const source = createLocalDocumentSource(root, "p").source;
    const resolve = createMarkdownAssetUrlResolver({ fileSource: source, filePath: "docs/reports/a.md" });
    const url = resolve("../charts/%E5%9B%BE%20%231.png");
    assert.equal(new URL(url).searchParams.get("path"), `${root}docs/charts/图 #1.png`);
    assert.equal(resolve("https://example.com/a.png"), "https://example.com/a.png");
    assert.equal(resolve("data:image/png;base64,abc"), "data:image/png;base64,abc");
  }
});

test("数据库使用同一预览组件，外部查询不会误走项目根目录", async () => {
  const calls = [];
  globalThis.fileReferenceFetch = async (...args) => { calls.push(args); return {}; };
  await database.getProjectDatabaseOverview({ kind: "local" }, "D:/file.db");
  await database.queryProjectDatabase({ kind: "local" }, { path: "D:/file.db", sql: "select 1", limit: 100 });
  await database.getProjectDatabaseOverview({ kind: "project", projectId: "p" }, "file.db");
  assert.match(calls[0][0], /^\/api\/editor\/local\/databases\/overview/);
  assert.equal(JSON.parse(calls[1][1].body).path, "D:/file.db");
  assert.match(calls[2][0], /^\/api\/projects\/p\/databases\/overview/);
});


test("部分引用打开原文件而非截图，失配不清空文件、不显示错误页", async () => {
  let submitted;
  globalThis.fileReferenceFetch = async (path, init) => {
    if (path.endsWith("/resolve")) {
      submitted = JSON.parse(init.body);
      return { kind: "local", root: "C:/", path: "outside/notes.md", name: "notes.md", mtime_ms: 1 };
    }
    return { path: "outside/notes.md", content: "文件已经改过", mtime_ms: 1 };
  };
  const view = await mount();
  try {
    const payload = { kind: "text", reference: { ...ref("C:/outside/notes.md").reference,
      source: "source", content: "原来的段落", startLine: 1, endLine: 1 } };
    await view.click(payload);
    assert.equal(submitted.path, "C:/outside/notes.md");
    assert.equal(submitted.source, "external_path");
    assert.equal(view.state.tabs.activeTab.kind, "text");
    assert.equal(view.state.tabs.activeTab.revealRequest.target.type, "reference_text");
    await act(async () => { view.state.tabs.activeTab.revealRequest.complete({ type: "reference", selected: false }); await flush(); });
    assert.equal(view.state.tabs.activeTab.content, "文件已经改过");
    assert.equal(view.state.actions.referenceOpenError, null);
  } finally { await view.close(); }
});

test("整文件、部分文件、截图原文件及文件夹丢失使用统一页面；服务器故障不伪装成丢失", async () => {
  const view = await mount();
  const base = ref("lost.md").reference;
  try {
    const payloads = [ref("C:/lost.md"), ref("C:/lost", { kind: "folder" }),
      { kind: "text", reference: { ...base, source: "source", content: "old" } },
      { kind: "image", reference: { ...base, source: "pdf_page", sourceFilePath: "C:/lost.pdf", sourceFileName: "lost.pdf",
        sourceDisplayPath: "C:/lost.pdf", imagePath: "tiance-attachment://snapshot", pageNumber: 2 } }];
    globalThis.fileReferenceFetch = async () => { throw new HttpRequestError("missing", 404); };
    for (const payload of payloads) {
      await view.click(payload);
      assert.equal(view.state.tabs.activeTab.referenceResolution.kind, "missing");
      assert.equal(view.state.actions.referenceOpenError, null);
    }
    const count = view.state.tabs.tabs.length;
    for (const status of [403, 500]) {
      globalThis.fileReferenceFetch = async () => { throw new HttpRequestError("真实错误", status); };
      await view.click(ref("C:/different.md"));
      assert.equal(view.state.actions.referenceOpenError, "真实错误");
      assert.equal(view.state.tabs.tabs.length, count);
    }
  } finally { await view.close(); }
});
