import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom", logLevel: "silent", root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const { followConversationRun } = await vite.ssrLoadModule("/src/features/client-tools/model/conversationRunFollower.ts");
const { createChatStreamAccumulator } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatStreamAccumulator.ts");
const { prepareConversationStreamResume } = await vite.ssrLoadModule("/src/features/ai-panel/model/conversationStreamResume.ts");
const { buildChatDisplayMessages } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatDisplayMessages.ts");
const { mapConversationMessages } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatMessage.ts");
after(() => vite.close());

function persisted(id, role, content, extra = {}) {
  return { message_id: id, session_id: "session", role, content, thinking_content: "", status: "done",
    usage: null, provider_id: "deepseek", model_id: "deepseek-v4", created_at: "2026-10-09T01:00:00Z",
    updated_at: "2026-10-09T01:00:00Z", ...extra };
}
const next = persisted("automatic", "user", "【天策自动续接通知】\n继续", {
  message_source: "output_limit", continuation_of: "root",
});
const limit = { kind: "output_limit", action: "send_message", will_recover: true,
  next_user_message: next, saved_message: null };
const started = (id) => ({ kind: "conversation_run_started", user_message_id: id });
const settled = (id, status, reply = null) => ({ kind: "conversation_run_settled", user_message_id: id,
  status, assistant_message_id: reply });

test("自动续接后子会话等待器跟随最终回复，断线重放不会退回原消息", async () => {
  let starts = 0;
  const result = await followConversationRun({ expectedUserMessageId: "root",
    request: { project_id: "project", session_id: "session", messages: [] },
    onStarted: () => { starts += 1; }, onEvent: () => undefined,
  }, {
    stream: async (_request, { onOpen, onEvent }) => {
      onOpen(); await onEvent(started("root")); await onEvent(limit);
      await onEvent(settled("root", "error")); throw new Error("disconnected");
    },
    resume: async (_project, _session, onEvent) => {
      await onEvent(started("root")); await onEvent(limit); await onEvent(settled("root", "error"));
      await onEvent(started("automatic")); await onEvent(settled("automatic", "done", "final"));
    },
    retryDelay: async () => undefined,
  });
  assert.equal(starts, 1);
  assert.deepEqual(result, { userMessageId: "automatic", outcome: "done", assistantMessageId: "final" });
});

test("等待器拒绝把其他消息伪装成自动续接", async () => {
  await assert.rejects(followConversationRun({ expectedUserMessageId: "root",
    request: { project_id: "project", session_id: "session", messages: [] },
    onStarted: () => undefined, onEvent: () => undefined,
  }, {
    stream: async (_request, { onOpen, onEvent }) => {
      onOpen(); await onEvent(started("root"));
      await onEvent({ ...limit, next_user_message: { ...next, continuation_of: "another-user" } });
    },
  }), /自动续接消息不属于当前会话运行/);
});

test("截断通知保留正文和思考，丢弃半截工具并创建独立的续接流消息", () => {
  let messages = mapConversationMessages([persisted("root", "user", "任务"), persisted("stream", "assistant", "")]);
  const accumulator = createChatStreamAccumulator({ assistantId: "stream", streamingEnabled: false,
    isSessionPresented: () => false, isThinkingStuckToBottom: () => false, onUsage: () => undefined,
    scrollThinkingContentToBottom: () => undefined, sessionId: "session", streamProjectId: "project",
    updateSessionMessages: (_project, _session, update) => { messages = update(messages); },
  });
  accumulator.handleEvent({ kind: "thinking_delta", content: "只生成了思考" });
  accumulator.handleEvent({ kind: "tool_call_delta", tool_call: { call_id: "half", name: "write_file", arguments: '{"path":' } });
  const partial = persisted("partial", "assistant", "", { thinking_content: "只生成了思考", finish_reason: "output_limit" });
  accumulator.handleEvent({ ...limit, saved_message: partial });
  accumulator.handleEvent({ kind: "delta", content: "最终回复" });
  accumulator.flushNow();
  assert.equal(messages.find((m) => m.id === "partial").thinkingContent, "只生成了思考");
  assert.equal(messages.find((m) => m.id === "automatic").messageSource, "output_limit");
  const current = messages.find((m) => m.id === accumulator.getAssistantId());
  assert.equal(current.content, "最终回复");
  assert.deepEqual(current.toolCalls ?? [], []);
  assert.notEqual(current.id, "stream");
});

test("重连和已处理折叠不会把保存的截断片段合并成最终回答", () => {
  const messages = mapConversationMessages([
    persisted("root", "user", "任务"),
    persisted("partial", "assistant", "截断片段", { finish_reason: "output_limit", include_in_context: false }),
    persisted("final", "assistant", "完整回答"),
  ]);
  const display = buildChatDisplayMessages(messages, { runtimeStatus: "idle" });
  assert.deepEqual(display.map((m) => m.id), ["root", "partial", "final"]);
  const resume = prepareConversationStreamResume(messages.slice(0, 2), "new-stream", 1);
  assert.equal(resume.assistantMessage.content, "");
  assert.equal(resume.messages[1].finishReason, "output_limit");
});

test("新续接用户消息有恢复点，完整重放不会把上一轮工具过程插入新回合", () => {
  let messages = mapConversationMessages([
    persisted("root", "user", "任务"),
    persisted("root-tools", "assistant", "已完成的操作"), next,
  ]);
  const resume = prepareConversationStreamResume(messages, "new-stream", 1);
  assert.equal(resume.checkpointMessageId, "automatic");
  messages = resume.messages;
  const accumulator = createChatStreamAccumulator({ assistantId: "new-stream", initialMessage: resume.assistantMessage,
    streamingEnabled: false, isSessionPresented: () => false, isThinkingStuckToBottom: () => false,
    onUsage: () => undefined, scrollThinkingContentToBottom: () => undefined,
    sessionId: "session", streamProjectId: "project",
    updateSessionMessages: (_project, _session, update) => { messages = update(messages); },
  });
  accumulator.handleEvent(started("root"));
  accumulator.handleEvent({ kind: "delta", content: "重放的旧操作" });
  accumulator.handleEvent(limit);
  accumulator.handleEvent(started("automatic"));
  accumulator.handleEvent({ kind: "delta", content: "续接的最终回复" });
  accumulator.flushNow();
  assert.equal(messages.at(-1).content, "续接的最终回复");
  assert.equal(messages.filter((m) => m.role === "user").length, 2);
  assert.equal(messages.find((m) => m.id === "root-tools").content, "已完成的操作");
});
