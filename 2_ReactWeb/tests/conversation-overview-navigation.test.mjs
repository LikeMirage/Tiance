import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "vite";
import React from "react";
import { act, create } from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ server: { middlewareMode: true }, appType: "custom", logLevel: "error" });
after(() => vite.close());
const { useConversationOverviewNavigation } = await vite.ssrLoadModule("/src/pages/workspace/model/useConversationOverviewNavigation.ts");
const { useCollectionOverviewNavigation } = await vite.ssrLoadModule("/src/pages/workspace/model/useCollectionOverviewNavigation.ts");
const { useToolOverviewNavigation } = await vite.ssrLoadModule("/src/pages/workspace/model/useToolOverviewNavigation.ts");
const { WORKSPACE_LAYOUT_DEFAULTS } = await vite.ssrLoadModule("/src/entities/workspace/model/workspaceLayoutPreferences.ts");

for (const kind of ["project", "role", "theme", "provider", "tool"]) {
  test(`${kind} overview preserves outer scope and opens inner tab only after entering project`, async () => {
    let open, renderer;
    const updates = [], tabs = [];
    const onLayoutPreferenceChange = value => updates.push(value);
    function Harness({ expandedProjectId }) {
      const common = {
        categoryId: "category", selectedToolsetId: "category",
        layoutPreferences: WORKSPACE_LAYOUT_DEFAULTS, onLayoutPreferenceChange,
        onSelectProject: () => { throw new Error("navigation must not reselect or enter a project"); },
        projects: [], selectedProjectId: "project",
      };
      const collection = useCollectionOverviewNavigation(common);
      const tool = useToolOverviewNavigation(common);
      open = useConversationOverviewNavigation({
        categoryId: "category", projectId: "project", expandedProjectId,
        openProjectOverview: (...args) => tabs.push(args),
        onLayoutPreferenceChange: kind === "project" ? onLayoutPreferenceChange
          : kind === "tool" ? tool.handleCommonLayoutPreferenceChange
          : collection.handleCommonLayoutPreferenceChange,
      });
      return null;
    }
    await act(async () => { renderer = create(React.createElement(Harness, { expandedProjectId: null })); });
    open();
    assert.equal(tabs.length, 0);
    assert.deepEqual(updates[0].projectOverviewView, { categoryId: "category", view: "conversation" });
    assert.deepEqual(updates[0].projectOverviewMaximized, { categoryId: "category", projectId: "project" });
    if (kind === "tool") assert.equal(updates[0].toolOverviewView.view, "conversation");
    else if (kind !== "project") assert.equal(updates[0].collectionOverviewView.view, "conversation");
    await act(async () => { renderer.update(React.createElement(Harness, { expandedProjectId: "project" })); });
    open();
    assert.equal(updates.length, 1);
    assert.deepEqual(tabs, [["project", { activate: true }]]);
    await act(async () => renderer.unmount());
  });
}
