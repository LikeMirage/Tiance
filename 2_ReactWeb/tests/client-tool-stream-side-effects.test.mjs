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
const { processChatStreamEventSideEffects } = await vite.ssrLoadModule(
  "/src/features/conversation-runtime/model/chatStreamEventSideEffects.ts",
);

const originalFetch = globalThis.fetch;
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.endsWith("/claim")) {
    return new Response(JSON.stringify({
      acquired: true,
      claim_id: `claim-${url}`,
      lease_duration_seconds: 30,
      resumed: false,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (url.endsWith("/result")) {
    return new Response(JSON.stringify({ accepted: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  throw new Error(`Unexpected request: ${url}`);
};

after(async () => {
  globalThis.fetch = originalFetch;
  await vite.close();
});

test("多个客户端工具请求不会互相阻塞事件流", async () => {
  let executeCount = 0;
  let releaseExecution;
  const blocked = new Promise((resolve) => {
    releaseExecution = resolve;
  });
  const executor = async () => {
    executeCount += 1;
    await blocked;
    return { ok: true };
  };

  await processChatStreamEventSideEffects(clientToolEvent("request-1"), executor);
  await processChatStreamEventSideEffects(clientToolEvent("request-2"), executor);
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(executeCount, 2);
  releaseExecution();
  await new Promise((resolve) => setImmediate(resolve));
});

function clientToolEvent(requestId) {
  return {
    kind: "client_tool_request",
    client_tool_request: {
      request_id: requestId,
      call_id: `call-${requestId}`,
      name: "generic_client_tool",
      arguments: "{}",
      timeout_seconds: 60,
    },
  };
}
