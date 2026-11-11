import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { EditorState } from "@codemirror/state";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { findReferenceTextSelection } = await vite.ssrLoadModule("/src/features/editor/model/referenceTextSelection.ts");
const { referenceOriginalFile, referenceRevealTarget } = await vite.ssrLoadModule("/src/entities/editor/model/referenceNavigation.ts");
const { spreadsheetReferenceRange, spreadsheetReferenceMatches } = await vite.ssrLoadModule("/src/features/office-preview/ui/spreadsheetReferenceSelection.ts");
const select = (content, reference, markdown = false) => {
  const doc = EditorState.create({ doc: content }).doc;
  const selection = findReferenceTextSelection(doc, reference, markdown);
  return selection ? doc.sliceString(selection.from, selection.to) : null;
};

test("原文本移位仍可定位；原行改成其他内容、目标消失或歧义时不误选", () => {
  const ref = { source: "source", content: "目标🙂", startLine: 2, endLine: 2 };
  assert.equal(select("a\n目标🙂\nend", ref), "目标🙂");
  assert.equal(select("new\na\n目标🙂\nend", ref), "目标🙂");
  assert.equal(select("a\n完全不同\nend", ref), null);
  assert.equal(select("目标🙂\na\n目标🙂", ref), null);
  assert.equal(select("only", { ...ref, startLine: -1, endLine: 1 }), null);
});

test("Markdown 渲染引用可映射到带加粗、链接的源码；重复内容不随便选择第一处", () => {
  const ref = { source: "markdown_preview", content: "引用 加粗与链接 结束。" };
  assert.equal(select("# 标题\n\n引用 **加粗**与[链接](https://example.com) 结束。", ref, true),
    "引用 **加粗**与[链接](https://example.com) 结束。");
  assert.equal(select("引用 **加粗**与[链接](https://example.com) 结束。\n\n引用 **加粗**与链接 结束。", ref, true), null);
  assert.equal(select("只有新的段落", ref, true), null);
});

test("部分图片引用定位原文档，保留页码；绝对路径不误当项目相对路径", () => {
  const payload = { kind: "image", reference: { id: "r", source: "pdf_page", projectId: "owner",
    imagePath: "tiance-attachment://shot", filePath: "tiance-attachment://shot",
    sourceFilePath: "C:/外部/source.pdf", sourceFileName: "source.pdf", sourceDisplayPath: "C:/外部/source.pdf", pageNumber: 8 } };
  assert.equal(referenceOriginalFile(payload).filePath, "C:/外部/source.pdf");
  assert.equal(referenceOriginalFile(payload).source, "external_path");
  assert.deepEqual(referenceRevealTarget(payload), { type: "pdf_page", page: 8 });
  payload.reference.sourceFilePath = "docs/source.pdf";
  assert.equal(referenceOriginalFile(payload).source, "project_file");
  payload.reference.pageNumber = 0;
  assert.equal(referenceRevealTarget(payload), null);
});

test("Excel 区域必须与引用的单元格快照相符，拒绝变化、空快照及无效范围", () => {
  const ref = { rangeAddress: "$AA$2:$AB$3", cells: [["甲", "1"], ["", "乙"]] };
  const range = spreadsheetReferenceRange(ref);
  assert.deepEqual(range, { sri: 1, eri: 2, sci: 26, eci: 27 });
  assert.equal(spreadsheetReferenceMatches(ref, range, (r, c) => ref.cells[r - 1][c - 26]), true);
  assert.equal(spreadsheetReferenceMatches(ref, range, () => "改过"), false);
  for (const invalid of [{ ...ref, rangeAddress: "A0:B2" }, { ...ref, rangeAddress: "B2:A1" },
    { ...ref, cells: undefined }, { ...ref, cells: [["甲"]] }]) assert.equal(spreadsheetReferenceRange(invalid), null);
});
