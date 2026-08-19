import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const { toggleDeleteTreeSelection } = await vite.ssrLoadModule(
  "/src/features/project-category-overview/ui/ProjectConversationDeleteModal.tsx",
);

after(async () => {
  await vite.close();
});

test("根会话保持选中，同时可一次选择全部后代", () => {
  const result = toggleDeleteTreeSelection(
    new Set(["root"]),
    ["root", "child-a", "grandchild-a", "child-b"],
    "root",
  );

  assert.deepEqual(
    [...result],
    ["root", "child-a", "grandchild-a", "child-b"],
  );
});

test("再次点击根会话只取消全部后代，根会话仍必须删除", () => {
  const result = toggleDeleteTreeSelection(
    new Set(["root", "child-a", "grandchild-a", "child-b"]),
    ["root", "child-a", "grandchild-a", "child-b"],
    "root",
  );

  assert.deepEqual([...result], ["root"]);
});

test("部分选择时点击根会话会补全整个分支树", () => {
  const result = toggleDeleteTreeSelection(
    new Set(["root", "child-a"]),
    ["root", "child-a", "grandchild-a", "child-b"],
    "root",
  );

  assert.deepEqual(
    [...result],
    ["root", "child-a", "grandchild-a", "child-b"],
  );
});

test("分支树默认只展开当前会话一级，并允许逐级展开", async () => {
  const source = await readFile(
    new URL(
      "../src/features/project-category-overview/ui/ProjectConversationDeleteModal.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /defaultExpanded=\{node\.sessionId === sessionId\}/);
  assert.match(source, /expanded && node\.children\.length > 0/);
  assert.match(source, /onClick=\{\(\) => setExpanded/);
});
