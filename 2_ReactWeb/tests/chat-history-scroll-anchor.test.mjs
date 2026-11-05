import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(fs.readFileSync(new URL(
  "../src/features/ai-panel/model/chatHistoryScrollAnchor.ts", import.meta.url), "utf8"),
{ compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const module = { exports: {} };
vm.runInThisContext(`(function(module,exports){${source}\n})`)(module, module.exports);
const { captureHistoryScrollAnchor } = module.exports;

function viewport() {
  let precedingHeight = 0, processHeight = 50, connected = true;
  const parent = { scrollTop: 100, getBoundingClientRect: () => ({ top: 20, bottom: 520 }),
    querySelectorAll: () => [row], contains: () => connected };
  const body = { getBoundingClientRect: () => ({
    top: 20 + precedingHeight + processHeight - parent.scrollTop,
    bottom: 20 + precedingHeight + processHeight + 800 - parent.scrollTop,
  }) };
  const row = { querySelector: () => body, getBoundingClientRect: () => ({
    top: 20 + precedingHeight - parent.scrollTop, bottom: body.getBoundingClientRect().bottom,
  }) };
  return { parent, body, prepend: (height) => { precedingHeight += height; },
    expand: (height) => { processHeight += height; }, remove: () => { connected = false; } };
}

test("prepending a user message keeps the same reply at the same reading position", () => {
  const v = viewport(), original = v.body.getBoundingClientRect().top;
  const restore = captureHistoryScrollAnchor(v.parent);
  v.prepend(240); restore();
  assert.equal(v.parent.scrollTop, 340);
  assert.equal(v.body.getBoundingClientRect().top, original);
  restore(); assert.equal(v.parent.scrollTop, 340, "repeated layout effects cannot apply the shift twice");
  v.prepend(60); restore();
  assert.equal(v.body.getBoundingClientRect().top, original, "late Markdown layout also retains the anchor");
});

test("user scrolling while history loads is preserved, including shifts inside the reply", () => {
  const v = viewport(), original = v.body.getBoundingClientRect().top;
  const restore = captureHistoryScrollAnchor(v.parent);
  v.parent.scrollTop -= 40;
  v.expand(90); restore();
  assert.equal(v.parent.scrollTop, 150);
  assert.equal(v.body.getBoundingClientRect().top, original + 40);
});

test("discarded history and empty viewports do not restore stale scroll positions", () => {
  const v = viewport(), restore = captureHistoryScrollAnchor(v.parent);
  v.remove(); v.prepend(300); restore();
  assert.equal(v.parent.scrollTop, 100);
  assert.equal(captureHistoryScrollAnchor({ ...v.parent, querySelectorAll: () => [] }), null);
});
