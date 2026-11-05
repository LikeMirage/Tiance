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
const { buildUserMessageNavigationItems, mergeUserMessageNavigationItems } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/userMessageNavigation.ts",
);
const {
  getMessageNavigatorHoverTickWidth,
  resolveNearestMessageNavigatorIndex,
} = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/messageNavigatorInteraction.ts",
);

after(async () => {
  await vite.close();
});

test("所有用户回合都有导航项，包括正在执行而没有最终回复的提问", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "user-1", role: "user", content: "第一个问题" }),
    message({ id: "assistant-1", role: "assistant", content: "第一个回答" }),
    message({ id: "user-2", role: "user", content: "还在生成的问题" }),
    message({ id: "assistant-2", role: "assistant", content: "生成中", status: "running" }),
  ]);

  assert.deepEqual(items, [{
    assistantMessageId: "assistant-1",
    assistantPreview: "第一个回答",
    turnNumber: 1,
    userMessageId: "user-1",
    userPreview: "第一个问题",
  }, { assistantMessageId: undefined, assistantPreview: "", turnNumber: 2,
    userMessageId: "user-2", userPreview: "还在生成的问题" }]);
});

test("多次工具调用后只取最后正式回复", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "user-1", role: "user", content: "分析项目" }),
    message({ id: "assistant-1", role: "assistant", content: "先读取文件" }),
    message({ id: "tool-1", role: "tool", content: "文件内容" }),
    message({ id: "assistant-2", role: "assistant", content: "再搜索引用" }),
    message({ id: "tool-2", role: "tool", content: "搜索结果" }),
    message({ id: "assistant-3", role: "assistant", content: "最终分析结论" }),
  ]);

  assert.equal(items.length, 1);
  assert.equal(items[0].assistantPreview, "最终分析结论");
});

test("工具结果之后没有正式回复也保留提问，但不把过程当作正式回复", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "user-1", role: "user", content: "执行任务" }),
    message({ id: "assistant-1", role: "assistant", content: "准备调用工具" }),
    message({ id: "tool-1", role: "tool", content: "工具完成" }),
  ]);

  assert.equal(items.length, 1);
  assert.equal(items[0].assistantPreview, "");
});

test("只有附件或失败的用户消息仍可定位", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "attachment", role: "user", content: "" }),
    message({ id: "failed", role: "user", content: "失败的请求" }),
    message({ id: "error", role: "error", content: "本地错误", status: "error" }),
  ]);
  assert.equal(items.length, 2);
  assert.equal(items[0].userPreview, "（附件消息）");
  assert.equal(items[1].assistantPreview, "本地错误");
});

test("正文只有末页或向前翻页不改变完整目录及编号，新提问立即追加", () => {
  const index = Array.from({ length: 120 }, (_, i) => ({ userMessageId: `u${i}`,
    turnNumber: i + 1, userPreview: `Question ${i}`, assistantPreview: `Answer ${i}` }));
  const tail = buildUserMessageNavigationItems([message({ id: "u119", role: "user", content: "Question 119" }),
    message({ id: "new", role: "user", content: "刚发送" })]);
  const merged = mergeUserMessageNavigationItems(index, tail);
  assert.equal(merged.length, 121);
  assert.equal(merged[119].turnNumber, 120);
  assert.equal(merged[119].assistantPreview, "Answer 119");
  assert.equal(merged[120].turnNumber, 121);
  const older = buildUserMessageNavigationItems([message({ id: "u30", role: "user", content: "Question 30" })]);
  assert.deepEqual(mergeUserMessageNavigationItems(index, older).map(x => x.turnNumber), index.map(x => x.turnNumber));
});

test("引用消息预览只显示用户真实提问", () => {
  const items = buildUserMessageNavigationItems([
    message({
      id: "user-1",
      role: "user",
      content: "请总结这份内容\n【用户消息】也是正文",
      references: [{ type: "text", reference: {
          id: "text-1",
          content: "引用正文",
          displayPath: "note.md",
          fileName: "note.md",
          filePath: "note.md",
          projectId: "project-a",
          source: "source",
      } }],
    }),
    message({ id: "assistant-1", role: "assistant", content: "总结结果" }),
  ]);

  assert.equal(items[0].userPreview, "请总结这份内容 【用户消息】也是正文");
});

test("消息导航按鼠标高度连续选择最近一项", () => {
  assert.equal(resolveNearestMessageNavigatorIndex(5, 80, 100, 100), 0);
  assert.equal(resolveNearestMessageNavigatorIndex(5, 100, 100, 100), 0);
  assert.equal(resolveNearestMessageNavigatorIndex(5, 149, 100, 100), 2);
  assert.equal(resolveNearestMessageNavigatorIndex(5, 199, 100, 100), 4);
  assert.equal(resolveNearestMessageNavigatorIndex(5, 220, 100, 100), 4);
  assert.equal(resolveNearestMessageNavigatorIndex(0, 150, 100, 100), null);
});

test("悬浮消息附近的横条按距离逐级缩短", () => {
  assert.equal(getMessageNavigatorHoverTickWidth(0), 28);
  assert.equal(getMessageNavigatorHoverTickWidth(1), 20);
  assert.equal(getMessageNavigatorHoverTickWidth(2), 16);
  assert.equal(getMessageNavigatorHoverTickWidth(3), 13);
  assert.equal(getMessageNavigatorHoverTickWidth(4), null);
  assert.equal(getMessageNavigatorHoverTickWidth(null), null);
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
    ...overrides,
  };
}
