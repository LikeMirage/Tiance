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
const { parseThemeWorkspaceEvent } = await vite.ssrLoadModule(
  "/src/services/theme/watchThemeWorkspaceEvents.ts",
);

after(async () => {
  await vite.close();
});

test("主题工作区事件只接受稳定的 ready 和 changed 合同", () => {
  assert.deepEqual(parseThemeWorkspaceEvent('{"kind":"ready"}'), {
    kind: "ready",
    paths: undefined,
  });
  assert.deepEqual(
    parseThemeWorkspaceEvent('{"kind":"changed","paths":["cloud-gate/theme.json"]}'),
    { kind: "changed", paths: ["cloud-gate/theme.json"] },
  );
  assert.equal(parseThemeWorkspaceEvent('{"kind":"changed","paths":[1]}'), null);
  assert.equal(parseThemeWorkspaceEvent('{"kind":"unknown"}'), null);
  assert.equal(parseThemeWorkspaceEvent("not-json"), null);
});
