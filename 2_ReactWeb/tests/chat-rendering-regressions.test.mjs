import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { buildChatDisplayMessages, createChatDisplayProjector } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatDisplayMessages.ts");
const { mapConversationMessages } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatMessage.ts");
const { resolveProcessElapsedSeconds } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatAssistantProcessTime.ts");
const { ChatMessageItem } = await vite.ssrLoadModule("/src/features/ai-panel/ui/ChatMessageItem.tsx");
await vite.ssrLoadModule("/src/features/markdown-preview/ui/MarkdownPreview.tsx");
const { formatChatMessageTimestamp } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatMessageTimestamp.ts");
const { ChatProcessFoldProvider, buildChatProcessFoldIdentities, createChatProcessFoldStore } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatProcessFoldState.tsx");
after(() => vite.close());

const message = (id, role, extra = {}) => ({ id, role, content: "", thinkingContent: "", status: "done",
  usage: null, isThinkingExpanded: false, thinkingStartedAt: null, thinkingFinishedAt: null,
  processItems: [], toolCalls: [], createdAt: 1000, updatedAt: 2000, ...extra });
const thinking = (id, extra = {}) => ({ id, type: "thinking", content: "分析", status: "done", startedAt: 1000, finishedAt: 2000, ...extra });

const renderAssistant = (assistant, isSessionStreaming = false) => renderToStaticMarkup(
  createElement(ChatProcessFoldProvider, { sessionKey: "assistant-actions" }, createElement(ChatMessageItem, {
    message: assistant, expandedUserMessageIds: new Set(), interactions: {},
    autoCollapseAssistantProcess: true, clockTick: 2000, isLastMessage: true,
    isSessionStreaming, modelSwitchModelId: null, foldTurnId: "actions-user", foldThinkingOffset: 0,
  })),
);

test("工具轮次异常结束或暂停，没有最终正文也保留导出入口，不复制过程说明", () => {
  const tool = { id: "action-tool", callId: "action-call", name: "read_file", arguments: "{}",
    result: "已读取", error: "", ok: true, status: "done", startedAt: 1000, finishedAt: 1500 };
  for (const status of ["error", "cancelled"]) {
    const display = buildChatDisplayMessages([
      message("actions-user", "user"),
      message("before-tool", "assistant", { content: "先读文件，再整理。" }),
      message("tool-answer", "assistant", {
        status, toolCalls: [tool], processItems: [{ id: tool.id, type: "tool", tool }],
      }),
    ], { runtimeStatus: "idle" });
    const html = renderAssistant(display.find((item) => item.role === "assistant"));
    assert.match(html, /aria-label="导出回复"/);
    assert.doesNotMatch(html, /aria-label="复制回复"/);
  }
  const thinkingOnly = renderAssistant(message("thinking-only", "assistant", {
    status: "cancelled", thinkingContent: "正在分析", processItems: [thinking("analysis")],
  }));
  assert.match(thinkingOnly, /aria-label="导出回复"/);
  assert.doesNotMatch(thinkingOnly, /aria-label="复制回复"/);
});

test("复制入口只跟随正文，过程文字不能冒充最终回复，流式运行中不提前显示底栏", () => {
  const process = { id: "explanation", type: "content", content: "调用工具前的说明。" };
  const processOnly = message("process-only", "assistant", { status: "cancelled",
    content: process.content, processItems: [process] });
  assert.doesNotMatch(renderAssistant(processOnly), /aria-label="复制回复"/);
  assert.match(renderAssistant(processOnly), /aria-label="导出回复"/);
  for (const status of ["done", "error", "cancelled"]) {
    const html = renderAssistant({ ...processOnly, status, content: process.content + "已生成的回复正文。" });
    assert.match(html, /aria-label="复制回复"/);
    assert.match(html, /aria-label="导出回复"/);
  }
  const running = renderAssistant({ ...processOnly, status: "running" }, true);
  assert.doesNotMatch(running, /aria-label="(?:复制|导出)回复"/);
  assert.doesNotMatch(renderAssistant(message("empty", "assistant")), /aria-label="(?:复制|导出)回复"/);
});

test("流式临时消息换成正式记录时保留显示身份，采用正式正文和消息编号", () => {
  const project = createChatDisplayProjector();
  const user = message("handoff-user", "user");
  const live = project([user, message("optimistic", "assistant", { content: "流式正文较长", status: "running" })], { runtimeStatus: "running" })[1];
  const saved = message("persisted", "assistant", { content: "最终正文" });
  const final = project([user, saved], { runtimeStatus: "idle" })[1];
  assert.equal(final.displayKey ?? final.id, live.displayKey ?? live.id);
  assert.equal(final.id, "persisted");
  assert.equal(final.content, "最终正文");
  const next = project([user, saved, message("next-user", "user"), message("next-answer", "assistant")]);
  assert.equal(next[1].displayKey, final.displayKey);
  assert.notEqual(next[3].displayKey ?? next[3].id, final.displayKey);
  project([]);
  assert.equal(project([user, saved])[1].displayKey, undefined, "切走释放显示身份缓存");
});

test("输出上限保存片段不继承普通最终回复的显示身份", () => {
  const project = createChatDisplayProjector();
  const user = message("limit-user", "user");
  project([user, message("optimistic-limit", "assistant", { status: "running" })]);
  const output = project([user, message("saved-limit", "assistant", { finishReason: "output_limit" })]);
  assert.equal(output[1].displayKey ?? output[1].id, "saved-limit");
});

test("补齐跨越多页的工具轮次及用户消息时，已有正式回复保持同一个显示身份", () => {
  const project = createChatDisplayProjector();
  const messages = [message("question", "user"), ...Array.from({ length: 504 }, (_, n) =>
    message(`saved-${n}`, "assistant", { content: n === 503 ? "最终回复" : `过程${n}` }))];
  const first = project(messages.slice(-80)).at(-1);
  const foldScope = buildChatProcessFoldIdentities([first]).get(first.id).turnId;
  for (const count of [160, 240, 320, 400, 480, 505]) {
    const display = project(messages.slice(-count));
    assert.equal(display.at(-1).displayKey, first.displayKey);
    assert.equal(display.at(-1).content, "最终回复");
    assert.equal(display.at(-1).id, "saved-503");
    assert.equal(buildChatProcessFoldIdentities(display).get("saved-503").turnId, foldScope);
  }
  const next = project([...messages, message("another-user", "user"), message("another-answer", "assistant")]);
  assert.notEqual(next.at(-1).displayKey ?? next.at(-1).id, first.displayKey);
});

test("用户消息底栏显示记录的发送时间，编辑时间不会覆盖发送时间", () => {
  const [user] = mapConversationMessages([{message_id:"user-time",role:"user",content:"原始消息",status:"done",
    created_at:"2026-10-04T23:12:34+08:00",updated_at:"2026-10-05T00:00:00+08:00"}]);
  const sent = formatChatMessageTimestamp(user.createdAt);
  assert.equal(sent.dateTime,"2026-10-04T15:12:34.000Z");
  const expected = new Intl.DateTimeFormat("sv-SE",{year:"numeric",month:"2-digit",day:"2-digit",
    hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"}).format(new Date(user.createdAt));
  assert.equal(sent.label,expected);
  const html = renderToStaticMarkup(createElement(ChatProcessFoldProvider,{sessionKey:"timestamp-test"},createElement(ChatMessageItem,{message:user,expandedUserMessageIds:new Set(),
    interactions:{},autoCollapseAssistantProcess:true,clockTick:0,isLastMessage:false,isSessionStreaming:false,
    modelSwitchModelId:null,foldTurnId:user.id,foldThinkingOffset:0})));
  assert.match(html,/class="chat-msg__user-actions"[^>]*>[\s\S]*<time/);
  assert.ok(html.includes(`dateTime="${sent.dateTime}"`) || html.includes(`datetime="${sent.dateTime}"`));
  assert.ok(html.includes(sent.label));
  assert.ok(!html.includes("2026-10-04T16:00:00.000Z"));
});

test("缺失或无效的发送时间留空，不使用当前时间或编辑时间代替", () => {
  for(const timestamp of [undefined,null,NaN,Infinity,1e30]) assert.equal(formatChatMessageTimestamp(timestamp),null);
  assert.equal(formatChatMessageTimestamp(0).dateTime,"1970-01-01T00:00:00.000Z");
  const html=renderToStaticMarkup(createElement(ChatProcessFoldProvider,{sessionKey:"timestamp-test"},createElement(ChatMessageItem,{message:message("unknown","user",{content:"旧消息",createdAt:null,updatedAt:Date.now()}),
    expandedUserMessageIds:new Set(),interactions:{},autoCollapseAssistantProcess:true,clockTick:0,isLastMessage:false,
    isSessionStreaming:false,modelSwitchModelId:null,foldTurnId:"unknown",foldThinkingOffset:0})));
  assert.ok(!html.includes("<time"));
});

test("投影复用旧回合，当前输出、补发旧消息和运行状态变化仍与原算法一致", () => {
  const project = createChatDisplayProjector();
  const messages = Array.from({ length: 50 }, (_, n) => [
    message(`u${n}`, "user", { content: `问题${n}` }),
    message(`a${n}`, "assistant", { content: "中间说明", processItems: [thinking(`t${n}`)] }),
    message(`b${n}`, "assistant", { content: "最后回答" }),
  ]).flat();
  messages.push(message("live-user", "user"), message("live", "assistant", { status: "running" }));
  const first = project(messages, { runtimeStatus: "running" });
  assert.deepEqual(first, buildChatDisplayMessages(messages, { runtimeStatus: "running" }));
  const next = messages.with(-1, { ...messages.at(-1), content: "新增正文" });
  const second = project(next, { runtimeStatus: "running" });
  assert.deepEqual(second, buildChatDisplayMessages(next, { runtimeStatus: "running" }));
  for (let n = 0; n < 100; n++) assert.strictEqual(first[n], second[n]);
  assert.strictEqual(project(next, { runtimeStatus: "running" }), second);
  for (const status of ["idle", "running", "waiting", null]) {
    const corrected = next.with(1, { ...next[1], content: "历史修正" });
    assert.deepEqual(project(corrected, { runtimeStatus: status }), buildChatDisplayMessages(corrected, { runtimeStatus: status }));
  }
  assert.deepEqual(project(messages.slice(0, 3)), buildChatDisplayMessages(messages.slice(0, 3)));
  assert.deepEqual(project([]), []);
});

test("投影在历史未完成工具、错误和系统消息之间保持原有语义", () => {
  const call = { id: "tool-1", callId: "call-1", name: "read", arguments: "{}", result: "", error: "",
    ok: null, status: "running", startedAt: 1000, finishedAt: null };
  const histories = [
    [message("u1", "user"), message("a", "assistant", { status: "running", toolCalls: [call], processItems: [{ id: "tool-1", type: "tool", tool: call }] })],
    [message("sys", "system"), message("a", "assistant", { content: "hello" }), message("err", "error", { status: "error", content: "失败" })],
    [message("u1", "user"), message("sys", "system"), message("a", "assistant", { processItems: [thinking("t", { status: "running", finishedAt: null })] })],
  ];
  for (const history of histories) {
    const project = createChatDisplayProjector();
    for (const status of ["running", "idle", null]) {
      for (const tail of [[], [message("u2", "user"), message("b", "assistant", { status: "running" })]]) {
        const source = [...history, ...tail];
        assert.deepEqual(project(source, { runtimeStatus: status }), buildChatDisplayMessages(source, { runtimeStatus: status }));
      }
    }
  }
});

test("历史未记录的思考用时不伪造为 0，真实运行与完成用时正常", () => {
  const [mapped] = mapConversationMessages([{ message_id: "persisted", role: "assistant", content: "正文", thinking_content: "分析",
    status: "done", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:30Z" }]);
  const item = mapped.processItems.find((entry) => entry.type === "thinking");
  assert.equal(item.startedAt, null);
  assert.equal(resolveProcessElapsedSeconds(item, Date.now()), null);
  assert.equal(resolveProcessElapsedSeconds(thinking("live", { status: "running", finishedAt: null }), 4000), 3);
  assert.equal(resolveProcessElapsedSeconds(thinking("fast", { finishedAt: 1001 }), 4000), 0);
});

test("第二轮思考运行时，即使第一轮已结束且折叠，时钟变化也会重新渲染", () => {
  const props = { autoCollapseAssistantProcess: true, clockTick: 3000, expandedUserMessageIds: new Set(),
    interactions: {}, isLastMessage: true, isSessionStreaming: true, modelSwitchModelId: null,
    foldTurnId: "u", foldThinkingOffset: 0,
    message: message("a", "assistant", { status: "running", thinkingStartedAt: 1000, thinkingFinishedAt: 2000,
      processItems: [thinking("first"), thinking("second", { status: "running", startedAt: 3000, finishedAt: null })] }) };
  assert.equal(ChatMessageItem.compare(props, { ...props, clockTick: 4000 }), false);
  const done = { ...props, message: { ...props.message, processItems: [thinking("first")] } };
  assert.equal(ChatMessageItem.compare(done, { ...done, clockTick: 4000 }), true);
});

test("手动折叠状态保留到重新订阅，隔离会话和用户回合", () => {
  const store = createChatProcessFoldStore();
  let notifications = 0;
  const unsubscribe = store.subscribe("session-a/u1", () => notifications++);
  store.set("session-a/u1", "thinking:0", true);
  store.set("session-a/u1", "tool:call-1", true);
  unsubscribe();
  store.set("session-b/u1", "thinking:0", false);
  store.subscribe("session-a/u1", () => notifications++);
  assert.equal(store.get("session-a/u1")["thinking:0"], true);
  assert.equal(store.get("session-a/u1")["tool:call-1"], true);
  assert.equal(store.get("session-a/u2")["thinking:0"], undefined);
  assert.equal(store.get("session-b/u1")["thinking:0"], false);
  assert.equal(notifications, 2);
});

test("折叠身份按用户回合与段落顺序保持，不依赖临时 AI 消息编号", () => {
  const raw = [message("u", "user"), message("a1", "assistant", { processItems: [thinking("t1")] }),
    message("a2", "assistant", { processItems: [thinking("t2")] })];
  const ids = buildChatProcessFoldIdentities(raw);
  assert.deepEqual(ids.get("a1"), { turnId: "u", thinkingOffset: 0 });
  assert.deepEqual(ids.get("a2"), { turnId: "u", thinkingOffset: 1 });
  const merged = buildChatDisplayMessages(raw);
  const mergedId = merged.find((item) => item.role === "assistant").id;
  assert.deepEqual(buildChatProcessFoldIdentities(merged).get(mergedId), { turnId: "u", thinkingOffset: 0 });
});
