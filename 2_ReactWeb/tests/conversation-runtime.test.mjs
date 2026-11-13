import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
const { ConversationRuntimeStore, conversationRuntime } = await vite.ssrLoadModule(
  "/src/entities/llm-chat/model/conversationRuntime.ts",
);
const { projectOverviewRuntime } = await vite.ssrLoadModule(
  "/src/features/project-category-overview/model/projectOverviewRuntime.ts",
);
const { SessionStreamingRegistry } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/sessionStreamingRegistry.ts",
);
after(() => vite.close());
const fact = (phase = "running", output_seq = 0, run_id = "run-1") => ({
  project_id: "project", session_id: "session", run_id, phase, output_seq,
});

test("actual task stays running across a silent upstream wait and stale list responses", () => {
  const store = new ConversationRuntimeStore();
  store.receive({ kind: "snapshot", runs: [fact()] });
  for (const persisted of ["idle", "error", "running"]) {
    assert.equal(store.status("project", "session", persisted), "running");
  }
  store.receive({ kind: "changed", runs: [fact("stopping")] });
  assert.equal(store.status("project", "session", "idle"), "running");
  store.receive({ kind: "changed", runs: [fact("idle")] });
  assert.equal(store.status("project", "session", "running"), "idle");
});

test("output pulses do not re-render the dashboard or masquerade as state changes", () => {
  const store = new ConversationRuntimeStore();
  let renders = 0, pulses = 0;
  store.subscribe(() => renders++);
  const unsubscribe = store.subscribeOutput("project", "session", () => pulses++);
  store.receive({ kind: "snapshot", runs: [fact("running", 900)] });
  assert.equal(pulses, 0);
  const initialRenders = renders;
  for (let seq = 901; seq <= 1000; seq++) store.receive({ kind: "changed", runs: [fact("running", seq)] });
  assert.equal(pulses, 100);
  assert.equal(renders, initialRenders);
  store.receive({ kind: "changed", runs: [fact("running", 1000)] });
  assert.equal(pulses, 100);
  unsubscribe();
  store.receive({ kind: "changed", runs: [fact("running", 1001)] });
  assert.equal(pulses, 100);
});

test("reconnect clears stale activity without replaying output and preserves stored errors", () => {
  const store = new ConversationRuntimeStore();
  store.receive({ kind: "snapshot", runs: [fact()] });
  store.receive({ kind: "snapshot", runs: [] });
  assert.equal(store.status("project", "session", "running"), "idle");
  assert.equal(store.status("project", "other", "error"), "error");
});

test("submit and settlement leases override late terminal events until the local request finishes", () => {
  const store = new ConversationRuntimeStore();
  store.receive({ kind: "snapshot", runs: [] });
  const lease = Symbol();
  store.acquire("project:session", lease);
  store.receive({ kind: "changed", runs: [fact("idle")] });
  assert.equal(store.status("project", "session", "idle"), "running");
  store.release("project:session", Symbol());
  assert.equal(store.status("project", "session", "idle"), "running");
  store.release("project:session", lease);
  assert.equal(store.status("project", "session", "running"), "idle");
});

test("chat streaming, session dots and project counters use the same active task", () => {
  conversationRuntime.receive({ kind: "snapshot", runs: [] });
  const leases = new SessionStreamingRegistry();
  const lease = leases.acquire("project:session");
  const overview = { project: { project_id: "project" }, sessions: [
    { session_id: "session", runtime_status: "idle" },
    { session_id: "old", runtime_status: "running" },
    { session_id: "failed", runtime_status: "error" },
  ] };
  let projected = projectOverviewRuntime(overview);
  assert.deepEqual([projected.active_count, projected.idle_count, projected.error_count], [1, 1, 1]);
  assert.equal(projected.sessions[0].runtime_status, "running");
  leases.release("project:session", lease);
  projected = projectOverviewRuntime(overview);
  assert.deepEqual([projected.active_count, projected.idle_count, projected.error_count], [0, 2, 1]);
  assert.equal(overview.sessions[1].runtime_status, "running");
});

test("retry and a subsequent task may restart output counters without losing pulses", () => {
  const store = new ConversationRuntimeStore();
  let pulses = 0;
  store.subscribeOutput("project", "session", () => pulses++);
  store.receive({ kind: "snapshot", runs: [fact("running", 500)] });
  store.receive({ kind: "changed", runs: [fact("error", 500)] });
  assert.equal(store.status("project", "session", "idle"), "error");
  store.receive({ kind: "changed", runs: [fact("running", 1, "run-2")] });
  assert.equal(store.status("project", "session", "idle"), "running");
  assert.equal(pulses, 1);
});
