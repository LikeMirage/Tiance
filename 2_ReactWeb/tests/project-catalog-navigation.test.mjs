import assert from "node:assert/strict";
import test from "node:test";
import { act, createElement } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({
  logLevel: "silent",
  server: { middlewareMode: true },
});
const { useProjectCatalog } = await vite.ssrLoadModule(
  "/src/features/project-catalog/model/useProjectCatalog.ts",
);
const { useWorkspaceProjectCollections } = await vite.ssrLoadModule(
  "/src/pages/workspace/model/useWorkspaceProjectCollections.ts",
);
const originalWebSocket = globalThis.WebSocket;
const originalWindow = globalThis.window;
const originalDocument = globalThis.document;
const originalActEnvironment = globalThis.IS_REACT_ACT_ENVIRONMENT;
globalThis.window = new EventTarget();
globalThis.document = new EventTarget();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
// Catalog event subscriptions stay local; tests never contact the running app.
globalThis.WebSocket = class { close() {} };
test.after(async () => {
  globalThis.WebSocket = originalWebSocket;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
  if (originalDocument === undefined) delete globalThis.document;
  else globalThis.document = originalDocument;
  if (originalActEnvironment === undefined) delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  else globalThis.IS_REACT_ACT_ENVIRONMENT = originalActEnvironment;
  await vite.close();
});

const categories = [
  { category_id: "daily", category_kind: "project", is_default: true },
  { category_id: "work", category_kind: "project" },
  { category_id: "knowledge", category_kind: "knowledge", is_default: true },
];
const projects = [
  { project_id: "daily-project", category_id: "daily", project_kind: "project" },
  { project_id: "work-project", category_id: "work", project_kind: "project" },
  { project_id: "knowledge-project", category_id: "knowledge", project_kind: "knowledge" },
];

async function mountCatalog(t, initialCategory = "knowledge") {
  const initialProject = projects.find((project) => project.category_id === initialCategory);
  const saved = {
    category_id: initialCategory,
    project_id: initialProject.project_id,
    session_id: "saved-session",
    category_selections: {},
    updated_at: null,
  };
  t.mock.method(globalThis, "fetch", async (input, init = {}) => {
    assert.equal(init.method ?? "GET", "GET", "navigation must not write server data");
    const path = new URL(input).pathname;
    const responses = {
      "/api/projects": { items: projects },
      "/api/projects/categories": { items: categories },
      "/api/projects/order": { project_ids: [] },
      "/api/workspace/last-opened": saved,
    };
    assert.ok(path in responses, `Unexpected request: ${path}`);
    return Response.json(responses[path]);
  });
  let current;
  function Probe() {
    const catalog = useProjectCatalog();
    const workspace = useWorkspaceProjectCollections(catalog);
    current = { catalog, ...workspace };
    return null;
  }
  let renderer;
  await act(async () => { renderer = create(createElement(Probe)); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  assert.equal(current.catalog.state, "ready", current.catalog.error ?? undefined);
  return () => current;
}

test("entering a visible project repairs a category restored from another collection", async (t) => {
  const get = await mountCatalog(t);
  assert.equal(get().catalog.selectedCategoryId, "knowledge");
  assert.equal(get().collections.project.expandedProject, null);

  await act(async () => get().catalog.expandProject("daily-project", "session-35"));

  assert.equal(get().collections.project.expandedProject?.project_id, "daily-project");
  assert.equal(get().collections.project.selectedCategoryId, "daily");
  assert.equal(get().collections.project.selectedSessionId, "session-35");

  // A background catalog refresh must not undo the repaired entry.
  await act(async () => get().catalog.reload());
  assert.equal(get().collections.project.expandedProject?.project_id, "daily-project");
  assert.equal(get().catalog.selectedCategoryId, "daily");
});

test("selecting then entering the same project synchronizes category without opening on single click", async (t) => {
  const get = await mountCatalog(t);
  await act(async () => get().catalog.selectProject("daily-project", "session-31"));
  assert.equal(get().catalog.selectedCategoryId, "daily");
  assert.equal(get().collections.project.selectedProject?.project_id, "daily-project");
  assert.equal(get().collections.project.expandedProject, null);

  await act(async () => get().catalog.expandProject("daily-project", "session-31"));
  await act(async () => get().catalog.expandProject("daily-project", "session-31"));
  assert.equal(get().collections.project.expandedProject?.project_id, "daily-project");
  assert.equal(get().collections.project.selectedSessionId, "session-31");
});

test("entering another category of the same kind survives catalog refresh", async (t) => {
  const get = await mountCatalog(t, "daily");
  await act(async () => get().catalog.expandProject("work-project"));
  assert.equal(get().catalog.selectedCategoryId, "work");
  assert.equal(get().catalog.selectedSessionId, null);
  await act(async () => get().catalog.reload());
  assert.equal(get().collections.project.expandedProject?.project_id, "work-project");
});
