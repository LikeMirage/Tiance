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
const { SessionStreamingRegistry } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/sessionStreamingRegistry.ts",
);

after(async () => {
  await vite.close();
});

test("旧运行的延迟清理不能清除同一会话的新运行", () => {
  const registry = new SessionStreamingRegistry();
  const oldLease = registry.acquire("project:session");
  const newLease = registry.acquire("project:session");

  assert.equal(registry.release("project:session", oldLease), false);
  assert.equal(registry.has("project:session"), true);
  assert.equal(registry.release("project:session", newLease), true);
  assert.equal(registry.has("project:session"), false);
});

test("清理项目只移除该项目的运行状态", () => {
  const registry = new SessionStreamingRegistry();
  registry.acquire("project-a:session-1");
  registry.acquire("project-b:session-1");

  assert.equal(registry.clearProject("project-a"), true);
  assert.deepEqual([...registry.keys()], ["project-b:session-1"]);
});
