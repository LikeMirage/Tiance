import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import {
  clientToolRequest, conversationBranchNode, conversationSession,
  installClientToolTestGlobals, installFetchRouter,
} from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { createConversationManagementClientToolRegistration } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationManagementClientTool.ts");
const { buildConversationSessionIndex, collectConversationDescendantIds } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationSessionScope.ts");
let restore;
before(() => { restore = installClientToolTestGlobals(); });
after(async () => { restore(); await vite.close(); });

function tree() {
  const definitions = [
    ["caller", null, "root"], ["root", null, "root"],
    ["child", "root", "child"], ["fork", "root", "fork"],
    ["naming", "root", "functional", "automatic_naming"],
    ["compact", "root", "functional", "memory_compaction"],
    ["project-memory", "root", "functional", "project_memory_management"],
    ["global-memory", "root", "functional", "global_memory_management"],
    ["grandchild", "compact", "child"],
    ["deep-compact", "grandchild", "functional", "memory_compaction"],
  ];
  return {
    project_id: "project-a", active_session_id: "root", count: definitions.length,
    items: definitions.map(([id], i) => conversationSession({ session_id: id, sequence_number: i + 1, settings: undefined, title: id })),
    branch_nodes: definitions.map(([id, parent, kind, fn]) => conversationBranchNode({
      session_id: id, branch_id: "branch-" + id, parent_session_id: parent,
      relation_kind: kind, function_type: fn ?? null,
    })),
    session_states: Object.fromEntries(definitions.map(([id]) => [id, { runtime_status: id === "deep-compact" ? "error" : "idle" }])),
  };
}
function setup(response = tree(), deleteFailure = false) {
  const calls = [];
  installFetchRouter(({ method, url, init }) => {
    calls.push({ method, path: url.pathname, body: init.body ? JSON.parse(init.body) : null });
    if (method === "GET" && url.pathname.endsWith("/conversations/summaries")) return response;
    if (method === "DELETE" && url.pathname.endsWith("/conversations")) {
      return deleteFailure ? new Response("changed", { status: 409 }) : new Response(null, { status: 204 });
    }
    throw new Error("Unexpected request " + method + " " + url.pathname);
  });
  const registration = createConversationManagementClientToolRegistration({ showSession() {} });
  return { calls, execute: (args, sessionId = "caller", signal) => registration.execute(
    clientToolRequest({ arguments: args, name: "manage_ai_conversations", sessionId }),
    signal ? { signal } : undefined,
  ), registration };
}

test("v3 列表按指定父级及全部四个功能分类返回完整层级信息，不读取详情", async () => {
  const { execute, calls, registration } = setup();
  assert.equal(registration.capability.version, 3);
  const direct = await execute({ action: "list_sessions", scope: "children", session_id: "root", group: "functional" });
  assert.equal(direct.ok, true, direct.error);
  assert.deepEqual(direct.content.sessions.map((s) => s.group), ["automatic_naming", "memory_compaction", "project_memory_management", "global_memory_management"]);
  for (const row of direct.content.sessions) {
    assert.equal(row.parent_session_id, "root");
    assert.equal(row.depth, 1);
    assert.equal(row.display_number, 1);
    assert.equal(row.relation_kind, "functional");
  }
  const deep = await execute({ action: "list_sessions", scope: "descendants", session_id: "root", group: "memory_compaction" });
  assert.deepEqual(deep.content.sessions.map((s) => s.session_id), ["compact", "deep-compact"]);
  assert.equal(deep.content.sessions[1].depth, 3);
  assert.equal(deep.content.sessions[1].parent_session_id, "grandchild");
  const errors = await execute({ action: "list_sessions", scope: "all", runtime_status: "error" });
  assert.deepEqual(errors.content.sessions.map((s) => s.session_id), ["deep-compact"]);
  const roots = await execute({ action: "list_sessions", scope: "roots" });
  assert.deepEqual(roots.content.sessions.map((s) => s.session_id), ["caller", "root"]);
  assert.ok(calls.every((c) => c.path.endsWith("/summaries")));
});

test("默认只预览目标本身，保留后代并显示预计新父级", async () => {
  const { execute, calls } = setup();
  const result = await execute({ action: "preview_delete", session_id: "compact" });
  assert.equal(result.ok, true, result.error);
  assert.deepEqual(result.content.session_ids, ["compact"]);
  assert.deepEqual(result.content.reparented_sessions, [{ session_id: "grandchild", title: "grandchild", previous_parent_session_id: "compact", parent_session_id: "root" }]);
  assert.ok(calls.every((c) => c.method === "GET"));
  const rootPreview = await execute({ action: "preview_delete", session_id: "root" });
  assert.equal(rootPreview.content.reparented_sessions.length, 6);
  assert.ok(rootPreview.content.reparented_sessions.every((row) => row.parent_session_id === null));
});

test("递归批量去重，预览清单可以精确执行且不吞掉后来新建的后代", async () => {
  const response = tree();
  const { execute, calls } = setup(response);
  const preview = await execute({ action: "preview_delete", session_ids: ["compact", "grandchild", "compact", "fork"], include_descendants: true });
  assert.equal(preview.ok, true, preview.error);
  assert.deepEqual(new Set(preview.content.session_ids), new Set(["compact", "grandchild", "deep-compact", "fork"]));
  response.items.push(conversationSession({ session_id: "new-child", title: "new-child" }));
  response.branch_nodes.push(conversationBranchNode({ session_id: "new-child", parent_session_id: "compact", relation_kind: "child" }));
  const result = await execute({ action: "delete_session", session_ids: preview.content.session_ids, include_descendants: false, confirm: true });
  assert.equal(result.ok, true, result.error);
  assert.equal(result.content.count, 4);
  assert.deepEqual(result.content.deleted_session_ids, preview.content.session_ids);
  const deletions = calls.filter((c) => c.method === "DELETE");
  assert.equal(deletions.length, 1);
  assert.deepEqual(deletions[0].body, { session_ids: preview.content.session_ids, protected_session_id: "caller" });
  assert.ok(!deletions[0].body.session_ids.includes("new-child"));
});

test("拒绝自删、祖先删除、无效目标、筛选误用、缺少确认；一律不发删除请求", async () => {
  const { execute, calls } = setup();
  const cases = [
    [{ session_id: "caller" }],
    [{ session_id: "root" }, "grandchild"],
    [{ session_id: "root", include_descendants: true }, "deep-compact"],
    [{ session_ids: ["fork", "missing"] }],
    [{ session_ids: [] }],
    [{ session_id: "fork", session_ids: ["fork"] }],
    [{ session_id: "fork", include_descendants: "false" }],
    [{ session_id: "fork", group: "memory_compaction" }],
    [{ session_id: "fork", confirm: false }],
    [{ session_id: "fork" }, null],
  ];
  for (const [args, caller = "caller"] of cases) {
    const result = await execute({ action: "delete_session", confirm: true, ...args }, caller);
    assert.equal(result.ok, false, JSON.stringify(args));
  }
  assert.ok(calls.every((c) => c.method !== "DELETE"));
});

test("删除接口失败不会报告已删除，调用取消后不发删除请求", async () => {
  const { execute, calls } = setup(tree(), true);
  const failed = await execute({ action: "delete_session", session_id: "fork", confirm: true });
  assert.equal(failed.ok, false);
  assert.equal(failed.content.deleted_session_ids, undefined);
  const controller = new AbortController();
  controller.abort();
  const cancelled = await execute({ action: "delete_session", session_id: "fork", confirm: true }, "caller", controller.signal);
  assert.equal(cancelled.ok, false);
  assert.equal(calls.filter((c) => c.method === "DELETE").length, 1);
});

test("千层后代迭代展开，不设置隐含层数上限", () => {
  const response = tree();
  for (let i = 0; i < 1100; i += 1) {
    response.items.push(conversationSession({ session_id: "depth-" + i }));
    response.branch_nodes.push(conversationBranchNode({ session_id: "depth-" + i,
      parent_session_id: i === 0 ? "deep-compact" : "depth-" + (i - 1), relation_kind: "child" }));
  }
  const index = buildConversationSessionIndex(response);
  const descendants = collectConversationDescendantIds(index, ["compact"]);
  assert.equal(descendants.size, 1102);
  assert.ok(descendants.has("depth-1099"));
});
