import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/features/editor/model/documentMarks.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { anchorSelection, resolveMark } = await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

test("a shifted multiline mark survives insertion, including CRLF-normalized editor lines", () => {
  const text = "文件\n开始\n焊接参数\n结束";
  const mark = anchorSelection(text, { from: 3, to: 10 }, "source");
  assert.deepEqual([mark.startLine, mark.endLine], [2, 3]);
  assert.deepEqual(resolveMark("新行\n" + text, mark), { from: 6, to: 13 });
  assert.equal(resolveMark(text.replace("焊接", "搬运"), mark), null);
});

test("identical and overlapping marks keep independent identities", () => {
  const text = "甲乙丙丁";
  const marks = [1, 1, 2].map(from => anchorSelection(text, { from, to: 4 }, "preview"));
  assert.equal(new Set(marks.map(m => m.id)).size, 3);
  assert.deepEqual(marks.slice(1).map(m => resolveMark(text, m)), [{ from: 1, to: 4 }, { from: 2, to: 4 }]);
});

test("large selections have bounded anchors and detect changes in the middle", () => {
  const body = "开" + "📖".repeat(10000) + "关";
  const mark = anchorSelection(body, { from: 0, to: body.length }, "source");
  assert.ok(JSON.stringify(mark).length < 450);
  assert.equal(resolveMark(body.slice(0, 101) + "不同" + body.slice(103), mark), null);
  assert.deepEqual(resolveMark("标题" + body, mark), { from: 2, to: 2 + body.length });
});

test("use adjacent context to distinguish repeated words, then nearest old location", () => {
  const text = "序言 abc 甲 abc 乙";
  const from = text.lastIndexOf("abc");
  const mark = anchorSelection(text, { from, to: from + 3 }, "source");
  assert.deepEqual(resolveMark("hello " + text, mark), { from: from + 6, to: from + 9 });
  assert.deepEqual(resolveMark("xabcxabcx", mark), { from: 5, to: 8 });
});
