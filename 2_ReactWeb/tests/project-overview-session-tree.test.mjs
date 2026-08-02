import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const {
  buildProjectOverviewSessionTree,
  collectSessionAncestorIds,
} = await vite.ssrLoadModule(
  "/src/features/project-category-overview/model/projectOverviewSessionTree.ts",
);

after(async () => {
  await vite.close();
});

test("项目卡片按明确关系类型构造任意深度层级", () => {
  const sessions = [
    session("ai-grandchild", 4),
    session("ai-child", 3),
    session("branch-child", 2),
    session("root", 1),
  ];
  const relations = [
    relation("node-root", "root", null, null, "root", "user", "empty"),
    relation(
      "node-branch",
      "branch-child",
      "node-root",
      "root",
      "fork",
      "ai",
      "fork",
    ),
    relation(
      "node-ai",
      "ai-child",
      "node-root",
      "root",
      "child",
      "user",
      "empty",
    ),
    relation(
      "node-ai-grandchild",
      "ai-grandchild",
      "node-ai",
      "ai-child",
      "child",
      "ai",
      "empty",
    ),
  ];

  const tree = buildProjectOverviewSessionTree(sessions, relations);

  assert.deepEqual(
    tree.roots.map((node) => node.session.session_id),
    ["root"],
  );
  assert.deepEqual(
    tree.roots[0].childrenByGroup.branch.map((node) => node.session.session_id),
    ["branch-child"],
  );
  assert.deepEqual(
    tree.roots[0].childrenByGroup.child.map((node) => node.session.session_id),
    ["ai-child"],
  );
  assert.deepEqual(
    tree.roots[0].childrenByGroup.child[0].childrenByGroup.child.map(
      (node) => node.session.session_id,
    ),
    ["ai-grandchild"],
  );
  assert.deepEqual(
    collectSessionAncestorIds(
      "ai-grandchild",
      tree.parentSessionIdBySession,
    ),
    ["ai-child", "root"],
  );
});

test("删除中间会话后仍沿明确父会话关系连接最近存活祖先", () => {
  const sessions = [
    session("root", 1),
    session("grandchild", 3),
  ];
  const relations = [
    relation("node-root", "root", null, null, "root", "user", "empty"),
    {
      ...relation(
        "node-deleted",
        "deleted-child",
        "node-root",
        "root",
        "child",
        "ai",
        "empty",
      ),
      deleted_at: "2026-07-28T01:00:00Z",
    },
    relation(
      "node-grandchild",
      "grandchild",
      "node-deleted",
      "deleted-child",
      "child",
      "ai",
      "empty",
    ),
  ];

  const tree = buildProjectOverviewSessionTree(sessions, relations);

  assert.deepEqual(
    tree.roots[0].childrenByGroup.child.map((node) => node.session.session_id),
    ["grandchild"],
  );
});

test("功能会话按明确功能类型归入独立分类", () => {
  const sessions = [
    session("root", 1),
    session("naming", 2),
    session("compaction", 3),
    session("project-memory", 4),
    session("global-memory", 5),
  ];
  const relations = [
    relation("node-root", "root", null, null, "root", "user", "empty"),
    {
      ...relation(
        "node-naming",
        "naming",
        "node-root",
        "root",
        "functional",
        "system",
        "copy",
      ),
      function_type: "automatic_naming",
    },
    {
      ...relation(
        "node-compaction",
        "compaction",
        "node-root",
        "root",
        "functional",
        "system",
        "copy",
      ),
      function_type: "memory_compaction",
    },
    {
      ...relation(
        "node-project-memory",
        "project-memory",
        "node-root",
        "root",
        "functional",
        "system",
        "copy",
      ),
      function_type: "project_memory_management",
    },
    {
      ...relation(
        "node-global-memory",
        "global-memory",
        "node-root",
        "root",
        "functional",
        "system",
        "copy",
      ),
      function_type: "global_memory_management",
    },
  ];

  const tree = buildProjectOverviewSessionTree(sessions, relations);
  const root = tree.roots[0];

  assert.deepEqual(
    root.childrenByGroup.automaticNaming.map((node) => node.session.session_id),
    ["naming"],
  );
  assert.deepEqual(
    root.childrenByGroup.memoryCompaction.map((node) => node.session.session_id),
    ["compaction"],
  );
  assert.deepEqual(
    root.childrenByGroup.projectMemoryManagement.map(
      (node) => node.session.session_id,
    ),
    ["project-memory"],
  );
  assert.deepEqual(
    root.childrenByGroup.globalMemoryManagement.map(
      (node) => node.session.session_id,
    ),
    ["global-memory"],
  );
});

function session(sessionId, sequenceNumber) {
  return {
    session_id: sessionId,
    sequence_number: sequenceNumber,
    title: sessionId,
    runtime_status: "idle",
    provider_id: null,
    model_id: null,
    message_count: 0,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
    pinned: false,
    usage: {},
    displayUsage: { total_tokens: 0 },
  };
}

function relation(
  branchId,
  sessionId,
  parentBranchId,
  parentSessionId,
  relationKind,
  createdBy,
  historyMode,
) {
  return {
    branch_id: branchId,
    tree_id: `tree-${sessionId}`,
    session_id: sessionId,
    parent_branch_id: parentBranchId,
    parent_session_id: parentSessionId,
    relation_kind: relationKind,
    function_type: null,
    created_by: createdBy,
    history_mode: historyMode,
    source_message_id: null,
    sibling_index: 0,
    created_at: "2026-07-28T00:00:00Z",
    deleted_at: null,
  };
}
