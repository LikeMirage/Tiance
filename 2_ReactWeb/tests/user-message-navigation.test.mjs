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
const { buildUserMessageNavigationItems } = await vite.ssrLoadModule(
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

test("只为已有最终回复的用户回合生成导航项", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "user-1", role: "user", content: "第一个问题" }),
    message({ id: "assistant-1", role: "assistant", content: "第一个回答" }),
    message({ id: "user-2", role: "user", content: "还在生成的问题" }),
    message({ id: "assistant-2", role: "assistant", content: "生成中", status: "running" }),
  ]);

  assert.deepEqual(items, [{
    assistantPreview: "第一个回答",
    turnNumber: 1,
    userMessageId: "user-1",
    userPreview: "第一个问题",
  }]);
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

test("工具结果之后没有正式回复时不生成导航项", () => {
  const items = buildUserMessageNavigationItems([
    message({ id: "user-1", role: "user", content: "执行任务" }),
    message({ id: "assistant-1", role: "assistant", content: "准备调用工具" }),
    message({ id: "tool-1", role: "tool", content: "工具完成" }),
  ]);

  assert.deepEqual(items, []);
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
