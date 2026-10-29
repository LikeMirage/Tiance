import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { ClientToolRequestSingleFlight } = await vite.ssrLoadModule("/src/features/client-tools/model/clientToolRequestSingleFlight.ts");
const { clientToolExecutionStore } = await vite.ssrLoadModule("/src/features/client-tools/model/clientToolExecutionSession.ts");
const { claimClientToolRequest } = await vite.ssrLoadModule("/src/services/llm/claimClientToolRequest.ts");
after(() => vite.close());
const turn = () => new Promise(setImmediate);
const request = (id = "request", timeout = 600) => ({ request_id: id, call_id: id, name: "test", arguments: "{}", timeout_seconds: timeout });
const lease = (overrides = {}) => ({ acquired: true, claim_id: "claim", lease_duration_seconds: 30, resumed: false, ...overrides });
function store() {
  const map = new Map();
  return { read: (id) => map.get(id) ?? null, write: (id, value) => map.set(id, value), remove: (id) => map.delete(id) };
}
function coordinator(options = {}) {
  return new ClientToolRequestSingleFlight({ executorId: "owner", executionStore: store(),
    claimRequest: async () => lease(), renewClaim: async () => true,
    submitResult: async () => ({ accepted: true }), ...options });
}
function clock(t) {
  let now = 0, next = 0;
  const timers = new Map(), intervals = new Map();
  t.mock.method(performance, "now", () => now);
  t.mock.method(globalThis, "setTimeout", (fn, ms) => { const id = ++next; timers.set(id, { fn, at: now + ms }); return id; });
  t.mock.method(globalThis, "clearTimeout", (id) => timers.delete(id));
  t.mock.method(globalThis, "setInterval", (fn) => { const id = ++next; intervals.set(id, fn); return id; });
  t.mock.method(globalThis, "clearInterval", (id) => intervals.delete(id));
  return { timers, intervals, async advance(ms) {
    now += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
    await turn();
  }, async heartbeat() { for (const fn of intervals.values()) fn(); await turn(); } };
}

test("领取接口传递同次领取标识和取消信号", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.match(String(url), /client-tools\/request\/claim$/);
    assert.deepEqual(JSON.parse(init.body), { executor_id: "owner", attempt_id: "attempt" });
    assert.strictEqual(init.signal, controller.signal);
    return new Response(JSON.stringify(lease({ attempt_id: "attempt" })));
  });
  assert.equal((await claimClientToolRequest("request", "owner", { attemptId: "attempt", signal: controller.signal })).attempt_id, "attempt");
});

test("领取失败后同一请求可重放，不缓存 rejected Promise 或产生旁路 rejection", async () => {
  let claims = 0, executions = 0;
  const c = coordinator({ claimRequest: async () => { if (++claims === 1) throw new Error("offline"); return lease(); } });
  const req = request("replay", 0); // Legacy requests without a budget rely on server replay.
  const execute = async () => { executions++; return { ok: true }; };
  await assert.rejects(c.run(req, execute), /offline/);
  await c.run(req, execute);
  await c.run(req, execute);
  await turn();
  assert.equal(claims, 2);
  assert.equal(executions, 1);
});

test("网络恢复自动重试，确认响应丢失时沿用同一领取标识且只执行一次", async (t) => {
  const time = clock(t), attempts = [];
  let executions = 0;
  const c = coordinator({ claimRequest: async (_id, _executor, { attemptId }) => {
    attempts.push(attemptId);
    if (attempts.length === 1) throw new TypeError("response lost after server accepted claim");
    return lease({ resumed: true, attempt_id: attempts[0] });
  } });
  const req = request();
  const execute = async () => { executions++; return { ok: true }; };
  const pending = c.run(req, execute);
  assert.strictEqual(c.run(req, execute), pending);
  await turn();
  assert.equal(attempts.length, 1);
  await time.advance(1000);
  await pending;
  assert.deepEqual(attempts, [attempts[0], attempts[0]]);
  assert.equal(executions, 1);
  assert.equal(time.timers.size + time.intervals.size, 0);
});

test("明确鉴权失败不自动反复请求，恢复后重放仍能领取", async () => {
  let claims = 0, executions = 0;
  const c = coordinator({ claimRequest: async () => {
    if (++claims === 1) throw Object.assign(new Error("login required"), { status: 401 });
    return lease();
  } });
  const execute = async () => { executions++; return { ok: true }; };
  await assert.rejects(c.run(request(), execute), /login/);
  await c.run(request(), execute);
  assert.equal(claims, 2);
  assert.equal(executions, 1);
});

test("重载后恢复尚未开始的领取，存储标识保留；执行状态未知仍不重做", async () => {
  const saved = new Map();
  const previous = globalThis.window;
  globalThis.window = { sessionStorage: { getItem: (key) => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value), removeItem: (key) => saved.delete(key) } };
  try {
    clientToolExecutionStore.write("reload", { state: "claiming", attemptId: "original-attempt" });
    assert.deepEqual(clientToolExecutionStore.read("reload"), { state: "claiming", attemptId: "original-attempt" });
    let executions = 0, submitted;
    const c = coordinator({ executionStore: clientToolExecutionStore,
      claimRequest: async (_id, _owner, options) => { assert.equal(options.attemptId, "original-attempt"); return lease({ resumed: true, attempt_id: options.attemptId }); },
      submitResult: async (_id, result) => { submitted = result; return { accepted: true }; } });
    await c.run(request("reload"), async () => { executions++; return { ok: true }; });
    assert.equal(executions, 1);
    assert.equal(submitted.ok, true);
    const unknown = coordinator({ claimRequest: async () => lease({ resumed: true, attempt_id: "different-old-attempt" }),
      submitResult: async (_id, result) => { submitted = result; return { accepted: true }; } });
    await unknown.run(request("unknown"), async () => { executions++; return { ok: true }; });
    assert.equal(executions, 1);
    assert.equal(submitted.content.error_code, "CLIENT_TOOL_EXECUTION_INTERRUPTED");
  } finally { globalThis.window = previous; }
});

test("取消领取等待会清理重试，之后不会开始执行", async (t) => {
  const time = clock(t);
  let claims = 0, executions = 0;
  const c = coordinator({ claimRequest: async () => { claims++; throw new Error("offline"); } });
  const pending = c.run(request(), async () => { executions++; return { ok: true }; });
  await turn();
  assert.equal(c.cancel("request"), true);
  await pending;
  await time.advance(60_000);
  assert.equal(claims, 1);
  assert.equal(executions, 0);
  assert.equal(time.timers.size, 0);
});

test("领取 HTTP 卡住由工具配置期限取消，重试节奏不是新的超时上限", async (t) => {
  const time = clock(t);
  let signal, executions = 0;
  const c = coordinator({ claimRequest: (_id, _owner, options) => {
    signal = options.signal;
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
  } });
  const pending = c.run(request("request", 600), async () => { executions++; return { ok: true }; });
  await time.advance(599_000);
  assert.equal(signal.aborted, false);
  await time.advance(1000);
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(executions, 0);
  assert.equal(time.timers.size, 0);
});

test("执行期间超过 30 秒且心跳失败不终止工具；心跳请求串行", async (t) => {
  const time = clock(t);
  let release, heartbeats = 0, rejectHeartbeat, signal;
  const execution = new Promise((resolve) => { release = resolve; });
  const c = coordinator({ renewClaim: () => { heartbeats++; return new Promise((_, reject) => { rejectHeartbeat = reject; }); } });
  const pending = c.run(request(), async (_req, ctx) => { signal = ctx.signal; await execution; return { ok: true }; });
  await turn();
  await time.heartbeat();
  for (let i = 0; i < 10; i++) await time.heartbeat();
  assert.equal(heartbeats, 1);
  rejectHeartbeat(new Error("network down"));
  await time.advance(120_000);
  assert.equal(signal.aborted, false);
  release();
  await pending;
  assert.equal(time.timers.size + time.intervals.size, 0);
});

test("执行本身也遵循工具配置期限，不重试动作", async (t) => {
  const time = clock(t);
  let signal, result, executions = 0;
  const c = coordinator({ submitResult: async (_id, value) => { result = value; return { accepted: false }; } });
  const pending = c.run(request("request", 180), async (_req, ctx) => { executions++; signal = ctx.signal; return new Promise(() => {}); });
  await turn();
  await time.advance(179_000);
  assert.equal(signal.aborted, false);
  await time.advance(1000);
  await pending;
  assert.equal(signal.aborted, true);
  assert.match(result.error, /超时/);
  assert.equal(executions, 1);
  assert.equal(time.timers.size + time.intervals.size, 0);
});
