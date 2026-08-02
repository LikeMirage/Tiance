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
const { runProjectFolderImportBatch } = await vite.ssrLoadModule(
  "/src/features/project-catalog/model/projectFolderImportBatch.ts",
);

after(async () => {
  await vite.close();
});

test("批量导入会继续处理重复项目和失败项之后的文件夹", async () => {
  const calls = [];
  const result = await runProjectFolderImportBatch(
    ["C:/one", "C:/duplicate", "C:/failed", "C:/two"],
    async (rootPath) => {
      calls.push(rootPath);
      if (rootPath.endsWith("duplicate")) throw new Error("duplicate");
      if (rootPath.endsWith("failed")) throw new Error("failed");
      return { project_id: rootPath };
    },
    (error) => error instanceof Error && error.message === "duplicate"
      ? { projectId: "existing" }
      : null,
  );

  assert.deepEqual(calls, ["C:/one", "C:/duplicate", "C:/failed", "C:/two"]);
  assert.deepEqual(
    result.createdProjects.map((project) => project.project_id),
    ["C:/one", "C:/two"],
  );
  assert.equal(result.conflicts.length, 1);
  assert.equal(result.failures.length, 1);
  assert.equal(result.failures[0].rootPath, "C:/failed");
});

test("批量导入会忽略空路径和完全重复的路径", async () => {
  const calls = [];
  await runProjectFolderImportBatch(
    ["C:/one", " ", "C:/one"],
    async (rootPath) => {
      calls.push(rootPath);
      return { project_id: rootPath };
    },
    () => null,
  );

  assert.deepEqual(calls, ["C:/one"]);
});
