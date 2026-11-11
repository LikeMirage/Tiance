import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import {
  installClientToolTestGlobals, installFetchRouter,
} from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const packageRoot = new URL("../../Data/tools/34b16133-f310-4064-b71f-f0411d13ab1d/", import.meta.url);
const vite = await createServer({
  appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true },
});
const { createToolProjectClientToolRegistration } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/toolProjectClientTool.ts",
);
let restore;
before(() => { restore = installClientToolTestGlobals(); });
after(async () => { restore(); await vite.close(); });

const category = { category_id: "category-a", category_kind: "tool", name: "开发", readonly: false };
const project = { project_id: "created-project", project_kind: "tool", category_id: "category-a", name: "我的工具", root_path: "C:\\Data\\tools\\created-project" };

function request(args, extra = {}) {
  return { request_id: "r1", call_id: "c1", name: "renamed_creator", arguments: JSON.stringify(args),
    project_id: "caller-project", session_id: "caller-session", tool_project_id: "creator-project", ...extra };
}

function routeApi({ editSource, beforeSave, afterCreate, failCreate, existing = false, wrongKind = false } = {}) {
  const writes = [];
  const calls = [];
  installFetchRouter(async ({ method, url, init }) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname, body });
    if (method === "GET" && url.pathname === "/api/tools/categories") return { items: [category] };
    if (method === "GET" && url.pathname === "/api/projects/categories") return { items: [category] };
    if (method === "POST" && url.pathname === "/api/projects/categories") return { ...category, name: body.name };
    if (method === "GET" && url.pathname === "/api/projects") return { items: [{ ...project, project_kind: wrongKind ? "project" : "tool", project_id: "caller-project" }] };
    if (method === "GET" && url.pathname === "/api/projects/creator-project/files/content") {
      const path = url.searchParams.get("path");
      let content = await readFile(new URL(path, packageRoot), "utf8");
      content = editSource?.(path, content) ?? content;
      return { content, path };
    }
    if (method === "POST" && url.pathname === "/api/tools/categories/category-a/projects") {
      if (failCreate) throw new Error("响应丢失");
      afterCreate?.();
      return { ...project, name: body.name };
    }
    if (method === "POST" && url.pathname.endsWith("/files/scaffold")) {
      beforeSave?.();
      writes.push(...body.files);
      return { root_path: project.root_path, written_files: body.files.map(f => f.path), preserved_files: [] };
    }
    if (method === "GET" && url.pathname.endsWith("/files/content")) {
      const file = writes.find(f => f.path === ".tool/tool.json");
      return { content: existing ? JSON.stringify({ name: "existing_call", state: { enabled: true } }) : file.content };
    }
    throw new Error(`不应访问 ${method} ${url.pathname}`);
  });
  return { calls, writes };
}

async function execute(args, { signal = new AbortController().signal, extra } = {}) {
  return createToolProjectClientToolRegistration().execute(request(args, extra), { signal });
}

test("分类查询只读，创建分类复用产品接口", async () => {
  const { calls } = routeApi();
  const listed = await execute({ action: "list_categories" });
  assert.equal(listed.ok, true);
  assert.deepEqual(listed.content.categories, [category]);
  assert.deepEqual(calls.map((call) => call.method), ["GET"]);
  const created = await execute({ action: "create_category", name: "  业务工具  " });
  assert.equal(created.content.category.name, "业务工具");
  assert.deepEqual(calls.at(-1).body, { name: "业务工具", category_kind: "tool" });
});

test("从执行工具包读取完整模板，整组提交且默认关闭，不使用调用方项目或工具名", async () => {
  const { writes, calls } = routeApi({ editSource(path, content) {
    if (!path.endsWith(".tool/tool.json")) return content;
    const manifest = JSON.parse(content);
    manifest.state.enabled = true;
    return JSON.stringify(manifest);
  } });
  const result = await execute({ action: "create_tool", category_id: "category-a", name: '中文"名称', call_name: "process_orders" });
  assert.equal(result.ok, true, result.error);
  assert.equal(writes.length, 17);
  assert.equal(writes.at(-1).path, ".tool/tool.json");
  const manifest = JSON.parse(writes.at(-1).content);
  assert.equal(manifest.registration_name, '中文"名称');
  assert.equal(manifest.name, "process_orders");
  assert.equal(manifest.state.enabled, false);
  assert.equal(result.content.enabled, false);
  assert.ok(result.content.documentation_path.endsWith("docs/tool-development/README.md"));
  assert.ok(result.content.guidance.join("\n").includes("用户意愿"));
  const createdAt = calls.findIndex((call) => call.method === "POST");
  assert.ok(calls.slice(0, createdAt).filter((call) => call.path.endsWith("/files/content")).length === 18);
  assert.equal(calls.some((call) => call.path.includes("caller-project")), false);
  assert.equal(calls.filter(call => call.path.endsWith("/files/scaffold")).length, 1);
});

test("未指定调用名时使用新项目身份生成", async () => {
  routeApi();
  const result = await execute({ action: "create_tool", category_id: "category-a", name: "新工具" });
  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.call_name, "tool_createdproject");
});

test("模板缺文件、非法路径或读取失败时尚未创建项目", async () => {
  for (const mutate of [
    (index) => { index.files = index.files.filter((file) => file.target !== ".tool/input.schema.json"); },
    (index) => { index.files[0].target = "../outside.txt"; },
    (index) => { index.files[0].target = ".Tiance/tiance.db"; },
    (index) => { index.files[0].source = "assets/not-existing.txt"; },
    (index) => { index.files.push({ ...index.files[0], target: index.files[0].target.toUpperCase() }); },
  ]) {
    const { calls } = routeApi({ editSource(path, content) {
      if (path !== "assets/scaffold.json") return content;
      const index = JSON.parse(content); mutate(index); return JSON.stringify(index);
    } });
    const result = await execute({ action: "create_tool", category_id: "category-a", name: "新工具" });
    assert.equal(result.ok, false);
    assert.equal(result.content.status, "failed");
    assert.equal(calls.some((call) => call.method === "POST"), false);
  }
});

test("缺少工具项目上下文、无效分类和无效参数不创建", async () => {
  const cases = [
    [{ action: "create_tool", category_id: "category-a", name: "新工具" }, { tool_project_id: null }],
    [{ action: "create_tool", category_id: "missing", name: "新工具" }],
    [{ action: "create_tool", category_id: "category-a", name: "新工具", call_name: "bad name" }],
    [{ action: "create_tool", category_id: "category-a", name: "新工具", call_name: "UpperCase" }],
    [{ action: "create_tool", category_id: "category-a", name: "新工具", call_name: "_private" }],
    [{ action: "create_tool", category_id: "category-a" }],
  ];
  for (const [args, extra] of cases) {
    const { calls } = routeApi();
    const result = await execute(args, { extra });
    assert.equal(result.ok, false);
    assert.equal(calls.some((call) => call.method === "POST"), false);
  }
});

test("整组写入失败保留项目身份，不删项目也不重复创建", async () => {
  const { writes, calls } = routeApi({ beforeSave() {
    throw new Error("磁盘写入失败");
  } });
  const result = await execute({ action: "create_tool", category_id: "category-a", name: "新工具" });
  assert.equal(result.ok, false);
  assert.equal(result.content.status, "inspect_existing_project");
  assert.equal(result.content.project.project_id, project.project_id);
  assert.equal(writes.length, 0);
  assert.equal(calls.filter((call) => call.method === "POST").length, 2);
  assert.equal(calls.some((call) => call.method === "DELETE"), false);
});

test("取消前无副作用；开始提交后等待模板事务结算", async () => {
  const before = new AbortController(); before.abort();
  let state = routeApi();
  assert.equal((await execute({ action: "list_categories" }, { signal: before.signal })).ok, false);
  assert.equal(state.calls.length, 0);
  const after = new AbortController();
  state = routeApi({ afterCreate: () => after.abort() });
  const result = await execute({ action: "create_tool", category_id: "category-a", name: "新工具" }, { signal: after.signal });
  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.project.project_id, project.project_id);
  assert.equal(state.writes.length, 17);
});

test("初始化绑定调用工作区，无新目录，并返回保留后的真实启用状态", async () => {
  const { calls } = routeApi({ existing: true });
  const result = await execute({ action: "initialize_current" });
  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.call_name, "existing_call");
  assert.equal(result.content.enabled, true);
  assert.deepEqual(calls.filter(c => c.method === "POST").map(c => c.path), ["/api/projects/caller-project/files/scaffold"]);
});

test("其他集的调用工作区拒绝初始化，未发送写入请求", async () => {
  const { calls } = routeApi({ wrongKind: true });
  const result = await execute({ action: "initialize_current" });
  assert.equal(result.ok, false);
  assert.equal(calls.some(c => c.method === "POST"), false);
});

test("删除不能指向调用项目或管理工具自身", async () => {
  const { calls } = routeApi();
  const result = await execute({ action: "delete", project_id: "caller-project", confirm: true });
  assert.equal(result.ok, false);
  assert.equal(calls.some(c => c.method === "DELETE"), false);
});

test("POST 响应丢失如实报告结果未知，不自动重试", async () => {
  const { calls } = routeApi({ failCreate: true });
  const result = await execute({ action: "create_tool", category_id: "category-a", name: "新工具" });
  assert.equal(result.ok, false);
  assert.equal(result.content.status, "creation_outcome_unknown");
  assert.equal(calls.filter((call) => call.method === "POST").length, 1);
});
