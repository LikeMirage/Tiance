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
const { resolveMessageVariantNavigation } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/conversationMessageVariants.ts",
);
const { buildConversationForkDraft } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/conversationForkDraft.ts",
);
const { resolveUserMessageContent } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/userMessageReferences.ts",
);
const { resolveViewportTurnNumber } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/useMessageNavigatorActiveTurn.ts",
);
const { resolveSessionScrollMode } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/useBodyAutoScroll.ts",
);
const {
  buildConversationBranchNodeInsights,
  getConversationBranchPoints,
  layoutConversationBranchGraph,
  resolveConversationBranchTarget,
} = await vite.ssrLoadModule(
  "/src/features/conversation-branch-dashboard/model/conversationBranchLayout.ts",
);
const {
  findActiveConversationBranchGroupId,
  shouldAutoRefreshConversationBranchDashboard,
} = await vite.ssrLoadModule(
  "/src/features/conversation-branch-dashboard/model/conversationBranchRefresh.ts",
);
const { buildConversationExportBaseName } = await vite.ssrLoadModule(
  "/src/features/conversation-export/model/conversationExport.ts",
);

after(async () => {
  await vite.close();
});

test("消息版本按稳定来源身份切换，不依赖会话名称", () => {
  const navigation = resolveMessageVariantNavigation(
    message({ originMessageId: "origin-b", variantGroupId: "group-a" }),
    [
      variant(1, "session-a", "message-a", "origin-a"),
      variant(2, "session-b", "message-b", "origin-b"),
      variant(3, "session-c", "message-c", "origin-c"),
    ],
    [session("session-a", "任意标题"), session("session-b", "已改名"), session("session-c", "x")],
  );

  assert.equal(navigation.currentPosition, 2);
  assert.equal(navigation.count, 3);
  assert.equal(navigation.previous.sessionId, "session-a");
  assert.equal(navigation.next.sessionId, "session-c");
});

test("已删除分支墓碑不再成为可点击消息版本", () => {
  const deleted = { ...variant(2, "session-b", "message-b", "origin-b"), deleted_at: "now" };
  const navigation = resolveMessageVariantNavigation(
    message({ originMessageId: "origin-a", variantGroupId: "group-a" }),
    [variant(1, "session-a", "message-a", "origin-a"), deleted],
    [session("session-a", "a"), session("session-b", "b")],
  );

  assert.equal(navigation, null);
});

test("中间分支删除后，后代中的同源消息仍可切换到其他版本", () => {
  const deletedCurrent = {
    ...variant(1, "deleted-session", "deleted-message", "origin-a"),
    deleted_at: "now",
  };
  const navigation = resolveMessageVariantNavigation(
    message({ id: "copied-message", originMessageId: "origin-a", variantGroupId: "group-a" }),
    [deletedCurrent, variant(2, "session-b", "message-b", "origin-b")],
    [session("descendant-session", "descendant"), session("session-b", "b")],
    "descendant-session",
  );

  assert.equal(navigation.count, 2);
  assert.equal(navigation.currentPosition, 1);
  assert.equal(navigation.next.sessionId, "session-b");
});

test("编辑引用消息时只把真实用户内容放回输入框", () => {
  const draft = buildConversationForkDraft(message({
    id: "user-1",
    role: "user",
    content: "从这里重新分析\n【用户消息】\n这也是用户正文",
    references: [{ type: "text", reference: {
        id: "text-1",
        content: "引用正文\n【用户消息】\n不会影响结构",
        displayPath: "docs/note.md",
        endLine: 3,
        fileName: "note.md",
        filePath: "docs/note.md",
        projectId: "project-a",
        source: "source",
        startLine: 2,
    } }],
  }));

  assert.equal(draft.draft, "从这里重新分析\n【用户消息】\n这也是用户正文");
  assert.equal(draft.references.length, 1);
  assert.equal(draft.references[0].type, "text");
  assert.equal(draft.references[0].reference.filePath, "docs/note.md");
});

test("复制用户消息直接读取正式正文，不解析中文标记", () => {
  const content = "第一段\n【用户引用内容】\n【用户消息】\n仍然属于正文";
  assert.equal(resolveUserMessageContent(message({ content })), content);
});

test("用户消息已经可见时不再选中顶部残留的上一轮回复", () => {
  const turnNumber = resolveViewportTurnNumber(0, 500, [
    { bottom: 140, isUserMessage: false, top: -120, turnNumber: 1 },
    { bottom: 220, isUserMessage: true, top: 150, turnNumber: 2 },
    { bottom: 620, isUserMessage: false, top: 230, turnNumber: 2 },
  ]);

  assert.equal(turnNumber, 2);
});

test("下一条用户消息只露出边缘时仍保持当前回复所属轮次", () => {
  const turnNumber = resolveViewportTurnNumber(0, 500, [
    { bottom: 492, isUserMessage: false, top: -200, turnNumber: 1 },
    { bottom: 560, isUserMessage: true, top: 492, turnNumber: 2 },
  ]);

  assert.equal(turnNumber, 1);
});

test("阅读长回复且没有用户消息可见时保持回复所属轮次", () => {
  const turnNumber = resolveViewportTurnNumber(0, 500, [
    { bottom: 800, isUserMessage: false, top: -300, turnNumber: 3 },
  ]);

  assert.equal(turnNumber, 3);
});

test("带目标消息的跨会话切换禁止自动滚到底部", () => {
  assert.equal(resolveSessionScrollMode(
    "project-a:session-b",
    "project-a:session-a",
    "project-a:session-b",
  ), "navigate");
});

test("普通会话切换继续自动恢复到底部", () => {
  assert.equal(resolveSessionScrollMode(
    "project-a:session-b",
    "project-a:session-a",
    null,
  ), "restore");
});

test("当前会话普通重渲染保持现有滚动位置", () => {
  assert.equal(resolveSessionScrollMode(
    "project-a:session-a",
    "project-a:session-a",
    null,
  ), "preserve");
});

test("分支图把同一父消息的不同版本排列为并列子节点", () => {
  const graph = layoutConversationBranchGraph(
    [branchTurn("root"), branchTurn("left"), branchTurn("right")],
    [
      { source_node_id: "root", target_node_id: "left" },
      { source_node_id: "root", target_node_id: "right" },
    ],
    "session-left",
    () => undefined,
  );
  const nodes = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));

  assert.equal(graph.nodes.length, 3);
  assert.equal(graph.edges.length, 2);
  assert.ok(nodes.root.position.x < nodes.left.position.x);
  assert.equal(nodes.left.position.x, nodes.right.position.x);
  assert.notEqual(nodes.left.position.y, nodes.right.position.y);
});

test("分支图只高亮当前会话链路上的连接线", () => {
  const root = branchTurn("root");
  root.targets = [
    { session_id: "session-left", message_id: "message-root-left" },
    { session_id: "session-right", message_id: "message-root-right" },
  ];
  const left = branchTurn("left");
  left.targets = [{ session_id: "session-left", message_id: "message-left" }];
  const right = branchTurn("right");
  right.targets = [{ session_id: "session-right", message_id: "message-right" }];
  const graph = layoutConversationBranchGraph(
    [root, left, right],
    [
      { source_node_id: "root", target_node_id: "left" },
      { source_node_id: "root", target_node_id: "right" },
    ],
    "session-left",
    () => undefined,
  );

  assert.equal(graph.edges[0].className, "conversation-branch-edge--active-path");
  assert.equal(graph.edges[1].className, undefined);
});

test("分支卡片导出回调保留节点的精确消息身份", () => {
  const turn = branchTurn("export-target");
  let exportedTurn = null;
  const graph = layoutConversationBranchGraph(
    [turn],
    [],
    "session-export-target",
    () => undefined,
    { onExport: (target) => { exportedTurn = target; } },
  );

  graph.nodes[0].data.onExport(graph.nodes[0].data.turn);
  assert.equal(exportedTurn.node_id, "export-target");
  assert.equal(exportedTurn.targets[0].message_id, "message-export-target");
});

test("节点跳转优先使用当前会话中的同源消息副本", () => {
  const turn = branchTurn("shared");
  turn.targets = [
    { session_id: "session-a", message_id: "message-a" },
    { session_id: "session-b", message_id: "message-b" },
  ];

  assert.deepEqual(resolveConversationBranchTarget(turn, "session-b"), {
    session_id: "session-b",
    message_id: "message-b",
  });
});

test("分叉点导航按消息版本组识别并包含第一条消息的分支", () => {
  const original = branchTurn("original", { variantGroupId: "fork-a", variantIndex: 1 });
  const edited = branchTurn("edited", { variantGroupId: "fork-a", variantIndex: 2 });
  const ordinary = branchTurn("ordinary", { variantGroupId: "single" });
  const points = getConversationBranchPoints([original, ordinary, edited]);

  assert.equal(points.length, 1);
  assert.equal(points[0].id, "fork-a");
  assert.deepEqual(points[0].nodeIds, ["original", "edited"]);
  assert.equal(points[0].preview, "original");
  assert.equal(points[0].variantCount, 2);
});

test("分支卡片统计相对起点层级并去重后续分叉点", () => {
  const turns = [
    branchTurn("root", { variantGroupId: "root" }),
    branchTurn("left", { variantGroupId: "fork-a", variantIndex: 1 }),
    branchTurn("right", { variantGroupId: "fork-a", variantIndex: 2 }),
    branchTurn("tail", { variantGroupId: "tail" }),
    branchTurn("deep-left", { variantGroupId: "fork-b", variantIndex: 1 }),
    branchTurn("deep-right", { variantGroupId: "fork-b", variantIndex: 2 }),
  ];
  const insights = buildConversationBranchNodeInsights(turns, [
    { source_node_id: "root", target_node_id: "left" },
    { source_node_id: "root", target_node_id: "right" },
    { source_node_id: "left", target_node_id: "tail" },
    { source_node_id: "tail", target_node_id: "deep-left" },
    { source_node_id: "tail", target_node_id: "deep-right" },
  ]);

  assert.equal(insights.get("root").depth, 1);
  assert.equal(insights.get("left").depth, 2);
  assert.equal(insights.get("tail").depth, 3);
  assert.equal(insights.get("deep-left").depth, 4);
  assert.deepEqual(
    insights.get("root").downstreamBranchPoints.map((point) => point.id),
    ["fork-a", "fork-b"],
  );
  assert.deepEqual(
    insights.get("left").downstreamBranchPoints.map((point) => point.id),
    ["fork-b"],
  );
});

test("分支看板只响应当前项目的结构和消息变化", () => {
  assert.equal(shouldAutoRefreshConversationBranchDashboard({
    kind: "structure",
    projectId: "project-a",
  }, "project-a"), true);
  assert.equal(shouldAutoRefreshConversationBranchDashboard({
    kind: "content",
    projectId: "project-a",
  }, "project-a"), true);
  assert.equal(shouldAutoRefreshConversationBranchDashboard({
    kind: "selection",
    projectId: "project-a",
  }, "project-a"), false);
  assert.equal(shouldAutoRefreshConversationBranchDashboard({
    kind: "usage",
    projectId: "project-a",
  }, "project-a"), false);
  assert.equal(shouldAutoRefreshConversationBranchDashboard({
    kind: "structure",
    projectId: "project-b",
  }, "project-a"), false);
});

test("会话切换只解析所属分支组，不依赖当前手动选择", () => {
  const groups = [
    { group_id: "group-a", session_ids: ["session-a", "session-a2"] },
    { group_id: "group-b", session_ids: ["session-b"] },
  ];

  assert.equal(findActiveConversationBranchGroupId(groups, "session-a2"), "group-a");
  assert.equal(findActiveConversationBranchGroupId(groups, "session-b"), "group-b");
  assert.equal(findActiveConversationBranchGroupId(groups, "missing"), null);
});

test("导出文件名包含会话名称和安全的本地时间", () => {
  const exportTime = new Date(2026, 6, 13, 9, 8, 7);
  assert.equal(buildConversationExportBaseName({
    initialDirectory: "C:\\project",
    messageId: null,
    projectId: "project-a",
    scope: "conversation",
    sessionId: "session-a",
    sessionTitle: "需求/评审:第一版?",
  }, exportTime), "需求_评审_第一版_2026-07-13_09-08-07");
  assert.equal(buildConversationExportBaseName({
    initialDirectory: "C:\\project",
    messageId: "message-a",
    projectId: "project-a",
    scope: "assistant-message",
    sessionId: "session-a",
    sessionTitle: "新会话",
  }, exportTime), "新会话_2026-07-13_09-08-07");
});

function message(overrides = {}) {
  return {
    id: "message",
    role: "user",
    content: "content",
    thinkingContent: "",
    status: "done",
    usage: null,
    isThinkingExpanded: false,
    thinkingStartedAt: null,
    thinkingFinishedAt: null,
    ...overrides,
  };
}

function variant(index, sessionId, messageId, originMessageId) {
  return {
    variant_group_id: "group-a",
    variant_index: index,
    branch_id: `branch-${index}`,
    session_id: sessionId,
    message_id: messageId,
    origin_message_id: originMessageId,
    created_at: "now",
    deleted_at: null,
  };
}

function session(id, title) {
  return { session_id: id, title };
}

function branchTurn(id, overrides = {}) {
  return {
    node_id: id,
    variant_group_id: overrides.variantGroupId ?? "group",
    variant_index: overrides.variantIndex ?? 1,
    user_preview: id,
    assistant_preview: `${id}-answer`,
    reply_status: "done",
    created_at: "now",
    targets: [{ session_id: `session-${id}`, message_id: `message-${id}` }],
  };
}
