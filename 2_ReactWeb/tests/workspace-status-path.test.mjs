import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({
  root: fileURLToPath(new URL("../", import.meta.url)),
  configFile: fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
  appType: "custom",
  logLevel: "silent",
  server: { middlewareMode: true },
});
after(() => vite.close());
const { AppStatusBarProvider, useAppStatusBar } = await vite.ssrLoadModule("/src/widgets/app-frame/model/appStatusBar.tsx");
const { useWorkspaceStatusPath } = await vite.ssrLoadModule("/src/pages/workspace/ui/WorkspaceStatusPath.tsx");

function Footer(options) {
  useWorkspaceStatusPath(options);
  return useAppStatusBar().statusBar.left ?? null;
}

test("七个集的路径跟随列表选中项和已进入的工作区，点击定位到同一目标", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    requests.push([new URL(url).pathname, JSON.parse(init.body).path]);
    return new Response(null, { status: 204 });
  });
  let view;
  t.after(async () => { if (view) await act(async () => view.unmount()); });
  const options = { collections: {}, toolFolders: {}, sidePanelWidth: 300 };
  async function show() {
    const frame = createElement(AppStatusBarProvider, null, createElement(Footer, options));
    await act(async () => { if (view) view.update(frame); else view = create(frame); });
  }
  async function check(project, filePath = "") {
    await show();
    const button = view.root.findByType("button");
    const label = filePath ? project.root_path + "\\" + filePath.replaceAll("/", "\\") : project.root_path;
    assert.equal(button.props.title, label);
    assert.deepEqual(button.findByType("span").children, [label]);
    const count = requests.length;
    await act(async () => button.props.onClick());
    assert.deepEqual(requests.slice(count), [[`/api/projects/${project.project_id}/files/reveal`, filePath]]);
  }

  for (const [section, kind] of Object.entries({
    overview: "project", knowledge: "knowledge", experience: "experience",
    roles: "role", themes: "theme", models: "provider", tools: "tool",
  })) {
    const project = { category_id: kind, project_id: kind + "-id", root_path: "C:\\Data\\" + kind };
    function select(selected, expanded = null, categoryId = kind) {
      if (kind === "tool") {
        options.toolFolders = { displayedToolsetId: categoryId, selectedFolder: selected, expandedFolder: expanded };
      } else {
        options.collections[kind] = { selectedCategoryId: categoryId, selectedProject: selected, expandedProject: expanded };
      }
    }
    const file = "docs/readme.md";
    const source = kind === "tool"
      ? { kind: "tool-folder", key: `tool-folder:${kind}:${project.project_id}`, id: project.project_id }
      : { kind: "project", id: project.project_id };
    const tabKey = kind === "tool" ? "toolTab" : "projectTab";
    options.section = section;
    select(project);
    options[tabKey] = { fileSource: source, filePath: file };
    await check(project); // Cached tabs cannot override the list selection.
    select(project, project);
    await check(project, file);
    options[tabKey] = { fileSource: null, filePath: null };
    await check(project); // Dashboard
    options[tabKey] = { fileSource: { ...source, id: "other", key: "tool-folder:other:other" }, filePath: file };
    await check(project); // Previous workspace's tab during a switch
    const next = { ...project, project_id: kind + "-next", root_path: project.root_path + "-next" };
    select(next);
    await check(next);
    select(next, null, "empty-category");
    await show();
    assert.equal(view.root.findAllByType("button").length, 0);
  }
  options.section = "settings";
  await show();
  assert.equal(view.root.findAllByType("button").length, 0);
});
