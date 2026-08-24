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
  serializeConversationTurns,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationMessageTurns.ts",
);
const {
  collectRecentCompletedConversationTurns,
  parseConversationMessageTurn,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/loadConversationMessageTurns.ts",
);
const { ConversationBackgroundRunRegistry } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationBackgroundRun.ts",
);
const { followConversationRun } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationRunFollower.ts",
);

after(async () => {
  await vite.close();
});

test("纯正文视图只保留用户正文和最终回复，完整视图保留工具链", async () => {
  const messages = buildToolTurn("turn", 3);
  const loader = createBackwardPageLoader(messages, 80);
  const { turns } = await collectRecentCompletedConversationTurns(loader.load, 1);

  assert.equal(turns.length, 1);
  assert.deepEqual(
    serializeConversationTurns(turns, "content_only")[0],
    {
      user: { message_id: "turn-user", role: "user", content: "问题 turn" },
      reply: { message_id: "turn-final", role: "assistant", content: "回答 turn" },
    },
  );
  assert.equal(serializeConversationTurns(turns, "full")[0].messages.length, 6);
});

test("完成轮次分页会跨过远超 100 条的工具消息，不形成静默总上限", async () => {
  const messages = [
    ...buildToolTurn("old", 2),
    ...buildToolTurn("large", 450),
  ];
  const loader = createBackwardPageLoader(messages, 80);

  const result = await collectRecentCompletedConversationTurns(loader.load, 1);

  assert.equal(result.turns[0].user.message_id, "large-user");
  assert.equal(result.turns[0].reply.message_id, "large-final");
  assert.ok(result.loadedMessageCount > 400);
  assert.ok(loader.callCount() > 5);
});

test("分页重复页面即使能凑够轮次深度也会明确失败", async () => {
  const repeatedPage = pageResponse({
    hasMore: true,
    items: buildToolTurn("repeat", 1),
  });
  let calls = 0;

  await assert.rejects(
    collectRecentCompletedConversationTurns(async () => {
      calls += 1;
      return repeatedPage;
    }, 2),
    /重复页面/,
  );
  assert.equal(calls, 2);
});

test("分页重复游标不会被下一页内容掩盖", async () => {
  const firstItems = [
    message({ id: "cursor-a", role: "assistant" }),
    message({ id: "latest", role: "assistant" }),
  ];
  const secondItems = [
    message({ id: "cursor-a", role: "user" }),
    message({ id: "different", role: "assistant" }),
  ];
  const pages = [
    pageResponse({ hasMore: true, items: firstItems }),
    pageResponse({ hasMore: true, items: secondItems }),
  ];

  await assert.rejects(
    collectRecentCompletedConversationTurns(async () => pages.shift(), 1),
    /重复游标/,
  );
});

test("精确轮次响应不能混入下一轮用户消息", () => {
  const items = [
    message({ id: "target-user", role: "user" }),
    message({ id: "target-reply", role: "assistant" }),
    message({ id: "next-user", role: "user" }),
  ];

  assert.throws(
    () => parseConversationMessageTurn(
      turnResponse("target-user", items),
      expectedTurnIdentity("target-user"),
    ),
    /下一轮用户消息/,
  );
});

test("精确轮次响应必须属于请求指定的项目、会话和用户消息", () => {
  const items = [message({ id: "target-user", role: "user" })];
  const response = turnResponse("target-user", items);
  response.session_id = "different-session";

  assert.throws(
    () => parseConversationMessageTurn(response, expectedTurnIdentity("target-user")),
    /会话身份不一致/,
  );
});

test("按 user_message_id 返回的精确轮次可收齐远超 100 条消息", () => {
  const targetTurn = buildToolTurn("target", 260);
  const turn = parseConversationMessageTurn(
    turnResponse("target-user", targetTurn),
    expectedTurnIdentity("target-user"),
  );

  assert.equal(turn.messages.length, targetTurn.length);
  assert.equal(turn.messages[0].message_id, "target-user");
  assert.equal(turn.messages.at(-1).message_id, "target-final");
  assert.equal(turn.reply.message_id, "target-final");
});

test("精确轮次响应的一万条工具消息没有隐式总上限", () => {
  const targetTurn = buildToolTurn("ten-thousand", 10_000);
  const turn = parseConversationMessageTurn(
    turnResponse("ten-thousand-user", targetTurn),
    expectedTurnIdentity("ten-thousand-user"),
  );

  assert.equal(turn.messages.length, targetTurn.length);
  assert.equal(turn.reply.message_id, "ten-thousand-final");
});

test("精确轮次读取保留 cancelled 终态，运行中回复则为 null", () => {
  const cancelled = [
    message({ id: "cancel-user", role: "user" }),
    message({ id: "cancel-reply", role: "assistant", status: "cancelled" }),
  ];
  const cancelledTurn = parseConversationMessageTurn(
    turnResponse("cancel-user", cancelled),
    expectedTurnIdentity("cancel-user"),
  );
  assert.equal(cancelledTurn.reply.status, "cancelled");

  const running = [
    message({ id: "running-user", role: "user" }),
    message({ id: "running-reply", role: "assistant", status: "running" }),
  ];
  const runningTurn = parseConversationMessageTurn(
    turnResponse("running-user", running),
    expectedTurnIdentity("running-user"),
  );
  assert.equal(runningTurn.reply, null);
});

test("不等待模式先返回 started，注册表按稳定消息 ID 复用同一运行", async () => {
  let releaseStream;
  const streamGate = new Promise((resolve) => {
    releaseStream = resolve;
  });
  let onStartedCalled = false;
  const persistedTurn = {
    user: message({ id: "new-user", role: "user", content: "执行" }),
    reply: message({ id: "new-reply", role: "assistant", content: "完成" }),
  };
  persistedTurn.messages = [persistedTurn.user, persistedTurn.reply];
  const registry = new ConversationBackgroundRunRegistry({
    followRun: async (input) => {
      await input.onStarted();
      await streamGate;
      return {
        userMessageId: "new-user",
        assistantMessageId: "new-reply",
        outcome: "done",
      };
    },
    loadTurn: async () => persistedTurn,
  });
  const session = conversationSession();
  const run = registry.startOrResume({
    clientCapabilities: () => [],
    clientToolExecutor: () => null,
    message: "执行",
    projectId: "project-a",
    session,
    userMessageId: "new-user",
    onStarted: () => {
      onStartedCalled = true;
    },
  });

  const started = await run.started;
  assert.equal(started.userMessageId, "new-user");
  assert.equal(started.running, true);
  assert.equal(onStartedCalled, true);
  assert.equal(registry.hasActiveRun("project-a", session.session_id), true);
  const repeatedRun = registry.startOrResume({
    clientCapabilities: () => [],
    clientToolExecutor: () => null,
    message: "执行",
    projectId: "project-a",
    session,
    userMessageId: "new-user",
  });
  assert.equal(repeatedRun, run);
  releaseStream();
  const result = await run.completion;
  await Promise.resolve();
  assert.equal(result.turn.reply.message_id, "new-reply");
  assert.equal(result.outcome, "done");
  assert.equal(registry.hasActiveRun("project-a", session.session_id), false);
});

test("首次 SSE 断开后续接同一运行并继续处理后续事件", async () => {
  const seenEvents = [];
  let startedCount = 0;
  const settlement = await followConversationRun({
    expectedUserMessageId: "run-user",
    request: {
      provider_id: "provider-a",
      model_id: "model-a",
      project_id: "project-a",
      session_id: "session-a",
      messages: [{ role: "user", content: "执行", message_id: "run-user" }],
    },
    onStarted: () => {
      startedCount += 1;
    },
    onEvent: (event) => {
      seenEvents.push(event.kind);
    },
  }, {
    stream: async (_request, handlers) => {
      handlers.onOpen?.();
      await handlers.onEvent({
        kind: "conversation_run_started",
        user_message_id: "run-user",
      });
      throw new TypeError("network disconnected");
    },
    resume: async (_projectId, _sessionId, onEvent) => {
      await onEvent({
        kind: "client_tool_request",
        client_tool_request: {
          request_id: "tool-request",
          call_id: "call-a",
          name: "read",
          arguments: "{}",
        },
      });
      await onEvent({
        kind: "conversation_run_settled",
        user_message_id: "run-user",
        assistant_message_id: "run-reply",
        status: "done",
      });
    },
    retryDelay: async () => undefined,
  });

  assert.equal(startedCount, 1);
  assert.deepEqual(seenEvents, ["client_tool_request"]);
  assert.deepEqual(settlement, {
    userMessageId: "run-user",
    assistantMessageId: "run-reply",
    outcome: "done",
  });
});

test("流终态标识与持久化回复不一致时明确失败", async () => {
  const turn = {
    user: message({ id: "exact-user", role: "user" }),
    reply: message({ id: "persisted-reply", role: "assistant" }),
  };
  turn.messages = [turn.user, turn.reply];
  const registry = new ConversationBackgroundRunRegistry({
    followRun: async (input) => {
      await input.onStarted();
      return {
        userMessageId: "exact-user",
        assistantMessageId: "different-reply",
        outcome: "done",
      };
    },
    loadTurn: async () => turn,
  });
  const run = registry.startOrResume({
    clientCapabilities: () => [],
    clientToolExecutor: () => null,
    message: "执行",
    projectId: "project-a",
    session: conversationSession(),
    userMessageId: "exact-user",
  });

  await run.started;
  await assert.rejects(run.completion, /身份不一致/);
});

function buildToolTurn(id, toolCount) {
  return [
    message({ id: `${id}-user`, role: "user", content: `问题 ${id}` }),
    message({
      id: `${id}-tool-call`,
      role: "assistant",
      content: "",
      tool_calls: [{ call_id: `${id}-call`, name: "read", arguments: "{}" }],
    }),
    ...Array.from({ length: toolCount }, (_, index) => message({
      id: `${id}-tool-${index}`,
      role: "tool",
      content: `结果 ${index}`,
    })),
    message({ id: `${id}-final`, role: "assistant", content: `回答 ${id}` }),
  ];
}

function createBackwardPageLoader(messages, pageSize) {
  let calls = 0;
  return {
    callCount: () => calls,
    load: async (beforeMessageId) => {
      calls += 1;
      const end = beforeMessageId
        ? messages.findIndex((item) => item.message_id === beforeMessageId)
        : messages.length;
      assert.notEqual(end, -1);
      const start = Math.max(0, end - pageSize);
      const items = messages.slice(start, end);
      return {
        project_id: "project-a",
        session_id: "session-a",
        count: items.length,
        total_count: messages.length,
        has_more: start > 0,
        next_before_message_id: start > 0 ? items[0].message_id : null,
        items,
      };
    },
  };
}

function pageResponse({ hasMore, items }) {
  return {
    project_id: "project-a",
    session_id: "session-a",
    count: items.length,
    total_count: 1000,
    has_more: hasMore,
    next_before_message_id: hasMore ? items[0].message_id : null,
    items,
  };
}

function turnResponse(userMessageId, items) {
  return {
    project_id: "project-a",
    session_id: "session-a",
    user_message_id: userMessageId,
    count: items.length,
    items,
  };
}

function expectedTurnIdentity(userMessageId) {
  return {
    projectId: "project-a",
    sessionId: "session-a",
    userMessageId,
  };
}

function message(overrides) {
  return {
    message_id: overrides.id,
    session_id: "session-a",
    role: overrides.role,
    content: overrides.content ?? "",
    provider_id: null,
    model_id: null,
    status: "done",
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    origin_message_id: overrides.id,
    ...overrides,
  };
}

function conversationSession() {
  return {
    session_id: "session-a",
    sequence_number: 1,
    title: "测试会话",
    provider_id: "provider-a",
    model_id: "model-a",
    reasoning_mode: "off",
    manual_title: false,
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    message_count: 10,
    settings: {
      global_memory_enabled: true,
      memory_context_token_trigger_threshold: 250000,
      memory_compression_enabled: true,
      memory_raw_context_token_reserve: 30000,
      project_memory_enabled: true,
      return_cancelled_messages: false,
      return_user_before_cancelled: false,
      streaming_enabled: true,
      auto_collapse_assistant_process: true,
      inject_message_timestamps: true,
      system_prompt: "",
      max_output_tokens: 32768,
      temperature: null,
      top_p: null,
      enabled_tool_names: null,
      max_tool_calls: 99999,
      tool_approval_mode: "auto_allow_ask",
    },
  };
}
