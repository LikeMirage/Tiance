import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let renderer, catalog, services, projects, categories, saved, writes, refresh;

const project = (id, category) => ({ project_id: id, category_id: category,
  project_kind: "project", name: id, is_default: false });
const category = (id) => ({ category_id: id, category_kind: "project", name: id,
  is_default: id === "a" });
const selection = (categoryId, projectId, sessionId) => ({ category_id: categoryId,
  project_id: projectId, session_id: sessionId, updated_at: "saved" });
function workspace() {
  return { ...selection("a", "a2", "sa2"), category_selections: {
    a: selection("a", "a2", "sa2"), b: selection("b", "b2", "sb2"),
  } };
}

async function setup() {
  categories = [category("a"), category("b")];
  projects = [project("a1", "a"), project("a2", "a"), project("a3", "a"),
    project("b1", "b"), project("b2", "b")];
  saved = workspace(); writes = []; refresh = null;
  const modules = new Map();
  const mocks = {
    react: React,
    "../../../entities/project/model/projectCatalogEvents": {
      listenProjectCatalogChanged: () => () => {}, dispatchProjectCatalogChanged() {},
    },
    "../../../services/project/getProjects": {
      getProjects: () => refresh ? new Promise(resolve => { refresh.resolve = resolve; })
        : Promise.resolve({ items: structuredClone(projects) }),
    },
    "../../../services/project/getProjectCategories": {
      getProjectCategories: async () => ({ items: structuredClone(categories) }),
    },
    "../../../services/project/getProjectOrder": { getProjectOrder: async () => ({ project_ids: [] }) },
    "../../../services/project/saveProjectOrder": { saveProjectOrder: async () => {} },
    "../../../services/project/watchProjectWorkspaceEvents": { watchProjectWorkspaceEvents: () => () => {} },
    "../../../services/project/deleteProject": { deleteProject: async () => {} },
    "../../../services/project/createProjectCategory": {
      createProjectCategory: async () => category("c"),
    },
    "../../../services/project/createProject": { createProject: async input => project("new", input.category_id) },
    "../../../services/project/moveProjectToCategory": {
      moveProjectToCategory: async (id, cid) => project(id, cid),
    },
  };
  const http = { HttpRequestError: class extends Error {}, fetchJson: async (url, options) => {
    assert.equal(url, "/api/workspace/last-opened");
    if (!options) return structuredClone(saved);
    assert.equal(options.method, "PUT");
    return new Promise((resolve, reject) => writes.push({ input: JSON.parse(options.body), resolve, reject }));
  } };
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename);
    const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const module = { exports: {} };
    vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename })(
      name => {
        if (name in mocks) return mocks[name];
        if (name.endsWith("/httpClient")) return http;
        if (name.includes("/services/project/")) return new Proxy({}, {
          get: (_, key) => () => { throw new Error(`Unexpected service: ${name}.${String(key)}`); },
        });
        assert.ok(name.startsWith("."), name);
        return load(path.resolve(path.dirname(filename), `${name}.ts`));
      }, module, module.exports);
    modules.set(filename, module.exports);
    return module.exports;
  }
  const { useProjectCatalog } = load(fileURLToPath(new URL(
    "../src/features/project-catalog/model/useProjectCatalog.ts", import.meta.url,
  )));
  services = load(fileURLToPath(new URL("../src/services/workspace/workspaceLastOpened.ts", import.meta.url)));
  function Harness() { catalog = useProjectCatalog(); return null; }
  await act(async () => { renderer = create(React.createElement(Harness)); });
  assert.equal(catalog.state, "ready");
  assert.equal(catalog.selectedProjectId, "a2");
  assert.equal(catalog.selectedSessionId, null);
}
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });
const switchTo = id => act(async () => catalog.selectCategory(id, { persistWorkspaceSelection: false }));

test("catalog refresh retains projects and leaves session restoration to each project", async () => {
  await setup();
  await act(async () => catalog.reload());
  await switchTo("b");
  assert.equal(catalog.selectedProjectId, "b2");
  assert.equal(catalog.selectedSessionId, null);
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a2");
  assert.equal(catalog.selectedSessionId, null);
});

test("local selection survives switching away before its session is loaded or saved", async () => {
  await setup();
  await act(async () => { catalog.selectProject("a3"); catalog.selectCategory("b"); });
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a3");
  assert.equal(catalog.selectedSessionId, null);
  await act(async () => catalog.confirmSessionSelection("a3", "sa3"));
  await switchTo("b");
  await switchTo("a");
  assert.equal(catalog.selectedSessionId, null);
});

test("late save completion cannot overwrite a more recent local selection", async () => {
  await setup();
  let saving;
  await act(async () => { saving = services.saveWorkspaceLastOpened({ category_id: "a", project_id: "a2" }); });
  await act(async () => { catalog.selectProject("a3"); catalog.confirmSessionSelection("a3", "sa3"); });
  await act(async () => { writes[0].resolve(workspace()); await saving; });
  await switchTo("b");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a3");
  assert.equal(catalog.selectedSessionId, null);
});

test("pending refresh preserves navigation performed while loading and does not collapse the project", async () => {
  await setup();
  refresh = {};
  await act(async () => catalog.reload());
  await switchTo("b");
  await act(async () => { catalog.expandProject("b2", "new-session"); });
  await act(async () => refresh.resolve({ items: projects }));
  assert.equal(catalog.selectedCategoryId, "b");
  assert.equal(catalog.selectedProjectId, "b2");
  assert.equal(catalog.selectedSessionId, "new-session");
  assert.equal(catalog.expandedProjectId, "b2");
});

test("refresh after the selected project is removed clears its session and remembers the valid fallback", async () => {
  await setup();
  projects = projects.filter(item => item.project_id !== "a2");
  await act(async () => catalog.reload());
  assert.equal(catalog.selectedProjectId, "a1");
  assert.equal(catalog.selectedSessionId, null);
  await switchTo("b");
  assert.equal(catalog.selectedProjectId, "b2");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a1");
});

test("moving a selected project does not leak its session or replace the destination's remembered project", async () => {
  await setup();
  await act(async () => catalog.moveProjectToCategory("a2", "b"));
  assert.equal(catalog.selectedProjectId, "a1");
  assert.equal(catalog.selectedSessionId, null);
  await switchTo("b");
  assert.equal(catalog.selectedProjectId, "b2");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a1");
});

test("new empty category has no project from the previous category", async () => {
  await setup();
  await act(async () => catalog.createProjectCategory());
  assert.equal(catalog.selectedCategoryId, "c");
  assert.equal(catalog.selectedProjectId, null);
  assert.equal(catalog.selectedSessionId, null);
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a2");
});

test("newly created project is remembered without waiting for a save response", async () => {
  await setup();
  await act(async () => catalog.createProject());
  assert.equal(catalog.selectedProjectId, "new");
  await switchTo("b");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "new");
});

test("failed persistence does not undo navigation and the save queue can recover", async () => {
  await setup();
  await act(async () => catalog.selectCategory("b"));
  await act(async () => { catalog.selectProject("b1"); catalog.confirmSessionSelection("b1", "sb1"); });
  await act(async () => writes[0].reject(new Error("offline")));
  await switchTo("a");
  await act(async () => catalog.selectCategory("b"));
  assert.equal(writes.length, 2);
  assert.equal(catalog.selectedProjectId, "b1");
  assert.equal(catalog.selectedSessionId, null);
  await act(async () => writes[1].resolve(workspace()));
  await switchTo("a");
  await switchTo("b");
  assert.equal(catalog.selectedProjectId, "b1");
});

test("late session confirmation from the previous project cannot contaminate the active category", async () => {
  await setup();
  await switchTo("b");
  await act(async () => catalog.confirmSessionSelection("a2", "late-a-session"));
  assert.equal(catalog.selectedProjectId, "b2");
  assert.equal(catalog.selectedSessionId, null);
  await switchTo("a");
  assert.equal(catalog.selectedSessionId, null);
});

test("deleting a project preserves other categories and an emptied category has no stale session", async () => {
  await setup();
  await act(async () => catalog.deleteProject("a2"));
  assert.equal(catalog.selectedProjectId, "a1");
  assert.equal(catalog.selectedSessionId, null);
  await act(async () => catalog.deleteProject("a1"));
  await act(async () => catalog.deleteProject("a3"));
  assert.equal(catalog.selectedProjectId, null);
  await switchTo("b");
  assert.equal(catalog.selectedProjectId, "b2");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, null);
  assert.equal(catalog.selectedSessionId, null);
});


test("project navigation persists before session loading; session confirmation never writes global state", async () => {
  await setup();
  await act(async () => catalog.selectProject("a3", "explicit-session"));
  assert.equal(catalog.selectedSessionId, "explicit-session");
  assert.deepEqual(writes.map(item => item.input), [{ category_id: "a", project_id: "a3" }]);
  await act(async () => writes[0].resolve(workspace()));
  await act(async () => catalog.confirmSessionSelection("a3", "confirmed-session"));
  assert.equal(catalog.selectedSessionId, "confirmed-session");
  assert.equal(writes.length, 1);
  await switchTo("b");
  await switchTo("a");
  assert.equal(catalog.selectedProjectId, "a3");
  assert.equal(catalog.selectedSessionId, null, "restore from project, never from a global session hint");
});
