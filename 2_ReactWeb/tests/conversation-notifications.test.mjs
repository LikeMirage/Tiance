import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const load = (name) => vite.ssrLoadModule(`/src/features/ai-panel/${name}`);
const { buildChatDisplayMessages, createChatDisplayProjector } = await load("model/chatDisplayMessages.ts");
const { createChatStreamAccumulator } = await load("model/chatStreamAccumulator.ts");
const { mergeLiveChatNotifications, reuseChatMessageRevisions } = await load("model/chatNotifications.ts");
const { prepareConversationStreamResume } = await load("model/conversationStreamResume.ts");
const { buildModelSwitches } = await load("model/chatModelTransitions.ts");
const { ChatMessageItem } = await load("ui/ChatMessageItem.tsx");
const { useVirtualMessageList } = await load("model/useVirtualMessageList.ts");
const { ChatProcessFoldProvider } = await load("model/chatProcessFoldState.tsx");
after(() => vite.close());

const message = (id, role, extra = {}) => ({ id, role, content: "", thinkingContent: "", status: "done",
  usage: null, isThinkingExpanded: false, thinkingStartedAt: null, thinkingFinishedAt: null,
  processItems: [], toolCalls: [], createdAt: 1000, updatedAt: 2000, ...extra });
const notice = (id = "compaction") => message(id, "system", { name: "memory_compaction", content: "已完成异步记忆压缩。" });
const tool = { id: "tool-x", callId: "x", name: "inspect_workspace", arguments: "{}", result: "", error: "", ok: null,
  status: "running", startedAt: 1000, finishedAt: null };
const failure = (id = "failure", extra = {}) => message(id, "error", { content: "网络断开", runAttemptFailure: {
  event_id: 1, run_id: "run-u", session_id: "s", user_message_id: "u", attempt_index: 1, attempt_count: 2,
  error_message: "网络断开", occurred_at: "2026-10-09T00:00:00Z", ...extra,
} });

test("运行提示携带的模型信息不产生虚假的对话模型切换", () => {
  const switches = buildModelSwitches([message("u", "user", { targetModelId: "chat" }),
    message("a", "assistant", { modelId: "chat" }), { ...notice(), modelId: "compressor" },
    { ...failure(), modelId: "failed-provider-model" }, message("b", "assistant", { modelId: "chat" }),
    message("v", "user", { targetModelId: "new-chat" })]);
  assert.deepEqual([...switches], [["v", "new-chat"]]);
});

function render(message, streaming, expanded = false) {
  // This check targets process/notice UI; Markdown parser semantics have their own tests.
  message = { ...message, content: "", processItems: message.processItems.filter((item) => item.type !== "content") };
  return renderToStaticMarkup(createElement(ChatProcessFoldProvider, { sessionKey: "s" },
    createElement(ChatMessageItem, { message, expandedUserMessageIds: new Set(), interactions: {},
      autoCollapseAssistantProcess: !expanded, clockTick: 4000, isLastMessage: false, isSessionStreaming: streaming,
      modelSwitchModelId: null, foldTurnId: "u", foldThinkingOffset: 0 })));
}
function accumulator() {
  const previousWindow = globalThis.window;
  globalThis.window = globalThis;
  let messages = [message("u", "user"), message("a", "assistant", { status: "running" })];
  const stream = createChatStreamAccumulator({ assistantId: "a", sessionId: "s", streamProjectId: "p",
    streamingEnabled: true, isSessionPresented: () => false, isThinkingStuckToBottom: () => false,
    onUsage() {}, scrollThinkingContentToBottom() {}, updateSessionMessages(_p, _s, update) { messages = update(messages); } });
  return { stream, get messages() { return messages; }, set messages(next) { messages = next; },
    dispose() { stream.clearFlushTimer(); globalThis.window = previousWindow; } };
}

test("压缩和单次失败提示不结束运行，不改工具结果，不提前显示用量", () => {
  const base = [message("u", "user"), message("a", "assistant", { content: "说明", usage: { total_tokens: 10 } }),
    message("b", "assistant", { toolCalls: [tool], processItems: [{ id: tool.id, type: "tool", tool }], usage: { total_tokens: 20 } })];
  const projector = createChatDisplayProjector();
  const original = projector(base, { runtimeStatus: "running" }).find((m) => m.role === "assistant");
  for (const event of [notice(), failure()]) {
    const display = projector([...base, event], { runtimeStatus: "running" });
    const active = display.find((m) => m.role === "assistant");
    assert.equal(active.displayKey, original.displayKey);
    assert.equal(active.status, "running");
    assert.equal(active.toolCalls[0].status, "running");
    assert.equal(active.usage.total_tokens, original.usage.total_tokens);
    const html = render(active, true);
    assert.ok(html.includes("inspect_workspace"));
    assert.ok(!html.includes("已处理"));
    assert.ok(!html.includes("chat-msg__usage"));
  }
});

test("过程内提示随已处理折叠，最终正文后的提示保持独立，展开模式可看见原提示", () => {
  const display = buildChatDisplayMessages([message("u", "user"), message("a", "assistant", { content: "中间说明" }),
    notice("inside"), failure(), message("b", "assistant", { content: "最终回答" }), notice("outside")], { runtimeStatus: "idle" });
  assert.deepEqual(display.map((m) => m.id), ["u", "b", "outside"]);
  const assistant = display[1];
  assert.deepEqual(assistant.processItems.filter((item) => item.type === "notification").map((item) => item.id), ["inside", "failure"]);
  assert.equal(assistant.content, "最终回答");
  const collapsed = render(assistant, false);
  assert.ok(collapsed.includes("已处理"));
  assert.ok(!collapsed.includes('data-chat-message-id="inside"'));
  const expanded = render(assistant, false, true);
  assert.ok(expanded.includes('data-chat-message-id="inside"'));
  assert.ok(expanded.includes("chat-msg__event-label"));
});

test("流式期间收到通知先隐藏，单次响应结束即显示，下一次响应保持原位置且不重复", () => {
  const state = accumulator();
  try {
    state.stream.handleEvent({ kind: "conversation_run_started", user_message_id: "u", run_id: "run-u" });
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "delta", content: "这一段已写完。" });
    state.stream.flushNow();
    state.messages = mergeLiveChatNotifications(state.messages, [notice()]);
    assert.equal(state.messages.at(-1).notificationPending, true);
    assert.ok(!buildChatDisplayMessages(state.messages, { runtimeStatus: "running" }).some((m) => m.id === "compaction"));
    state.stream.handleEvent({ kind: "model_response_finished", has_tool_calls: false });
    assert.equal(state.messages[1].content, "这一段已写完。");
    assert.equal(state.messages.at(-1).notificationPending, false);
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "delta", content: "下一段" });
    state.stream.flushNow();
    assert.deepEqual(state.messages[1].processItems.map((item) => item.type), ["content", "notification"]);
    state.messages = mergeLiveChatNotifications(state.messages, [notice()]);
    assert.equal(state.messages.length, 2);
    assert.equal(state.messages[1].content, "下一段");
  } finally { state.dispose(); }
});

test("工具响应边界在工具执行前释放通知，正文、工具、通知的顺序不变", () => {
  const state = accumulator();
  try {
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "delta", content: "先检查文件" });
    state.stream.handleEvent({ kind: "tool_call_delta", tool_call: { call_id: "x", name: "inspect_workspace", arguments: "{}" } });
    state.messages = mergeLiveChatNotifications(state.messages, [notice()]);
    state.stream.handleEvent({ kind: "model_response_finished", has_tool_calls: true });
    state.stream.handleEvent({ kind: "tool_call", tool_call: { call_id: "x", name: "inspect_workspace", arguments: "{}" } });
    assert.deepEqual(state.messages[1].processItems.map((item) => item.type), ["content", "tool", "notification"]);
    assert.equal(state.messages[1].toolCalls[0].status, "running");
    assert.equal(state.messages.length, 2);
  } finally { state.dispose(); }
});

test("输出上限保存的片段位于边界通知之前，自动续接用户位于通知之后", () => {
  const state = accumulator();
  const persisted = (message_id, role, content, extra = {}) => ({ message_id, project_id: "p", session_id: "s",
    role, content, thinking_content: "", status: "done", created_at: "2026-10-09T00:00:00Z", ...extra });
  try {
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "delta", content: "保留的截断内容" });
    state.stream.handleEvent({ kind: "model_response_finished", error_code: "upstream_output_limit",
      notifications: [persisted("n", "system", "已完成异步记忆压缩。", { name: "memory_compaction" })] });
    state.stream.handleEvent({ kind: "output_limit", action: "send_message", will_recover: true,
      saved_message: persisted("partial", "assistant", "保留的截断内容", { finish_reason: "output_limit" }),
      next_user_message: persisted("automatic", "user", "继续原任务", { message_source: "output_limit" }) });
    assert.deepEqual(state.messages.slice(0, 4).map((m) => m.id), ["u", "partial", "n", "automatic"]);
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "delta", content: "最终回答" });
    state.stream.flushNow();
    assert.equal(state.messages.at(-1).content, "最终回答");
    assert.equal(state.messages[1].content, "保留的截断内容");
  } finally { state.dispose(); }
});

test("暂停、普通重试及最终失败不丢通知，失败有真实用户回合身份", () => {
  for (const action of ["cancel", "retry", "error"]) {
    const state = accumulator();
    try {
      state.stream.handleEvent({ kind: "conversation_run_started", user_message_id: "u", run_id: "run-u" });
      state.stream.handleEvent({ kind: "model_response_started" });
      state.messages = mergeLiveChatNotifications(state.messages, [notice()]);
      if (action === "cancel") state.stream.finalizeCancelled();
      else if (action === "retry") {
        state.stream.handleEvent({ kind: "retry_reset", error: "网络断开", attempt_index: 2, attempt_count: 2 });
        state.stream.handleEvent({ kind: "model_response_started" });
        state.stream.handleEvent({ kind: "error", error: "仍然断开", attempt_index: 2, attempt_count: 2 });
      } else state.stream.handleEvent({ kind: "error", error: "网络断开" });
      const notices = state.messages.flatMap((m) => [m, ...(m.processItems ?? []).flatMap((item) => item.message ? [item.message] : [])]);
      assert.equal(notices.filter((m) => m.id === "compaction").length, 1);
      assert.ok(!notices.some((m) => m.notificationPending));
      for (const m of notices.filter((m) => m.runAttemptFailure)) {
        assert.equal(m.runAttemptFailure.user_message_id, "u");
        assert.equal(m.runAttemptFailure.run_id, "run-u");
      }
    } finally { state.dispose(); }
  }
});

test("历史工具结果跨过通知仍归属原调用；通知不影响重连恢复点且不会消失", () => {
  const assistant = message("a", "assistant", { toolCalls: [tool], processItems: [{ id: tool.id, type: "tool", tool }] });
  const result = message("result", "tool", { toolCallId: "x", name: "inspect_workspace", content: JSON.stringify({ call_id: "x", tool: "inspect_workspace", ok: true, result: { files: [] } }) });
  const history = [message("u", "user"), assistant, notice(), result, notice("end")];
  const display = buildChatDisplayMessages(history, { runtimeStatus: "running" });
  assert.equal(display.find((m) => m.role === "assistant").toolCalls[0].status, "done");
  const snapshot = prepareConversationStreamResume(history, "fallback");
  assert.equal(snapshot.checkpointMessageId, "result");
  assert.deepEqual(snapshot.messages.filter((m) => m.name === "memory_compaction").map((m) => m.id), ["compaction", "end"]);
  assert.equal(snapshot.assistantMessage.processItems.filter((item) => item.type === "notification").length, 0);
});

test("虚拟列表在末尾为通知时仍挂载并计时当前工具回复", () => {
  const messages = Array.from({ length: 30 }, (_, index) => message(`u-${index}`, "user"));
  messages.push(message("a", "assistant", { status: "running", toolCalls: [tool], processItems: [{ id: tool.id, type: "tool", tool }] }), notice());
  function VirtualizedTest() {
    const { virtualItems } = useVirtualMessageList({ enabled: true, messages, keepLastMessageMounted: true,
      keepMessageMountedId: "a", scrollParentRef: { current: null } });
    assert.ok(virtualItems.some((item) => item.message.id === "compaction"));
    const active = virtualItems.find((item) => item.message.id === "a");
    assert.ok(active);
    return createElement(ChatMessageItem, { message: active.message, autoCollapseAssistantProcess: true,
      clockTick: 5000, expandedUserMessageIds: new Set(), interactions: {}, isLastMessage: false,
      isSessionStreaming: true, modelSwitchModelId: null, foldTurnId: "u", foldThinkingOffset: 0 });
  }
  const html = renderToStaticMarkup(createElement(ChatProcessFoldProvider, { sessionKey: "s" }, createElement(VirtualizedTest)));
  assert.ok(html.includes("inspect_workspace"));
  assert.ok(!html.includes("已处理"));
  assert.ok(!html.includes("chat-msg__usage"));
});

test("旧历史里工具结果先于助手消息时，中间通知仍按顺序进入处理折叠", () => {
  const result = message("result", "tool", { toolCallId: "x", name: "inspect_workspace",
    content: JSON.stringify({ call_id: "x", tool: "inspect_workspace", ok: true, result: { files: [] } }) });
  const display = buildChatDisplayMessages([message("u", "user"), result, notice(),
    message("a", "assistant", { content: "最终回答" }), notice("outside")], { runtimeStatus: "idle" });
  assert.deepEqual(display.map((m) => m.id), ["u", "a", "outside"]);
  assert.deepEqual(display[1].processItems.map((item) => item.type), ["tool", "notification"]);
  assert.equal(display[1].toolCalls[0].status, "done");
  assert.equal(display[1].content, "最终回答");
});


test("历史刷新复用未改变的消息，活动请求失败通过流事件显示而不重复混入", () => {
  const old = message("old", "assistant", { content: "历史正文" });
  const active = message("a", "assistant", { status: "running", modelResponseInFlight: true });
  const current = [old, message("u", "user"), active];
  const merged = mergeLiveChatNotifications(current, [failure(), notice()]);
  assert.equal(merged.filter((m) => m.runAttemptFailure).length, 0);
  assert.equal(merged.at(-1).notificationPending, true);
  assert.equal(merged[0], old);
  const updated = message("other", "assistant", { content: "已更新", updatedAt: 3000 });
  assert.equal(reuseChatMessageRevisions([old], [{ ...old }, updated])[0], old);
});

test("合并保持固定显示键，导出和导航仍使用最终正式消息编号", () => {
  const user = message("u", "user");
  const first = message("first", "assistant", { content: "工具前的说明" });
  const next = message("next", "assistant", { status: "running" });
  const initial = buildChatDisplayMessages([user, first], { runtimeStatus: "running" })[1];
  const later = buildChatDisplayMessages([user, first, notice(), next], { runtimeStatus: "running" })[1];
  assert.equal(initial.displayKey ?? initial.id, later.displayKey ?? later.id);
  assert.equal(later.id, "next");
  assert.equal(later.status, "running");
  const cancelled = buildChatDisplayMessages([user, message("a", "assistant", { status: "cancelled" })], { runtimeStatus: "running" })[1];
  assert.equal(cancelled.status, "cancelled");
});

test("工具等待中通过流通道收到通知立即显示，再次开始模型响应时保留通知位置", () => {
  const state = accumulator();
  try {
    const persisted = { message_id: "n", role: "system", name: "memory_compaction", content: "压缩完成",
      status: "done", created_at: "2026-10-09T00:00:00Z", updated_at: "2026-10-09T00:00:00Z" };
    state.stream.handleEvent({ kind: "model_response_started" });
    state.stream.handleEvent({ kind: "model_response_finished", has_tool_calls: true });
    state.stream.handleEvent({ kind: "tool_call", tool_call: { call_id: "x", name: "inspect_workspace", arguments: "{}" } });
    state.stream.handleEvent({ kind: "conversation_notice", message: persisted });
    assert.equal(state.messages.at(-1).id, "n");
    assert.equal(state.messages.at(-1).notificationPending, false);
    state.stream.handleEvent({ kind: "model_response_started" });
    assert.equal(state.messages.length, 2);
    assert.equal(state.messages[1].processItems.at(-1).message.id, "n");
    state.stream.handleEvent({ kind: "conversation_notice", message: persisted });
    assert.equal(state.messages.length, 2);
  } finally { state.dispose(); }
});
