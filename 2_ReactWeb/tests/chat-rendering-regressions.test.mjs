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
const { formatChatMessageTimestamp } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatMessageTimestamp.ts");
const { ChatProcessFoldProvider, buildChatProcessFoldIdentities, createChatProcessFoldStore } = await vite.ssrLoadModule("/src/features/ai-panel/model/chatProcessFoldState.tsx");
after(() => vite.close());

const message = (id, role, extra = {}) => ({ id, role, content: "", thinkingContent: "", status: "done",
  usage: null, isThinkingExpanded: false, thinkingStartedAt: null, thinkingFinishedAt: null,
  processItems: [], toolCalls: [], createdAt: 1000, updatedAt: 2000, ...extra });
const thinking = (id, extra = {}) => ({ id, type: "thinking", content: "分析", status: "done", startedAt: 1000, finishedAt: 2000, ...extra });

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
