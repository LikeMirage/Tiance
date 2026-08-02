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
const { resolveProjectOverviewTarget } = await vite.ssrLoadModule(
  "/src/features/project-category-overview/model/projectOverviewTarget.ts",
);

after(async () => {
  await vite.close();
});

test("会话总览优先沿用当前可见会话而不是历史项目", () => {
  const target = resolveProjectOverviewTarget(
    [project("project-5"), project("project-6")],
    { projectId: "project-5", sessionId: "session-5" },
    "project-6",
  );

  assert.deepEqual(target, {
    projectId: "project-5",
    sessionId: "session-5",
  });
});

test("没有当前分类会话时才使用历史项目", () => {
  const target = resolveProjectOverviewTarget(
    [project("project-5"), project("project-6")],
    { projectId: "outside-project", sessionId: "outside-session" },
    "project-6",
  );

  assert.deepEqual(target, {
    projectId: "project-6",
    sessionId: null,
  });
});

test("当前会话和历史项目都无效时使用分类第一项", () => {
  const target = resolveProjectOverviewTarget(
    [project("project-5"), project("project-6")],
    null,
    "missing-project",
  );

  assert.deepEqual(target, {
    projectId: "project-5",
    sessionId: null,
  });
});

function project(projectId) {
  return { project_id: projectId };
}
