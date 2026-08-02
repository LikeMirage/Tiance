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
  buildProgressiveMarkdownSegments,
  buildStreamingMarkdownSegments,
} = await vite.ssrLoadModule(
  "/src/features/markdown-preview/model/markdownSegments.ts",
);
const { normalizeMarkdownMath } = await vite.ssrLoadModule(
  "/src/features/markdown-preview/model/markdownMath.ts",
);
const {
  prepareMarkdownForVisualEditor,
  restoreMarkdownFromVisualEditor,
} = await vite.ssrLoadModule(
  "/src/features/markdown-visual-editor/model/markdownVisualEditorContent.ts",
);

after(async () => {
  await vite.close();
});

test("渐进分块能够无损拼回完整 Markdown", () => {
  const content = [
    "# 标题",
    "",
    "第一段内容。",
    "",
    "第二段内容。",
    "",
    "第三段内容。",
  ].join("\n");

  const segments = buildProgressiveMarkdownSegments(content, 12);

  assert.ok(segments.length > 1);
  assert.equal(segments.map((segment) => segment.content).join(""), content);
});

test("代码围栏内部不会被拆分", () => {
  const fencedBlock = [
    "```ts",
    "const first = 1;",
    "",
    "const second = 2;",
    "```",
  ].join("\n");
  const content = `${fencedBlock}\n\n围栏后的正文`;

  const segments = buildProgressiveMarkdownSegments(content, 16);
  const containingFence = segments.filter((segment) => segment.content.includes("```ts"));

  assert.equal(containingFence.length, 1);
  assert.ok(containingFence[0].content.includes("const second = 2;"));
  assert.equal(segments.map((segment) => segment.content).join(""), content);
});

test("流式分块只把稳定边界前的内容固化，末段继续作为尾部", () => {
  const content = "已经完成的段落。\n\n仍在输出的段落";

  const result = buildStreamingMarkdownSegments(content, 8);

  assert.equal(result.chunks.map((segment) => segment.content).join(""), "已经完成的段落。\n\n");
  assert.equal(result.tail, "仍在输出的段落");
});

test("超长 GFM 表格按完整行拆分且每块都保留可解析表头", () => {
  const header = "| 编号 | 公式 |\n| --- | --- |\n";
  const rows = Array.from(
    { length: 20 },
    (_, index) => `| ${index + 1} | $x_{${index + 1}} = ${index + 1}$ |\n`,
  );
  const content = `${header}${rows.join("")}`;

  const segments = buildProgressiveMarkdownSegments(content, 120);

  assert.ok(segments.length > 1);
  assert.ok(segments.every((segment) => segment.content.startsWith(header)));
  assert.ok(segments.every((segment) => segment.content.length <= 120));
  assert.ok(segments.every((segment) => segment.tableGroupId === segments[0].tableGroupId));
  assert.deepEqual(
    segments.map((segment) => segment.tablePartIndex),
    segments.map((_, index) => index),
  );
  assert.equal(
    segments.flatMap((segment) => segment.content.split("\n").slice(2, -1)).length,
    rows.length,
  );
});

test("不成对的方括号公式标记不会吞掉后续 Markdown", () => {
  const content = ["# 标题", "", "\\[TOC]", "", "## 正文章节"].join("\n");

  assert.equal(normalizeMarkdownMath(content), content);
});

test("成对的单行方括号公式仍会转换为块级公式", () => {
  assert.equal(normalizeMarkdownMath("\\[x + y\\]"), "$$\nx + y\n$$");
});

test("成对的多行方括号公式仍会转换为块级公式", () => {
  const content = ["\\[", "x + y", "\\]"].join("\n");

  assert.equal(normalizeMarkdownMath(content), ["$$", "x + y", "$$"].join("\n"));
});

test("可视化编辑器保护 TOC 指令并能无损还原", () => {
  const source = ["# 标题", "", "[TOC]", "", "## 正文"].join("\n");
  const prepared = prepareMarkdownForVisualEditor(source);

  assert.equal(prepared, ["# 标题", "", "\\[TOC\\]", "", "## 正文"].join("\n"));
  assert.equal(restoreMarkdownFromVisualEditor(prepared), source);
});
