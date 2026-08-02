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
const { ClientToolRequestSingleFlight } = await vite.ssrLoadModule(
  "/src/features/client-tools/model/clientToolRequestSingleFlight.ts",
);

after(async () => {
  await vite.close();
});

test("并发收到同一 request_id 时执行与提交都只有一次", async () => {
  let executeCount = 0;
  let submitCount = 0;
  let releaseExecution;
  const executionBlocked = new Promise((resolve) => {
    releaseExecution = resolve;
  });
  const coordinator = createCoordinator(async () => {
    submitCount += 1;
    return { accepted: true };
  });
  const executor = async () => {
    executeCount += 1;
    await executionBlocked;
    return { ok: true, content: { value: "done" } };
  };

  const first = coordinator.run(request("concurrent"), executor);
  const replay = coordinator.run(request("concurrent"), executor);

  assert.strictEqual(replay, first);
  await Promise.resolve();
  assert.equal(executeCount, 1);
  releaseExecution();
  await Promise.all([first, replay]);
  assert.equal(executeCount, 1);
  assert.equal(submitCount, 1);
});

test("请求完成后的紧随重放复用已完成结果", async () => {
  let executeCount = 0;
  let submitCount = 0;
  const coordinator = createCoordinator(async () => {
    submitCount += 1;
    return { accepted: true };
  });
  const executor = async () => {
    executeCount += 1;
    return { ok: true };
  };
  const original = coordinator.run(request("completed"), executor);
  await original;

  const replay = coordinator.run(request("completed"), executor);
  await replay;
  assert.equal(executeCount, 1);
  assert.equal(submitCount, 1);
});

test("第一次提交失败后重放复用结果并提交成功", async () => {
  let executeCount = 0;
  let submitCount = 0;
  const submitError = new Error("submit failed");
  const coordinator = createCoordinator(async () => {
    submitCount += 1;
    if (submitCount === 1) throw submitError;
    return { accepted: true };
  });
  const executor = async () => {
    executeCount += 1;
    return { ok: true };
  };
  const original = coordinator.run(request("submit-failed"), executor);
  await assert.rejects(original, submitError);

  const replay = coordinator.run(request("submit-failed"), executor);
  await replay;
  assert.equal(executeCount, 1);
  assert.equal(submitCount, 2);
});

test("连续提交失败仍然只执行工具一次", async () => {
  let executeCount = 0;
  let submitCount = 0;
  const submitError = new Error("still unavailable");
  const coordinator = createCoordinator(async () => {
    submitCount += 1;
    throw submitError;
  });
  const executor = async () => {
    executeCount += 1;
    return { ok: true };
  };
  const pendingRequest = request("repeated-submit-failure");

  await assert.rejects(coordinator.run(pendingRequest, executor), submitError);
  await assert.rejects(coordinator.run(pendingRequest, executor), submitError);
  await assert.rejects(coordinator.run(pendingRequest, executor), submitError);

  assert.equal(executeCount, 1);
  assert.equal(submitCount, 3);
});

test("accepted=false 表示服务端请求已关闭且不会继续提交", async () => {
  let executeCount = 0;
  let submitCount = 0;
  const coordinator = createCoordinator(async () => {
    submitCount += 1;
    return { accepted: false };
  });
  const executor = async () => {
    executeCount += 1;
    return { ok: true };
  };
  const pendingRequest = request("closed-request");

  await coordinator.run(pendingRequest, executor);
  await coordinator.run(pendingRequest, executor);

  assert.equal(executeCount, 1);
  assert.equal(submitCount, 1);
});

test("已执行结果长期保留并按有界 LRU 淘汰", async () => {
  const executionCounts = new Map();
  const coordinator = new ClientToolRequestSingleFlight({
    maxCompletedResults: 2,
    submitResult: async () => ({ accepted: true }),
  });
  const executor = async (pendingRequest) => {
    const requestId = pendingRequest.request_id;
    executionCounts.set(requestId, (executionCounts.get(requestId) ?? 0) + 1);
    return { ok: true };
  };

  await coordinator.run(request("lru-a"), executor);
  await coordinator.run(request("lru-b"), executor);
  await new Promise((resolve) => setTimeout(resolve, 40));
  await coordinator.run(request("lru-a"), executor);
  await coordinator.run(request("lru-c"), executor);
  await coordinator.run(request("lru-a"), executor);
  await coordinator.run(request("lru-b"), executor);

  assert.equal(executionCounts.get("lru-a"), 1);
  assert.equal(executionCounts.get("lru-b"), 2);
  assert.equal(executionCounts.get("lru-c"), 1);
});

function createCoordinator(submitResult) {
  return new ClientToolRequestSingleFlight({
    submitResult,
  });
}

function request(requestId) {
  return {
    request_id: requestId,
    call_id: `call-${requestId}`,
    name: "generic_client_tool",
    arguments: "{}",
    timeout_seconds: 0,
  };
}
