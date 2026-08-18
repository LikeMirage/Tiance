import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import {
  clientToolRequest,
  completedTurn,
  conversationMessage,
  conversationHistoryLocator,
  installClientToolTestGlobals,
  installSessionListFetch,
} from "./helpers/conversationClientToolRegistrationFixtures.mjs";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const {
  createConversationInteractionClientToolRegistration,
} = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationInteractionClientTool.ts",
);
const { ConversationBackgroundRunRegistry } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationBackgroundRun.ts",
);
const { followConversationRun } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/conversationRunFollower.ts",
);
const { HttpRequestError } = await vite.ssrLoadModule(
  "/src/services/http/httpClient.ts",
);
let restoreGlobals;

before(() => {
  restoreGlobals = installClientToolTestGlobals();
});

after(async () => {
  restoreGlobals();
  await vite.close();
});

test("不等待模式只在消息持久化 started 后返回", async () => {
  const events = [];
  let startInput = null;
  installSessionListFetch();
  const backgroundRuns = {
    hasActiveRun: () => false,
    startOrResume: (input) => {
      startInput = input;
      return {
        started: Promise.resolve().then(async () => {
          events.push("started");
          await input.onStarted?.();
          return { running: true, userMessageId: input.userMessageId };
        }),
        completion: new Promise(() => undefined),
      };
    },
  };
  const registration = createInteractionRegistration(backgroundRuns, {
    onSessionRuntimeStatusChanged: (_projectId, _sessionId, status) => {
      events.push(`status:${status}`);
    },
  });

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-no-wait",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "后台执行",
      wait_for_reply: false,
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(startInput.userMessageId, "client_request-no-wait");
  assert.equal(
    startInput.message,
    "后台执行\n\n本条消息来源会话名称：来源会话\n本条消息来源会话 ID：caller-session",
  );
  assert.equal(result.content.accepted, true);
  assert.equal(result.content.runtime_status, "running");
  assert.equal(result.content.outcome, "still_running");
  assert.equal(result.content.user_message_id, "client_request-no-wait");
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
  assert.deepEqual(events.slice(0, 2), ["started", "status:running"]);
});

test("等待模式返回本次精确完成回复", async () => {
  installSessionListFetch();
  const resultTurn = completedTurn({
    outcome: "done",
    reply: conversationMessage("assistant-result", "assistant", "精确回复"),
    userMessageId: "client_request-wait",
  });
  const registration = createInteractionRegistration(settledBackgroundRuns(resultTurn));

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-wait",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "等待回复",
      wait_for_reply: true,
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(result.content.outcome, "done");
  assert.equal(result.content.runtime_status, "idle");
  assert.equal(result.content.user_message_id, "client_request-wait");
  assert.equal(result.content.assistant_message_id, "assistant-result");
  assert.equal(result.content.reply.content, "精确回复");
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
});

test("前端刷新后等待模式按稳定消息身份续接自己的运行", async () => {
  installSessionListFetch({ runtimeStatus: "running" });
  const persisted = completedTurn({
    outcome: "done",
    reply: conversationMessage("assistant-resumed", "assistant", "续接完成"),
    userMessageId: "client_request-resumed",
  });
  let resumeCalls = 0;
  let streamCalls = 0;
  const backgroundRuns = new ConversationBackgroundRunRegistry({
    followRun: (input) => followConversationRun(input, {
      resume: async (_projectId, _sessionId, onEvent) => {
        resumeCalls += 1;
        await onEvent({
          kind: "conversation_run_started",
          user_message_id: "client_request-resumed",
        });
        await onEvent({
          kind: "conversation_run_settled",
          user_message_id: "client_request-resumed",
          assistant_message_id: "assistant-resumed",
          status: "done",
        });
      },
      retryDelay: async () => undefined,
      stream: async () => {
        streamCalls += 1;
      },
    }),
    loadTurn: async () => persisted.turn,
  });
  const registration = createInteractionRegistration(backgroundRuns);

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-resumed",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "刷新前已经发出的消息",
      wait_for_reply: true,
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(result.content.outcome, "done");
  assert.equal(result.content.user_message_id, "client_request-resumed");
  assert.equal(result.content.reply.content, "续接完成");
  assert.equal(resumeCalls, 1);
  assert.equal(streamCalls, 0);
});

test("刷新续接到他人运行时明确拒绝且不执行他人事件", async () => {
  installSessionListFetch({ runtimeStatus: "running" });
  let clientToolCalls = 0;
  let streamCalls = 0;
  const backgroundRuns = new ConversationBackgroundRunRegistry({
    followRun: (input) => followConversationRun(input, {
      resume: async (_projectId, _sessionId, onEvent) => {
        for (const event of [
          {
            kind: "conversation_run_started",
            user_message_id: "someone-elses-user-message",
          },
          {
            kind: "client_tool_request",
            client_tool_request: {
              request_id: "other-tool-request",
              call_id: "other-call",
              name: "other-tool",
              arguments: "{}",
            },
          },
        ]) {
          await onEvent(event);
        }
      },
      retryDelay: async () => undefined,
      stream: async () => {
        streamCalls += 1;
      },
    }),
    loadTurn: async () => {
      throw new Error("身份冲突时不应读取本次轮次。");
    },
  });
  const registration = createInteractionRegistration(backgroundRuns, {
    getClientToolExecutor: () => async () => {
      clientToolCalls += 1;
      return { ok: true };
    },
  });

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-conflict",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "不能串到他人的运行",
      wait_for_reply: true,
    },
  }));

  assert.equal(result.ok, false);
  assert.match(result.error, /另一轮会话运行/);
  assert.equal(clientToolCalls, 0);
  assert.equal(streamCalls, 0);
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
});

test("刷新时运行刚结束只在 resume 404 后用同一消息 ID 幂等重放", async () => {
  installSessionListFetch({ runtimeStatus: "running" });
  const persisted = completedTurn({
    outcome: "done",
    reply: conversationMessage("assistant-replayed", "assistant", "幂等结果"),
    userMessageId: "client_request-replayed",
  });
  let resumeCalls = 0;
  let streamedRequest = null;
  const backgroundRuns = new ConversationBackgroundRunRegistry({
    followRun: (input) => followConversationRun(input, {
      resume: async () => {
        resumeCalls += 1;
        throw new HttpRequestError("当前会话没有正在运行的生成任务。", 404);
      },
      retryDelay: async () => undefined,
      stream: async (request, handlers) => {
        streamedRequest = request;
        handlers.onOpen?.();
        await handlers.onEvent({
          kind: "conversation_run_started",
          user_message_id: "client_request-replayed",
        });
        await handlers.onEvent({
          kind: "conversation_run_settled",
          user_message_id: "client_request-replayed",
          assistant_message_id: "assistant-replayed",
          status: "done",
        });
      },
    }),
    loadTurn: async () => persisted.turn,
  });
  const registration = createInteractionRegistration(backgroundRuns);

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-replayed",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "刷新前已经完成的消息",
      wait_for_reply: true,
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(result.content.outcome, "done");
  assert.equal(resumeCalls, 1);
  assert.equal(streamedRequest.messages.at(-1).message_id, "client_request-replayed");
  assert.equal(result.content.user_message_id, "client_request-replayed");
  assert.equal(result.content.reply.content, "幂等结果");
});

test("会话列表状态短暂落后时用 409 后的精确续接消除启动竞争", async () => {
  installSessionListFetch();
  const persisted = completedTurn({
    outcome: "done",
    reply: conversationMessage("assistant-raced", "assistant", "竞争后续接"),
    userMessageId: "client_request-raced",
  });
  let resumeCalls = 0;
  let streamCalls = 0;
  const backgroundRuns = new ConversationBackgroundRunRegistry({
    followRun: (input) => followConversationRun(input, {
      resume: async (_projectId, _sessionId, onEvent) => {
        resumeCalls += 1;
        await onEvent({
          kind: "conversation_run_started",
          user_message_id: "client_request-raced",
        });
        await onEvent({
          kind: "conversation_run_settled",
          user_message_id: "client_request-raced",
          assistant_message_id: "assistant-raced",
          status: "done",
        });
      },
      retryDelay: async () => undefined,
      stream: async () => {
        streamCalls += 1;
        throw new HttpRequestError("当前会话已有生成任务正在运行。", 409);
      },
    }),
    loadTurn: async () => persisted.turn,
  });
  const registration = createInteractionRegistration(backgroundRuns);

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-raced",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "列表刷新与启动之间发生竞争",
      wait_for_reply: true,
    },
  }));

  assert.equal(result.ok, true);
  assert.equal(result.content.outcome, "done");
  assert.equal(streamCalls, 1);
  assert.equal(resumeCalls, 1);
  assert.equal(result.content.user_message_id, "client_request-raced");
});

test("等待模式区分模型错误与无正文取消终态", async () => {
  for (const scenario of terminalScenarios()) {
    installSessionListFetch();
    const registration = createInteractionRegistration(
      settledBackgroundRuns(scenario.result),
    );
    const result = await registration.execute(clientToolRequest({
      name: "interact_ai_conversation",
      requestId: scenario.requestId,
      arguments: {
        action: "send",
        session_id: "session-a",
        message: "检查终态",
        wait_for_reply: true,
      },
    }));

    assert.equal(result.ok, true);
    assert.equal(result.content.outcome, scenario.result.outcome);
    assert.equal(result.content.runtime_status, scenario.expectedRuntimeStatus);
    assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
    if (scenario.expectedReplyRole) {
      assert.equal(result.content.reply.role, scenario.expectedReplyRole);
    } else {
      assert.equal("reply" in result.content, false);
      assert.equal("assistant_message_id" in result.content, false);
    }
  }
});

test("发送启动竞争失败保留路径且不伪造运行终态", async () => {
  installSessionListFetch();
  const backgroundRuns = {
    hasActiveRun: () => false,
    startOrResume: () => {
      throw new Error("目标会话刚被另一请求占用。");
    },
  };
  const runtimeStatuses = [];
  const registration = createInteractionRegistration(backgroundRuns, {
    onSessionRuntimeStatusChanged: (_projectId, _sessionId, status) => {
      runtimeStatuses.push(status);
    },
  });

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "竞争发送",
    },
  }));

  assert.equal(result.ok, false);
  assert.match(result.error, /另一请求占用/);
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
  assert.deepEqual(runtimeStatuses, []);
});

test("started 后跟随失败只刷新真实状态，不伪造 error", async () => {
  installSessionListFetch();
  const backgroundRuns = new ConversationBackgroundRunRegistry({
    followRun: async (input) => {
      await input.onStarted();
      throw new Error("运行跟随失败。");
    },
    loadTurn: async () => {
      throw new Error("失败运行不应读取完成轮次。");
    },
  });
  const runtimeStatuses = [];
  const registration = createInteractionRegistration(backgroundRuns, {
    onSessionRuntimeStatusChanged: (_projectId, _sessionId, status) => {
      runtimeStatuses.push(status);
    },
  });

  const result = await registration.execute(clientToolRequest({
    name: "interact_ai_conversation",
    requestId: "request-follow-failed",
    arguments: {
      action: "send",
      session_id: "session-a",
      message: "跟随失败",
    },
  }));
  await Promise.resolve();

  assert.equal(result.ok, false);
  assert.match(result.error, /运行跟随失败/);
  assert.deepEqual(result.content.history_locator, conversationHistoryLocator("session-a"));
  assert.deepEqual(runtimeStatuses, ["running"]);
  assert.equal(backgroundRuns.hasActiveRun("project-a", "session-a"), false);
});

function createInteractionRegistration(backgroundRuns, overrides = {}) {
  return createConversationInteractionClientToolRegistration({
    backgroundRuns,
    getClientToolExecutor: () => null,
    getClientCapabilities: () => [],
    onSessionRuntimeStatusChanged: () => undefined,
    ...overrides,
  });
}

function settledBackgroundRuns(result) {
  return {
    hasActiveRun: () => false,
    startOrResume: (input) => ({
      started: Promise.resolve({ running: true, userMessageId: input.userMessageId }),
      completion: Promise.resolve(result),
    }),
  };
}

function terminalScenarios() {
  return [
    {
      requestId: "request-error",
      result: completedTurn({
        outcome: "error",
        reply: conversationMessage("error-result", "error", "模型失败", {
          status: "error",
        }),
        userMessageId: "client_request-error",
      }),
      expectedRuntimeStatus: "error",
      expectedReplyRole: "error",
    },
    {
      requestId: "request-cancelled",
      result: completedTurn({
        outcome: "cancelled",
        reply: null,
        userMessageId: "client_request-cancelled",
      }),
      expectedRuntimeStatus: "idle",
      expectedReplyRole: null,
    },
  ];
}
