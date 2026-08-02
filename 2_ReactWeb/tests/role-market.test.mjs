import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";

const vite = await createServer({
  logLevel: "silent",
  server: { middlewareMode: true },
});

const {
  filterRoleMarketRoles,
  listRoleMarketAuthors,
} = await vite.ssrLoadModule(
  "/src/features/role-market/model/roleMarketFilters.ts",
);
const {
  applyInstalledRoleResult,
  filterRoleCategories,
  isRoleMarketActionDisabled,
  LatestRoleMarketRequest,
} = await vite.ssrLoadModule(
  "/src/features/role-market/model/roleMarketOperations.ts",
);

test.after(async () => {
  await vite.close();
});

const roles = [
  {
    id: "writing-assistant",
    name: "写作助手",
    author: "LikeMirage",
    summary: "整理长篇内容",
    installationStatus: "not-installed",
    localProjectId: null,
    localVersion: null,
  },
  {
    id: "reviewer",
    name: "Reviewer",
    author: "Another",
    summary: "Review changes",
    installationStatus: "update-available",
    localProjectId: "local-1",
    localVersion: "1.0.0",
  },
];

test("role market search covers name, id, author, and summary", () => {
  const filters = { authors: [], statuses: [] };
  assert.deepEqual(filterRoleMarketRoles(roles, filters, "writing"), [roles[0]]);
  assert.deepEqual(filterRoleMarketRoles(roles, filters, "LikeMirage"), [roles[0]]);
  assert.deepEqual(filterRoleMarketRoles(roles, filters, "长篇"), [roles[0]]);
});

test("role market filters combine author and installation status", () => {
  assert.deepEqual(filterRoleMarketRoles(roles, {
    authors: ["Another"],
    statuses: ["update-available"],
  }, ""), [roles[1]]);
  assert.deepEqual(listRoleMarketAuthors(roles), ["Another", "LikeMirage"]);
});

test("installed result updates only the matching role status", () => {
  const updated = applyInstalledRoleResult(roles, {
    projectId: "project-2",
    roleId: "writing-assistant",
    version: "1.2.0",
  });
  assert.equal(updated[0].installationStatus, "installed");
  assert.equal(updated[0].localProjectId, "project-2");
  assert.equal(updated[1], roles[1]);
});

test("authoritative update status is not hidden by a prior success phase", () => {
  assert.equal(isRoleMarketActionDisabled("update-available", "success"), false);
  assert.equal(isRoleMarketActionDisabled("installed", "success"), true);
  assert.equal(isRoleMarketActionDisabled("not-installed", "installing"), true);
});

test("category chooser contains role categories only", () => {
  const categories = [
    { category_id: "r", category_kind: "role" },
    { category_id: "t", category_kind: "theme" },
  ];
  assert.deepEqual(filterRoleCategories(categories), [categories[0]]);
});

test("latest request gate rejects stale results", () => {
  const gate = new LatestRoleMarketRequest();
  const stale = gate.begin();
  const latest = gate.begin();
  assert.equal(gate.isCurrent(stale), false);
  assert.equal(gate.isCurrent(latest), true);
});
