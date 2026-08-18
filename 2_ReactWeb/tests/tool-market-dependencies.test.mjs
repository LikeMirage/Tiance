import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("tool market dependency prompt uses the backend result and opens the installed tool dashboard", async () => {
  const marketSource = await readFile(
    new URL("../src/features/tool-market/ui/ToolMarketBoard.tsx", import.meta.url),
    "utf8",
  );
  const workspaceSource = await readFile(
    new URL("../src/pages/workspace/ui/WorkspaceToolCanvasPanel.tsx", import.meta.url),
    "utf8",
  );

  assert.match(marketSource, /result\?\.hasDependencies/);
  assert.match(marketSource, /onOpenDependencies\?\.\(target\)/);
  assert.match(workspaceSource, /activeView: "dependencies"/);
  assert.match(workspaceSource, /dependencyTarget\.projectId/);
  assert.match(workspaceSource, /dependencyTarget\.categoryId/);
});

test("dependency dashboard documents the isolated install location and responds to its own width", async () => {
  const dashboardSource = await readFile(
    new URL("../src/features/tool-dependencies-dashboard/ui/ToolDependenciesDashboard.tsx", import.meta.url),
    "utf8",
  );
  const styleSource = await readFile(
    new URL("../src/features/tool-dependencies-dashboard/ui/tool-dependencies-dashboard.css", import.meta.url),
    "utf8",
  );

  assert.match(dashboardSource, /dependencies\/py313\//);
  assert.match(dashboardSource, /<ul className="tool-dependencies-dashboard__description">/);
  assert.match(styleSource, /container-type:\s*inline-size/);
  assert.match(styleSource, /@container\s*\(max-width:\s*720px\)/);
});
