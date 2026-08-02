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
const { parseProjectWorkspaceEvent } = await vite.ssrLoadModule(
  "/src/services/project/watchProjectWorkspaceEvents.ts",
);

after(async () => {
  await vite.close();
});

test("项目工作区事件只接受稳定的 ready 和 changed 合同", () => {
  assert.deepEqual(parseProjectWorkspaceEvent('{"kind":"ready"}'), {
    kind: "ready",
    paths: undefined,
  });
  assert.deepEqual(
    parseProjectWorkspaceEvent(
      '{"kind":"changed","paths":["new-project/.Tiance/project.json"]}',
    ),
    { kind: "changed", paths: ["new-project/.Tiance/project.json"] },
  );
  assert.equal(parseProjectWorkspaceEvent('{"kind":"changed","paths":[1]}'), null);
  assert.equal(parseProjectWorkspaceEvent('{"kind":"unknown"}'), null);
  assert.equal(parseProjectWorkspaceEvent("not-json"), null);
});
