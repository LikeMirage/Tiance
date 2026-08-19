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

test("调用会话取消后立即停止等待且不伪装已开始动作被回滚", async () => {
  let receivedSignal;
  let submittedResult;
  const coordinator = createCoordinator(async (_requestId, result) => {
    submittedResult = result;
    return { accepted: false };
  });
  const pending = coordinator.run(request("cancelled-wait"), async (_request, context) => {
    receivedSignal = context.signal;
    await new Promise(() => undefined);
    return { ok: true };
  });

  await Promise.resolve();
  await Promise.resolve();
  assert.equal(coordinator.cancel("cancelled-wait"), true);
  await pending;

  assert.equal(receivedSignal.aborted, true);
  assert.equal(submittedResult.ok, false);
  assert.match(submittedResult.error, /停止等待/);
});

test("已执行结果长期保留并按有界 LRU 淘汰", async () => {
  const executionCounts = new Map();
  const coordinator = new ClientToolRequestSingleFlight({
    maxCompletedResults: 2,
    executorId: "frontend-test",
    executionStore: createExecutionStore(),
    claimRequest: async () => claimLease(),
    renewClaim: async () => true,
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

test("前端重载后不重复执行结果未知的动作", async () => {
  let executeCount = 0;
  let submittedResult;
  const executionStore = createExecutionStore();
  executionStore.write("interrupted", { state: "executing" });
  const coordinator = new ClientToolRequestSingleFlight({
    executorId: "frontend-reloaded",
    executionStore,
    claimRequest: async () => claimLease({ resumed: true }),
    renewClaim: async () => true,
    submitResult: async (_requestId, result) => {
      submittedResult = result;
      return { accepted: true };
    },
  });

  await coordinator.run(request("interrupted"), async () => {
    executeCount += 1;
    return { ok: true };
  });

  assert.equal(executeCount, 0);
  assert.equal(submittedResult.ok, false);
  assert.equal(
    submittedResult.content.error_code,
    "CLIENT_TOOL_EXECUTION_INTERRUPTED",
  );
});

function createCoordinator(submitResult) {
  return new ClientToolRequestSingleFlight({
    executorId: "frontend-test",
    executionStore: createExecutionStore(),
    claimRequest: async () => claimLease(),
    renewClaim: async () => true,
    submitResult,
  });
}

function claimLease(overrides = {}) {
  return {
    acquired: true,
    claim_id: "claim-test",
    lease_duration_seconds: 30,
    resumed: false,
    ...overrides,
  };
}

function createExecutionStore() {
  const records = new Map();
  return {
    read(requestId) {
      return records.get(requestId) ?? null;
    },
    write(requestId, record) {
      records.set(requestId, record);
    },
    remove(requestId) {
      records.delete(requestId);
    },
  };
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
