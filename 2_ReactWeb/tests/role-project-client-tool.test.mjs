import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { installClientToolTestGlobals, installFetchRouter } from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const root = new URL("../../Data/tools/030b5552-6e0c-5a24-b200-6a626038ce9e/", import.meta.url);
const vite = await createServer({ appType: "custom", logLevel: "silent", root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { createRoleProjectClientToolRegistration } = await vite.ssrLoadModule("/src/features/client-tools/model/roleProjectClientTool.ts");
let restore;
before(() => { restore = installClientToolTestGlobals(); });
after(async () => { restore(); await vite.close(); });

function setup(kind = "role") {
  const calls = [];
  const project = { project_id: "caller", project_kind: kind, root_path: "C:/Data/roles/caller", name: "角色", category_id: "roles" };
  installFetchRouter(async ({ method, url, init }) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname, body });
    if (method === "GET" && url.pathname === "/api/projects") return { items: [project] };
    if (method === "GET" && url.pathname === "/api/projects/manager/files/content") {
      return { content: await readFile(new URL(url.searchParams.get("path"), root), "utf8") };
    }
    if (method === "POST" && url.pathname === "/api/projects/roles") return { ...project, project_id: "new-role", name: body.name };
    if (method === "POST" && url.pathname.endsWith("/files/scaffold")) return { root_path: project.root_path, written_files: body.files.map(f => f.path), preserved_files: [] };
    throw new Error(`Unexpected ${method} ${url}`);
  });
  return calls;
}

function execute(args) {
  return createRoleProjectClientToolRegistration().execute({ request_id: "r", call_id: "c", name: "manage_roles", project_id: "caller", session_id: "s", tool_project_id: "manager", arguments: JSON.stringify(args) }, { signal: new AbortController().signal });
}

test("角色创建复用原流程并批量补充说明，模板无私人模型配置", async () => {
  const calls = setup();
  const result = await execute({ action: "create_role", name: "校对员", category_id: "roles" });
  assert.equal(result.ok, true, result.error);
  const writes = calls.filter(c => c.method === "POST");
  assert.deepEqual(writes.map(c => c.path), ["/api/projects/roles", "/api/projects/new-role/files/scaffold"]);
  assert.equal(writes[1].body.project_kind, "role");
  const files = writes[1].body.files;
  assert.equal(files.length, 9);
  assert.equal(JSON.parse(files.find(f => f.path === "model.json").content).model_id, null);
  assert.ok(files.find(f => f.path === "docs/role-development/README.md").content.includes("model_source"));
});

test("原地初始化使用调用项目，错误集无写入", async () => {
  let calls = setup();
  assert.equal((await execute({ action: "initialize_current" })).ok, true);
  assert.deepEqual(calls.filter(c => c.method === "POST").map(c => c.path), ["/api/projects/caller/files/scaffold"]);
  calls = setup("project");
  assert.equal((await execute({ action: "initialize_current" })).ok, false);
  assert.equal(calls.some(c => c.method === "POST"), false);
});
