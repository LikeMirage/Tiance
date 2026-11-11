import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
  plugins: [{
    name: "project-removal-test", enforce: "pre",
    transform(code, id) {
      const path = id.replaceAll("\\", "/");
      if (path.endsWith("/src/shared/i18n/index.ts")) {
        return "export const useI18n = () => ({ t: (key, args) => key + (args ? JSON.stringify(args) : '') });";
      }
      if (path.endsWith("/ConfirmModal.tsx")) {
        return code.replace('import { createPortal } from "react-dom";',
          "const createPortal = (children: any, _target: any) => children;");
      }
    },
  }],
});
const { ProjectDeleteConfirmModal } = await vite.ssrLoadModule(
  "/src/features/project-catalog/ui/ProjectDeleteConfirmModal.tsx",
);
const { deleteProject } = await vite.ssrLoadModule("/src/services/project/deleteProject.ts");
const { runSequentialProjectBatchAction } = await vite.ssrLoadModule(
  "/src/features/project-catalog/model/projectBatchActions.ts",
);
after(() => vite.close());

test("移除默认不清理，勾选后提交选择；重新打开仍默认关闭", async () => {
  const previous = { window: globalThis.window, document: globalThis.document, act: globalThis.IS_REACT_ACT_ENVIRONMENT };
  globalThis.window = new EventTarget();
  globalThis.document = { body: {} };
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let view, submitted, cancelled = 0;
  const pending = { mode: "remove", projectIds: ["one", "two"], projectNames: ["One", "Two"] };
  function Harness({ mode = "remove", busy = false, error = null }) {
    const [value, setValue] = React.useState({ ...pending, mode });
    return React.createElement(ProjectDeleteConfirmModal, {
      pendingDelete: value, isDeleting: busy, error,
      onChangeClearTianceData: checked => setValue({ ...value, clearTianceData: checked }),
      onConfirm: value => { submitted = value; }, onCancel: () => { cancelled++; },
    });
  }
  try {
    await act(async () => { view = create(React.createElement(Harness)); });
    assert.equal(view.root.findByType("input").props.checked, false);
    await act(async () => { view.root.findByType("input").props.onChange({ target: { checked: true } }); });
    assert.equal(view.root.findByType("input").props.checked, true);
    assert.match(view.root.findByType("p").children.join(""), /removeWithData/);
    await act(async () => { view.root.findAllByType("button").at(-1).props.onClick(); });
    assert.deepEqual(submitted, { ...pending, clearTianceData: true });
    await act(async () => { view.update(React.createElement(Harness, { busy: true })); });
    assert.equal(view.root.findByType("input").props.disabled, true);
    await act(async () => { view.unmount(); view = create(React.createElement(Harness)); });
    assert.equal(view.root.findByType("input").props.checked, false);
    await act(async () => { view.root.findAllByType("button")[0].props.onClick(); });
    assert.equal(cancelled, 1);
    await act(async () => { view.unmount(); view = create(React.createElement(Harness, { mode: "delete-local" })); });
    assert.equal(view.root.findAllByType("input").length, 0);
  } finally {
    if (view) await act(async () => { view.unmount(); });
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = previous.act;
  }
});

test("请求只在勾选时携带清理参数，批量失败不继续删除剩余项目", async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push([String(url), options.method]);
    if (String(url).includes("/fail?")) return Response.json({ message: "文件占用" }, { status: 409 });
    return new Response(null, { status: 204 });
  };
  try {
    await deleteProject("plain");
    assert.match(requests[0][0], /\/plain$/);
    const result = await runSequentialProjectBatchAction(["one", "fail", "three"],
      id => deleteProject(id, { clearTianceData: true }));
    assert.deepEqual(result.completedProjectIds, ["one"]);
    assert.deepEqual(result.remainingProjectIds, ["fail", "three"]);
    assert.ok(result.error);
    assert.equal(requests.length, 3);
    assert.match(requests[1][0], /\/one\?clear_tiance_data=true$/);
    assert.ok(requests.every(([, method]) => method === "DELETE"));
  } finally { globalThis.fetch = previous; }
});
