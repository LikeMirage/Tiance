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
const { buildModelSwitches } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/chatModelTransitions.ts",
);

after(async () => {
  await vite.close();
});

test("只在实际消息模型变化时生成切换标记", () => {
  const switches = buildModelSwitches([
    message({ id: "user-a", role: "user", targetModelId: "model-a" }),
    message({ id: "assistant-a", modelId: "model-a" }),
    message({ id: "tool-without-model", role: "tool" }),
    message({ id: "user-b", role: "user", targetModelId: "model-b" }),
    message({ id: "assistant-b", modelId: "model-b" }),
  ]);

  assert.deepEqual([...switches], [["user-b", "model-b"]]);
});

test("忽略空模型并以用户消息的目标模型为准", () => {
  const switches = buildModelSwitches([
    message({ id: "assistant-a", modelId: " model-a " }),
    message({ id: "unknown", modelId: "" }),
    message({
      id: "user-b",
      role: "user",
      modelId: "stale-model",
      targetModelId: "model-b",
    }),
  ]);

  assert.deepEqual([...switches], [["user-b", "model-b"]]);
});

function message(overrides) {
  return {
    id: "message",
    role: "assistant",
    content: "",
    thinkingContent: "",
    status: "done",
    usage: null,
    isThinkingExpanded: false,
    thinkingStartedAt: null,
    thinkingFinishedAt: null,
    ...overrides,
  };
}
