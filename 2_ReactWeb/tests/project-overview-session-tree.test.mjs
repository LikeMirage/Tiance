import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
  plugins: [{
    name: "session-tree-test-translations",
    enforce: "pre",
    transform(_code, id) {
      if (id.replaceAll("\\", "/").endsWith("/src/shared/i18n/index.ts")) {
        return "export const useI18n = () => ({ t: key => key });";
      }
    },
  }],
});
const {
  buildProjectOverviewSessionTree,
  collectSessionAncestorIds,
} = await vite.ssrLoadModule(
  "/src/features/project-category-overview/model/projectOverviewSessionTree.ts",
);
const { buildConversationSessionTree } = await vite.ssrLoadModule(
  "/src/entities/llm-chat/model/conversationSessionTree.ts",
);
const { SessionDisplayTitle } = await vite.ssrLoadModule(
  "/src/features/ai-panel/ui/SessionDisplayTitle.tsx",
);
const { ProjectOverviewSessionTreeList } = await vite.ssrLoadModule(
  "/src/features/project-category-overview/ui/ProjectOverviewSessionTree.tsx",
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

function groupedFixture() {
  const sessions = [session("old-root", 1), session("new-root", 115)];
  const relations = [
    relation("node-old-root", "old-root", null, null, "root", "user", "empty"),
    relation("node-new-root", "new-root", null, null, "root", "user", "empty"),
  ];
  const add = (id, parent, sequence, kind, functionType = null) => {
    sessions.push(session(id, sequence));
    relations.push({ ...relation(`node-${id}`, id, `node-${parent}`, parent, kind, "system", "empty"),
      function_type: functionType, sibling_index: sequence });
  };
  for (const [index, type] of ["automatic_naming", "memory_compaction", "project_memory_management", "global_memory_management"].entries()) {
    add(`${type}-old`, "old-root", 10 + index * 10, "functional", type);
    add(`${type}-new`, "old-root", 11 + index * 10, "functional", type);
  }
  add("fork-old", "old-root", 49, "fork");
  add("fork-new", "old-root", 107, "fork");
  add("child-old", "old-root", 52, "child");
  add("child-new", "old-root", 53, "child");
  add("other-compaction", "new-root", 116, "functional", "memory_compaction");
  add("deep-compaction", "child-new", 117, "functional", "memory_compaction");
  add("deeper-child", "deep-compaction", 118, "child");
  return { sessions, relations, add };
}

test("root sessions, direct children and each of the four functional categories number independently at any depth", () => {
  const { sessions, relations } = groupedFixture();
  const tree = buildConversationSessionTree([...sessions].reverse(), relations);
  const numbers = tree.displaySequenceBySession;
  assert.equal(numbers.get("old-root"), 1);
  assert.equal(numbers.get("new-root"), 2);
  for (const type of ["automatic_naming", "memory_compaction", "project_memory_management", "global_memory_management"]) {
    assert.equal(numbers.get(`${type}-old`), 1);
    assert.equal(numbers.get(`${type}-new`), 2);
  }
  assert.equal(numbers.get("fork-old"), 1);
  assert.equal(numbers.get("fork-new"), 2);
  assert.equal(numbers.get("child-old"), 1);
  assert.equal(numbers.get("child-new"), 2);
  for (const id of ["other-compaction", "deep-compaction", "deeper-child"]) assert.equal(numbers.get(id), 1);
  assert.deepEqual(tree.roots.map(node => node.session.session_id), ["new-root", "old-root"]);
});

test("adding a functional session only advances its own category, never roots or another parent's category", () => {
  const fixture = groupedFixture();
  const before = buildConversationSessionTree(fixture.sessions, fixture.relations).displaySequenceBySession;
  fixture.add("next-compaction", "old-root", 119, "functional", "memory_compaction");
  const after = buildConversationSessionTree(fixture.sessions, fixture.relations).displaySequenceBySession;
  for (const [id, number] of before) assert.equal(after.get(id), number);
  assert.equal(after.get("next-compaction"), 3);
});

test("deleting a sibling closes the gap only in that category without rewriting stored numbers or titles", () => {
  const { sessions, relations } = groupedFixture();
  const before = buildConversationSessionTree(sessions, relations).displaySequenceBySession;
  const remaining = sessions.filter(item => item.session_id !== "memory_compaction-old");
  const source = JSON.stringify({ sessions, relations });
  sessions.forEach(Object.freeze);
  relations.forEach(Object.freeze);
  const after = buildConversationSessionTree(remaining, relations).displaySequenceBySession;
  assert.equal(after.has("memory_compaction-old"), false);
  assert.equal(after.get("memory_compaction-new"), 1);
  for (const [id, number] of before) {
    if (!id.startsWith("memory_compaction-")) assert.equal(after.get(id), number);
  }
  assert.equal(JSON.stringify({ sessions, relations }), source);
});

test("pinning and display order do not renumber sessions; chronological order wins over project-wide numbers", () => {
  const { sessions, relations } = groupedFixture();
  const before = buildConversationSessionTree(sessions, relations).displaySequenceBySession;
  const shuffled = [...sessions].reverse().map(item => ({ ...item, pinned: item.session_id.endsWith("old") }));
  const after = buildConversationSessionTree(shuffled, relations).displaySequenceBySession;
  for (const [id, number] of before) assert.equal(after.get(id), number);
  const chronology = buildConversationSessionTree([
    { ...session("earlier", 900), created_at: "2026-07-28T01:00:00Z" },
    { ...session("later", 2), created_at: "2026-07-28T02:00:00Z" },
  ], []).displaySequenceBySession;
  assert.equal(chronology.get("earlier"), 1);
  assert.equal(chronology.get("later"), 2);
});

test("deleting a parent uses the same nearest visible ancestor grouping as the tree", () => {
  const { sessions, relations, add } = groupedFixture();
  add("promoted-child", "child-old", 120, "child");
  const remaining = sessions.filter(item => item.session_id !== "child-old");
  const deletedRelations = relations.map(item => item.session_id === "child-old"
    ? { ...item, deleted_at: "2026-10-30T00:00:00Z" } : item);
  const tree = buildConversationSessionTree(remaining, deletedRelations);
  assert.equal(tree.parentSessionIdBySession.get("promoted-child"), "old-root");
  assert.equal(tree.displaySequenceBySession.get("child-new"), 1);
  assert.equal(tree.displaySequenceBySession.get("promoted-child"), 2);
  assert.equal(tree.displaySequenceBySession.get("deep-compaction"), 1);
});

test("overview rows and chat title share the local number while API session data retains its original number", () => {
  const { sessions, relations } = groupedFixture();
  const tree = buildProjectOverviewSessionTree([...sessions].reverse(), relations);
  const root = sessions.find(item => item.session_id === "new-root");
  const title = renderToStaticMarkup(createElement(SessionDisplayTitle, {
    session: root, displaySequence: tree.displaySequenceBySession.get(root.session_id),
  }));
  assert.match(title, /session-title-index">2<\/span>/);
  assert.doesNotMatch(title, />115</);
  const rows = renderToStaticMarkup(createElement(ProjectOverviewSessionTreeList, {
    tree, activeSessionId: null, renamingSessionId: null,
  }));
  assert.deepEqual([...rows.matchAll(/session-sequence">(\d+)<\/span>/g)].map(match => Number(match[1])), [2, 1]);
  assert.equal(root.sequence_number, 115);
  const pending = renderToStaticMarkup(createElement(SessionDisplayTitle, { session: root, displaySequence: null }));
  assert.doesNotMatch(pending, /session-title-index/);
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
