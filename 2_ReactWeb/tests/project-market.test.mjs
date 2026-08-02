import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createServer } from "vite";

const vite = await createServer({
  logLevel: "silent",
  server: { middlewareMode: true },
});

const {
  filterProjectMarketCategories,
  filterProjectMarketProjects,
  isProjectMarketInstallActive,
  listProjectMarketAuthors,
  listProjectMarketTags,
} = await vite.ssrLoadModule(
  "/src/features/project-market/model/projectMarketOperations.ts",
);

test.after(async () => {
  await vite.close();
});

const projects = [
  {
    author: "LikeMirage",
    id: "workflow-demo",
    installationStatus: "not-installed",
    name: "工作流示例",
    summary: "包含完整会话和记忆",
    tags: ["workflow", "memory"],
  },
  {
    author: "Another",
    id: "writing-demo",
    installationStatus: "installed",
    name: "Writing",
    summary: "Document project",
    tags: ["document"],
  },
];

test("project market search and real index filters combine correctly", () => {
  assert.deepEqual(filterProjectMarketProjects(projects, {
    authors: ["LikeMirage"],
    statuses: ["not-installed"],
    tags: ["memory"],
  }, "会话"), [projects[0]]);
  assert.deepEqual(filterProjectMarketProjects(projects, {
    authors: [], statuses: [], tags: [],
  }, "document"), [projects[1]]);
});

test("project market derives author and tag options from index data", () => {
  assert.deepEqual(listProjectMarketAuthors(projects), ["Another", "LikeMirage"]);
  assert.deepEqual(listProjectMarketTags(projects), ["document", "memory", "workflow"]);
});

test("project install chooser contains ordinary project categories only", () => {
  const categories = [
    { category_id: "project", category_kind: "project" },
    { category_id: "knowledge", category_kind: "knowledge" },
    { category_id: "experience", category_kind: "experience" },
    { category_id: "theme", category_kind: "theme" },
  ];
  assert.deepEqual(filterProjectMarketCategories(categories, "project"), [categories[0]]);
  assert.deepEqual(filterProjectMarketCategories(categories, "knowledge"), [categories[1]]);
  assert.deepEqual(filterProjectMarketCategories(categories, "experience"), [categories[2]]);
});

test("all backend work phases disable duplicate installation", () => {
  for (const phase of ["queued", "downloading", "extracting", "importing"]) {
    assert.equal(isProjectMarketInstallActive(phase), true);
  }
  assert.equal(isProjectMarketInstallActive("completed"), false);
  assert.equal(isProjectMarketInstallActive("failed"), false);
});

test("project market uses backend default source and operation polling contracts", async () => {
  const apiSource = await readFile(
    new URL("../src/services/project-market/projectMarketApi.ts", import.meta.url),
    "utf8",
  );
  assert.match(apiSource, /\/api\/projects\/market/);
  assert.match(apiSource, /\/api\/knowledge\/market/);
  assert.match(apiSource, /\/api\/experience\/market/);
  assert.match(apiSource, /restore-default/);
  assert.match(apiSource, /operations/);
  assert.doesNotMatch(apiSource, /LikeMirage\/Tiance-projects/);
});

test("online project view does not require activating a project target", async () => {
  const keepAliveSource = await readFile(
    new URL("../src/pages/workspace/ui/ProjectCategoryOverviewKeepAlive.tsx", import.meta.url),
    "utf8",
  );
  assert.match(keepAliveSource, /view === "projects" \|\| view === "online"/);
  assert.match(keepAliveSource, /categoryOverviewView === "online"/);
  assert.match(keepAliveSource, /marketScope=\{marketScope/);
});

test("workspace exposes the matching online market for project collections", async () => {
  const canvasSource = await readFile(
    new URL("../src/pages/workspace/ui/WorkspaceCanvasPanel.tsx", import.meta.url),
    "utf8",
  );
  const tabsSource = await readFile(
    new URL("../src/features/project-category-overview/ui/ProjectOverviewViewTabs.tsx", import.meta.url),
    "utf8",
  );
  assert.match(canvasSource, /projectMarketScope="project"/);
  assert.match(canvasSource, /projectMarketScope="knowledge"/);
  assert.match(canvasSource, /projectMarketScope="experience"/);
  assert.match(tabsSource, /projectOverview\.views\.onlineKnowledge/);
  assert.match(tabsSource, /projectOverview\.views\.onlineExperience/);
});
