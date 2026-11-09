import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { useDefaultRoles } = await vite.ssrLoadModule("/src/features/default-role-settings/model/useDefaultRoles.ts");
const { DEFAULT_ROLE_COLLECTIONS } = await vite.ssrLoadModule("/src/services/project/defaultRoles.ts");
const { functionalModelSettingsSections } = await vite.ssrLoadModule("/src/features/functional-model-settings/model/functionalModelSections.ts");
const { isFunctionalModelSettingsSection } = await vite.ssrLoadModule("/src/pages/workspace/model/workspaceSettingsSections.ts");

test("七个集都有默认角色入口，与功能模型分开", () => {
  assert.deepEqual([...DEFAULT_ROLE_COLLECTIONS], ["project", "tool", "knowledge", "experience", "role", "provider", "theme"]);
  assert.equal(isFunctionalModelSettingsSection("default-roles"), false);
  assert.equal(functionalModelSettingsSections.length, 4);
  for (const section of functionalModelSettingsSections) assert.equal(isFunctionalModelSettingsSection(section.id), true);
});

test("逐集保存，失败不冒充成功；保存期间目录刷新排在保存后", async () => {
  const originalWindow = globalThis.window, originalFetch = globalThis.fetch, originalDocument = globalThis.document;
  const events = new EventTarget();
  globalThis.window = { addEventListener: (...args) => events.addEventListener(...args), removeEventListener: (...args) => events.removeEventListener(...args) };
  globalThis.document = { addEventListener() {}, removeEventListener() {} };
  const defaults = Object.fromEntries(DEFAULT_ROLE_COLLECTIONS.map(kind => [kind, "default"]));
  let rejectSave = true, finishSave, readCount = 0;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([String(url), init?.body]);
    if (String(url).endsWith("/roles/catalog")) return Response.json({
      default_role_project_id: "default", categories: [],
      roles: ["default", "author"].map(role_project_id => ({ role_project_id, name: role_project_id })),
    });
    if (init?.method === "PUT") {
      if (rejectSave) return Response.json({ detail: "写入失败" }, { status: 500 });
      await new Promise(resolve => { finishSave = resolve; });
      const kind = String(url).split("/").at(-1);
      defaults[kind] = JSON.parse(init.body).role_project_id;
      return Response.json({ role_project_id: defaults[kind] });
    }
    readCount++;
    return Response.json(defaults);
  };
  let state, view;
  function Probe() { state = useDefaultRoles(); return null; }
  try {
    await act(async () => { view = create(createElement(Probe)); });
    assert.equal(state.isLoading, false);
    await act(async () => assert.equal(await state.select("tool", "author"), false));
    assert.equal(state.defaults.tool, "default");
    assert.match(state.error, /500/);
    rejectSave = false;
    let pending;
    await act(async () => { pending = state.select("tool", "author"); });
    await act(async () => {
      events.dispatchEvent(new Event("tiance:project-catalog-changed"));
      assert.equal(await state.select("theme", "author"), false);
    });
    assert.equal(readCount, 1);
    await act(async () => { finishSave(); assert.equal(await pending, true); });
    assert.equal(readCount, 2);
    assert.equal(state.defaults.tool, "author");
    assert.equal(state.defaults.theme, "default");
    assert.equal(state.isLoading, false);
    assert.equal(state.isSaving, false);
    assert.ok(calls.some(([url, body]) => url.endsWith("/defaults/tool") && body === '{"role_project_id":"author"}'));
  } finally {
    if (view) await act(async () => view.unmount());
    globalThis.window = originalWindow; globalThis.fetch = originalFetch; globalThis.document = originalDocument;
  }
});
