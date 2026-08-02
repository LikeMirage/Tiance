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
  prepareConversationStreamFullReplay,
  prepareConversationStreamResume,
} = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/conversationStreamResume.ts",
);
const { buildChatDisplayMessages } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatDisplayMessages.ts",
);
const { createChatStreamAccumulator } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatStreamAccumulator.ts",
);
const { processSequencedChatStreamEvent } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatStreamEventSequence.ts",
);
const { mergeStreamingRuntimeStatuses } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/conversationRuntimeState.ts",
);

after(async () => {
  await vite.close();
});

test("重连时把已保存的工具轮次整理成一个运行中消息且不重复正文", () => {
  const userMessage = message({
    id: "user-1",
    role: "user",
    content: "写一篇长文",
  });
  const assistantMessage = message({
    id: "assistant-1",
    role: "assistant",
    content: "好的，现在开始写。",
    processItems: [
      { id: "content-1", type: "content", content: "好的，现在开始写。" },
      {
        id: "tool-call-1",
        type: "tool",
        tool: tool({ status: "running", finishedAt: null }),
      },
    ],
    toolCalls: [tool({ status: "running", finishedAt: null })],
  });
  const toolMessage = message({
    id: "tool-result-1",
    role: "tool",
    content: JSON.stringify({
      arguments: { path: "chapter.md" },
      call_id: "call-1",
      ok: true,
      result: { written: true },
      tool: "write_text_file",
    }),
    toolCallId: "call-1",
  });

  const snapshot = prepareConversationStreamResume(
    [userMessage, assistantMessage, toolMessage],
    "fallback-assistant",
    5000,
  );

  assert.equal(snapshot.checkpointMessageId, "tool-result-1");
  assert.equal(snapshot.messages.length, 2);
  assert.equal(snapshot.assistantMessage.content, "");
  assert.deepEqual(
    snapshot.assistantMessage.processItems
      .filter((item) => item.type === "content")
      .map((item) => item.content),
    ["好的，现在开始写。"],
  );
  const resumedTool = snapshot.assistantMessage.processItems.find(
    (item) => item.type === "tool",
  );
  assert.equal(resumedTool.tool.status, "done");
  assert.equal(snapshot.assistantMessage.toolCalls[0].status, "done");
});

test("只有用户消息尚未产生持久化轮次时从流开头恢复", () => {
  const snapshot = prepareConversationStreamResume([
    message({ id: "user-only", role: "user", content: "继续" }),
  ], "assistant-new", 6000);

  assert.equal(snapshot.checkpointMessageId, null);
  assert.equal(snapshot.messages.length, 2);
  assert.equal(snapshot.assistantMessage.id, "assistant-new");
});

test("保存点失效改为完整重放时会丢弃本轮已保存助手片段但保留历史与用户消息", () => {
  const snapshot = prepareConversationStreamFullReplay([
    message({ id: "user-old", role: "user", content: "旧问题" }),
    message({ id: "assistant-old", role: "assistant", content: "旧回答" }),
    message({ id: "user-current", role: "user", content: "当前问题" }),
    message({ id: "assistant-partial", role: "assistant", content: "当前部分回答" }),
  ], "assistant-replay", 6500);

  assert.deepEqual(
    snapshot.messages.map((item) => item.id),
    ["user-old", "assistant-old", "user-current", "assistant-replay"],
  );
  assert.equal(snapshot.assistantMessage.content, "");
  assert.equal(snapshot.checkpointMessageId, null);
});

test("多轮工具结果在跨项目恢复时合并为一个连续助手轮次", () => {
  const messages = [message({ id: "user-multi", role: "user", content: "执行两步" })];
  for (const [index, content] of [[1, "第一步"], [2, "第二步"]]) {
    const callId = `call-${index}`;
    const toolItem = tool({
      id: `tool-${callId}`,
      callId,
      name: `tool_${index}`,
      status: "running",
    });
    messages.push(message({
      id: `assistant-${index}`,
      role: "assistant",
      content,
      processItems: [
        { id: `content-${index}`, type: "content", content },
        { id: toolItem.id, type: "tool", tool: toolItem },
      ],
      toolCalls: [toolItem],
    }));
    messages.push(message({
      id: `tool-result-${index}`,
      role: "tool",
      content: JSON.stringify({
        arguments: {},
        call_id: callId,
        ok: true,
        result: { index },
        tool: `tool_${index}`,
      }),
      toolCallId: callId,
    }));
  }

  const snapshot = prepareConversationStreamResume(
    messages,
    "fallback-multi",
    7000,
  );

  assert.equal(snapshot.messages.length, 2);
  assert.deepEqual(
    snapshot.assistantMessage.processItems
      .filter((item) => item.type === "content")
      .map((item) => item.content),
    ["第一步", "第二步"],
  );
  assert.deepEqual(
    snapshot.assistantMessage.toolCalls.map((item) => item.status),
    ["done", "done"],
  );
});

test("关闭流式显示时工具边界仍会保存前段正文并在结束时补上后段正文", () => {
  let messages = [message({
    id: "assistant-live",
    role: "assistant",
    status: "running",
  })];
  const accumulator = createChatStreamAccumulator({
    assistantId: "assistant-live",
    isSessionPresented: () => false,
    isThinkingStuckToBottom: () => false,
    onUsage: () => undefined,
    scrollThinkingContentToBottom: () => undefined,
    sessionId: "session-a",
    streamProjectId: "project-a",
    streamingEnabled: false,
    updateSessionMessages: (projectId, sessionId, updater) => {
      assert.equal(projectId, "project-a");
      assert.equal(sessionId, "session-a");
      messages = updater(messages);
    },
  });

  accumulator.handleEvent({ kind: "delta", content: "工具前正文" });
  assert.equal(messages[0].content, "");

  accumulator.handleEvent({
    kind: "tool_call",
    tool_call: {
      call_id: "call-live",
      name: "write_text_file",
      arguments: "{}",
    },
  });
  assert.deepEqual(
    messages[0].processItems
      .filter((item) => item.type === "content")
      .map((item) => item.content),
    ["工具前正文"],
  );
  assert.equal(messages[0].toolCalls[0].status, "running");

  accumulator.handleEvent({
    kind: "tool_result",
    tool_result: {
      call_id: "call-live",
      name: "write_text_file",
      arguments: "{}",
      ok: true,
      content: "完成",
    },
  });
  assert.equal(messages[0].toolCalls[0].status, "done");

  accumulator.handleEvent({ kind: "delta", content: "工具后正文" });
  assert.equal(messages[0].content, "");
  accumulator.flushNow();
  assert.equal(messages[0].content, "工具后正文");
});

test("运行中的已保存工具轮次不会因为普通 done 消息被误判失败", () => {
  const runningTool = tool({ status: "running", finishedAt: null });
  const displayMessages = buildChatDisplayMessages([
    message({
      id: "assistant-tool-round",
      content: "准备调用工具",
      processItems: [
        { id: "content-tool-round", type: "content", content: "准备调用工具" },
        { id: runningTool.id, type: "tool", tool: runningTool },
      ],
      toolCalls: [runningTool],
    }),
    message({
      id: "assistant-next-round",
      content: "继续处理",
    }),
  ], { runtimeStatus: "running" });

  assert.equal(displayMessages.length, 1);
  assert.equal(displayMessages[0].toolCalls[0].status, "running");
});

test("会话已停止时没有结果的工具调用显示为已取消而不是永久调用中", () => {
  const runningTool = tool({ status: "running", finishedAt: null });
  const displayMessages = buildChatDisplayMessages([
    message({
      id: "assistant-cancelled-tool",
      content: "准备调用工具",
      processItems: [
        { id: "content-cancelled-tool", type: "content", content: "准备调用工具" },
        { id: runningTool.id, type: "tool", tool: runningTool },
      ],
      toolCalls: [runningTool],
    }),
  ], { runtimeStatus: "idle" });

  assert.equal(displayMessages[0].toolCalls[0].status, "cancelled");
  assert.equal(
    displayMessages[0].processItems.find((item) => item.type === "tool").tool.status,
    "cancelled",
  );
});

test("空正文的取消终态会合并同一回合的工具过程并保留用量", () => {
  const runningTool = tool({ status: "running", finishedAt: null });
  const usage = {
    prompt_tokens: 120,
    completion_tokens: 8,
    total_tokens: 128,
  };
  const displayMessages = buildChatDisplayMessages([
    message({
      id: "assistant-tool-round",
      content: "",
      processItems: [
        {
          id: "thinking-tool-round",
          type: "thinking",
          content: "准备执行工具。",
          status: "done",
          startedAt: 1000,
          finishedAt: 1500,
        },
        { id: runningTool.id, type: "tool", tool: runningTool },
      ],
      toolCalls: [runningTool],
    }),
    message({
      id: "assistant-cancelled-terminal",
      content: "",
      status: "cancelled",
      usage,
      createdAt: 3000,
      updatedAt: 3000,
    }),
  ], { runtimeStatus: "idle" });

  assert.equal(displayMessages.length, 1);
  assert.equal(displayMessages[0].id, "assistant-cancelled-terminal");
  assert.equal(displayMessages[0].status, "cancelled");
  assert.deepEqual(displayMessages[0].usage, usage);
  assert.equal(displayMessages[0].toolCalls[0].status, "cancelled");
  assert.equal(
    displayMessages[0].processItems.find((item) => item.type === "tool").tool.status,
    "cancelled",
  );
});

test("下一条用户消息已开始时会合并前一轮没有独立取消终态的工具过程", () => {
  const firstTool = tool({
    id: "tool-first-closed-turn",
    callId: "call-first-closed-turn",
    name: "wait",
    status: "done",
    finishedAt: 2000,
  });
  const secondTool = tool({
    id: "tool-second-closed-turn",
    callId: "call-second-closed-turn",
    name: "list_sessions",
    status: "done",
    finishedAt: 3000,
  });
  const displayMessages = buildChatDisplayMessages([
    message({ id: "user-closed-turn", role: "user", content: "并发处理" }),
    message({
      id: "assistant-first-closed-turn",
      content: "开始并发处理。",
      processItems: [
        {
          id: "thinking-first-closed-turn",
          type: "thinking",
          content: "准备并发任务。",
          status: "done",
          startedAt: 1000,
          finishedAt: 1500,
        },
        { id: firstTool.id, type: "tool", tool: firstTool },
      ],
      toolCalls: [firstTool],
    }),
    message({
      id: "assistant-second-closed-turn",
      content: "",
      processItems: [{ id: secondTool.id, type: "tool", tool: secondTool }],
      toolCalls: [secondTool],
    }),
    message({
      id: "assistant-empty-closed-turn",
      content: "",
      processItems: [],
      toolCalls: [],
    }),
    message({ id: "user-next-turn", role: "user", content: "检查已有状态" }),
  ], { runtimeStatus: "running" });

  assert.equal(displayMessages.length, 3);
  assert.deepEqual(
    displayMessages.map((item) => item.id),
    ["user-closed-turn", "assistant-empty-closed-turn", "user-next-turn"],
  );
  assert.deepEqual(
    displayMessages[1].toolCalls.map((item) => item.id),
    [firstTool.id, secondTool.id],
  );
});

test("流式错误会立即结束仍在运行的工具计时", () => {
  let messages = [message({
    id: "assistant-error-tool",
    status: "running",
  })];
  const accumulator = createChatStreamAccumulator({
    assistantId: "assistant-error-tool",
    isSessionPresented: () => false,
    isThinkingStuckToBottom: () => false,
    onUsage: () => undefined,
    scrollThinkingContentToBottom: () => undefined,
    sessionId: "session-error",
    streamProjectId: "project-error",
    streamingEnabled: true,
    updateSessionMessages: (_projectId, _sessionId, updater) => {
      messages = updater(messages);
    },
  });

  accumulator.handleEvent({
    kind: "tool_call",
    tool_call: {
      call_id: "call-error",
      name: "write_text_file",
      arguments: "{}",
    },
  });
  accumulator.handleEvent({ kind: "error", error: "工具执行中断" });

  assert.equal(messages[0].toolCalls[0].status, "error");
  assert.notEqual(messages[0].toolCalls[0].finishedAt, null);
});

test("主动暂停会结束思考和工具计时并保留已取得的统计", () => {
  let messages = [message({
    id: "assistant-cancelled",
    status: "running",
    isThinkingExpanded: true,
    thinkingStartedAt: 1000,
  })];
  const accumulator = createChatStreamAccumulator({
    assistantId: "assistant-cancelled",
    isSessionPresented: () => false,
    isThinkingStuckToBottom: () => false,
    onUsage: () => undefined,
    scrollThinkingContentToBottom: () => undefined,
    sessionId: "session-cancelled",
    streamProjectId: "project-cancelled",
    streamingEnabled: false,
    updateSessionMessages: (_projectId, _sessionId, updater) => {
      messages = updater(messages);
    },
  });

  accumulator.handleEvent({ kind: "thinking_delta", content: "正在分析" });
  accumulator.handleEvent({
    kind: "tool_call",
    tool_call: {
      call_id: "call-cancelled",
      name: "read_file",
      arguments: "{}",
    },
  });
  accumulator.handleEvent({
    kind: "usage",
    usage: {
      prompt_tokens: 120,
      completion_tokens: 8,
      total_tokens: 128,
    },
  });
  accumulator.finalizeCancelled();

  assert.equal(messages[0].status, "cancelled");
  assert.equal(messages[0].isThinkingExpanded, false);
  assert.notEqual(messages[0].thinkingFinishedAt, null);
  assert.equal(messages[0].processItems[0].status, "done");
  assert.equal(messages[0].toolCalls[0].status, "cancelled");
  assert.notEqual(messages[0].toolCalls[0].finishedAt, null);
  assert.equal(messages[0].usage.total_tokens, 128);
});

test("流事件序号按项目和会话隔离并忽略同一会话的重复事件", async () => {
  const state = {
    claimed: { current: new Set() },
    processed: { current: new Map() },
    queues: { current: new Map() },
  };
  const processed = [];
  const apply = (sessionKey, sequence) => processSequencedChatStreamEvent(
    sessionKey,
    { kind: "delta", content: sessionKey, run_sequence: sequence },
    state,
    () => processed.push(`${sessionKey}:${sequence}`),
  );

  await apply("project-a:session-1", 1);
  await apply("project-a:session-1", 1);
  await apply("project-a:session-2", 1);
  await apply("project-b:session-1", 1);

  assert.deepEqual(processed, [
    "project-a:session-1:1",
    "project-a:session-2:1",
    "project-b:session-1:1",
  ]);
});

test("会话列表刷新保护同项目所有流式会话且不串到其它项目", () => {
  const responseStates = {
    "session-a": sessionState("idle"),
    "session-b": sessionState("running"),
  };
  const previousStates = {
    "session-a": sessionState("running"),
    "session-b": sessionState("idle"),
  };

  const merged = mergeStreamingRuntimeStatuses(
    "project-a",
    responseStates,
    previousStates,
    new Set([
      "project-a:session-a",
      "project-b:session-b",
    ]),
  );

  assert.equal(merged["session-a"].runtime_status, "running");
  assert.equal(merged["session-b"].runtime_status, "running");
});

function message(overrides) {
  return {
    id: "message",
    role: "assistant",
    content: "",
    thinkingContent: "",
    status: "done",
    usage: null,
    isThinkingExpanded: false,
    thinkingStartedAt: null,
    thinkingFinishedAt: null,
    processItems: [],
    toolCalls: [],
    createdAt: 1000,
    updatedAt: 1000,
    ...overrides,
  };
}

function tool(overrides) {
  return {
    id: "tool-call-1",
    callId: "call-1",
    name: "write_text_file",
    arguments: JSON.stringify({ path: "chapter.md" }),
    result: "",
    error: "",
    ok: null,
    status: "running",
    startedAt: 2000,
    finishedAt: null,
    ...overrides,
  };
}

function sessionState(runtimeStatus) {
  return {
    runtime_status: runtimeStatus,
    draft: "",
    references: [],
    updated_at: "2026-07-10T00:00:00Z",
  };
}
