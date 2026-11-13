import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true },
  plugins: [{ name: "project-drag-test", enforce: "pre", transform(code, id) {
    const path = id.replaceAll("\\", "/");
    if (path.endsWith("/src/shared/i18n/index.ts")) {
      return 'export const useI18n = () => ({ language: "zh-CN", t: (key) => key });';
    }
    if (path.endsWith("/EmbeddedPanel.tsx")) {
      return code.replace('import { createPortal } from "react-dom";',
        "const createPortal = (children: any, _target: any) => children;");
    }
  } }],
});
const { ProjectListPanel } = await vite.ssrLoadModule("/src/features/project-catalog/ui/ProjectListPanel.tsx");
const { ChatComposerAddMenu } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatComposerAddMenu.tsx");
const { useWorkspaceEditorReferences } = await vite.ssrLoadModule("/src/pages/workspace/model/useWorkspaceEditorReferences.ts");
const drop = await vite.ssrLoadModule("/src/features/ai-panel/ui/chatComposerDrop.ts");
const drag = await vite.ssrLoadModule("/src/entities/project/model/projectDragData.ts");
const projects = ["a", "b", "c"].map(id => ({ project_id: id, name: `项目 ${id}`,
  root_path: `C:\\工作区\\${id}`, category_id: "category", project_kind: "project",
  created_at: "2026-11-10T08:00:00Z", updated_at: "2026-11-10T08:00:00Z", sort_order: 0 }));
const categories = [{ category_id: "category", name: "日常项目", category_kind: "project" }];
const previous = {};
before(() => {
  for (const key of ["window", "document", "IS_REACT_ACT_ENVIRONMENT"]) previous[key] = Object.getOwnPropertyDescriptor(globalThis, key);
  const window = Object.assign(new EventTarget(), { innerWidth: 1200, innerHeight: 900, setTimeout, clearTimeout });
  const document = Object.assign(new EventTarget(), { body: {} });
  Object.assign(globalThis, { window, document, IS_REACT_ACT_ENVIRONMENT: true });
});
after(async () => {
  for (const [key, descriptor] of Object.entries(previous)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
  }
  await vite.close();
});
const createNodeMock = () => ({ style: {}, focus() {}, contains() { return false; },
  getBoundingClientRect: () => ({ left: 20, top: 300, height: 20, width: 200 }),
  addEventListener() {}, removeEventListener() {} });

function transfer() {
  const values = new Map();
  return { effectAllowed: "uninitialized", dropEffect: "none", get types() { return [...values.keys()]; },
    setData: (type, value) => values.set(type, value), getData: type => values.get(type) ?? "" };
}
function event(dataTransfer) {
  return { dataTransfer, clientY: 400, preventDefault() {}, stopPropagation() {} };
}
const projectArticle = (view, id) => view.root.findAllByType("article").find(node =>
  node.findByProps({ className: "catalog-list-entry__name" }).children.join("") === `项目 ${id}`);

async function listHarness(failSave = false) {
  const saves = [], selections = [], previews = [];
  let view, current;
  function Harness() {
    const [items, setItems] = React.useState(projects);
    current = items.map(item => item.project_id);
    const reorder = ids => setItems(old => ids.map(id => old.find(item => item.project_id === id)));
    const catalog = {
      categories, items, selectedCategoryProjects: items, selectedCategoryId: "category",
      selectedProjectId: "b", state: "ready", error: null,
      selectProject: id => selections.push(id), expandProject: id => selections.push(id),
      previewProjectOrder: ids => { previews.push(ids.slice()); reorder(ids); },
      persistProjectOrder: async ids => { saves.push(ids); if (failSave) throw new Error("保存失败"); reorder(ids); },
      getReorderedProjectIds: (source, target, position) => {
        const ids = items.map(item => item.project_id).filter(id => id !== source);
        ids.splice(ids.indexOf(target) + (position === "after" ? 1 : 0), 0, source); return ids;
      },
    };
    return React.createElement(ProjectListPanel, { projectCatalog: catalog, searchKeyword: "" });
  }
  await act(async () => { view = create(React.createElement(Harness), { createNodeMock }); });
  return { view, saves, selections, previews, order: () => current,
    close: () => act(async () => { view.unmount(); }) };
}

test("经过其他项目再拖进会话，只添加引用，顺序恢复且不切换项目", async () => {
  const list = await listHarness();
  try {
    const data = transfer();
    await act(async () => { projectArticle(list.view, "a").props.onDragStart(event(data)); });
    assert.equal(data.effectAllowed, "copyMove");
    assert.equal(data.getData("text/plain"), "");
    await act(async () => { projectArticle(list.view, "b").props.onDragOver(event(data)); });
    assert.deepEqual(list.order(), ["b", "a", "c"]);
    const references = [];
    const input = { projectId: "b", onReferenceExternalPath: value => references.push(value),
      onDropProjectFile: () => assert.fail("跨项目引用不能误走当前项目文件入口") };
    assert.equal(drop.hasChatComposerReferenceDrag(event(data), input), true);
    assert.equal(drop.handleChatComposerReferenceDrop(event(data), input), true);
    data.dropEffect = "copy";
    await act(async () => { projectArticle(list.view, "a").props.onDragEnd(event(data)); });
    assert.deepEqual(references, [{ kind: "folder", name: "项目 a（Tiance 项目）", path: "C:/工作区/a" }]);
    assert.deepEqual(list.order(), ["a", "b", "c"]);
    assert.deepEqual(list.saves, []);
    assert.deepEqual(list.selections, []);
  } finally { await list.close(); }
});

test("只有在原列表内落下才保存，随后取消拖拽也不会沿用上次落点", async () => {
  const list = await listHarness();
  try {
    const data = transfer();
    await act(async () => { projectArticle(list.view, "a").props.onDragStart(event(data)); });
    await act(async () => { projectArticle(list.view, "b").props.onDragOver(event(data)); });
    await act(async () => { list.view.root.findByType("nav").props.onDrop(event(data)); });
    await act(async () => { projectArticle(list.view, "a").props.onDragEnd(event(data)); });
    assert.deepEqual(list.saves, [["b", "a", "c"]]);
    assert.deepEqual(list.order(), ["b", "a", "c"]);
    await act(async () => { projectArticle(list.view, "b").props.onDragStart(event(data)); });
    await act(async () => { projectArticle(list.view, "c").props.onDragOver(event(data)); });
    // Even if the last drag-over advertised "move", Escape has no list drop.
    data.dropEffect = "move";
    await act(async () => { projectArticle(list.view, "b").props.onDragEnd(event(data)); });
    assert.deepEqual(list.order(), ["b", "a", "c"]);
    assert.equal(list.saves.length, 1);
  } finally { await list.close(); }
});

test("列表排序保存失败恢复原顺序并显示错误", async () => {
  const list = await listHarness(true);
  try {
    const data = transfer();
    await act(async () => { projectArticle(list.view, "a").props.onDragStart(event(data)); });
    await act(async () => { projectArticle(list.view, "b").props.onDragOver(event(data)); });
    await act(async () => { list.view.root.findByType("nav").props.onDrop(event(data)); });
    await act(async () => { projectArticle(list.view, "a").props.onDragEnd(event(data)); });
    assert.deepEqual(list.order(), ["a", "b", "c"]);
    assert.equal(list.view.root.findByProps({ role: "alert" }).children.join(""), "保存失败");
  } finally { await list.close(); }
});

test("加号与拖入得到相同引用，并由已有引用状态统一去重", async () => {
  let view, editor;
  const calls = [];
  function Harness() {
    editor = useWorkspaceEditorReferences({ projectId: "b", sessionId: "session", documentTabs: {} });
    return React.createElement(ChatComposerAddMenu, { isOpen: true, panelContainer: document.body, onOpenChange() {}, onSelectFiles: async () => {},
      projectId: "b", projectCatalog: { categories, projects, isLoading: false, error: null },
      onReferenceExternalPath: value => { calls.push(value); editor.handleReferenceExternalPath(value); } });
  }
  try {
    await act(async () => { view = create(React.createElement(Harness), { createNodeMock }); });
    await act(async () => { view.root.findAllByProps({ role: "tab" })[2].props.onClick(); });
    await act(async () => { view.root.findByProps({ title: projects[0].root_path }).props.onClick(); });
    const data = transfer(); data.setData(drag.PROJECT_DRAG_MIME_TYPE, drag.serializeProjectDragData(projects[0]));
    await act(async () => { assert.equal(drop.handleChatComposerReferenceDrop(event(data), {
      onReferenceExternalPath: value => { calls.push(value); editor.handleReferenceExternalPath(value); },
    }), true); });
    assert.deepEqual(calls[0], calls[1]);
    assert.equal(editor.references.length, 1);
    assert.equal(editor.references[0].reference.source, "external_path");
    assert.equal(editor.references[0].reference.fileName, "项目 a（Tiance 项目）");
  } finally { if (view) await act(async () => { view.unmount(); }); }
});

test("拒绝普通文本、非法拖拽数据和相对路径，无可用会话入口时不接受项目拖入", () => {
  const data = transfer(), calls = [];
  const input = { onReferenceExternalPath: value => calls.push(value) };
  data.setData("text/plain", "a");
  assert.equal(drop.hasChatComposerReferenceDrag(event(data), input), false);
  assert.equal(drop.handleChatComposerReferenceDrop(event(data), input), false);
  for (const value of ["bad json", "[]", "{}", JSON.stringify({ ...projects[0], root_path: "relative/path" })]) {
    data.setData(drag.PROJECT_DRAG_MIME_TYPE, value);
    assert.equal(drop.handleChatComposerReferenceDrop(event(data), input), false);
  }
  data.setData(drag.PROJECT_DRAG_MIME_TYPE, drag.serializeProjectDragData(projects[0]));
  assert.equal(drop.hasChatComposerReferenceDrag(event(data), {}), false);
  assert.equal(drop.handleChatComposerReferenceDrop(event(data), {}), false);
  assert.deepEqual(calls, []);
});
