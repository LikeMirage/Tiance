import type { ConversationRuntimeStatus } from "./conversation";

type RuntimeFact = {
  project_id: string;
  session_id: string;
  run_id: string;
  phase: "running" | "stopping" | "idle" | "error";
  output_seq: number;
};
type RuntimeEvent = { kind: "snapshot" | "changed"; runs: RuntimeFact[] };
const keyOf = (projectId: string, sessionId: string) => `${projectId}:${sessionId}`;

/** Execution state and output activity are separate subscriptions. Silence never ends a run. */
export class ConversationRuntimeStore {
  private facts = new Map<string, RuntimeFact>();
  private local = new Map<string, Set<symbol>>();
  private ready = false;
  private version = 0;
  private listeners = new Set<() => void>();
  private outputListeners = new Map<string, Set<() => void>>();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  getSnapshot = () => this.version;
  private changed() {
    this.version += 1;
    this.listeners.forEach((listener) => listener());
  }

  receive(event: RuntimeEvent) {
    if (!event || !["snapshot", "changed"].includes(event.kind) || !Array.isArray(event.runs)) return;
    const previous = this.facts;
    const next = event.kind === "snapshot" ? new Map<string, RuntimeFact>() : new Map(previous);
    let changed = event.kind === "snapshot";
    for (const fact of event.runs) {
      if (!fact || typeof fact.project_id !== "string" || typeof fact.session_id !== "string"
        || typeof fact.run_id !== "string" || !["running", "stopping", "idle", "error"].includes(fact.phase)) continue;
      const key = keyOf(fact.project_id, fact.session_id);
      const old = previous.get(key);
      next.set(key, fact);
      changed ||= old?.phase !== fact.phase || old?.run_id !== fact.run_id;
      // A reconnect snapshot must not pretend that replayed output is arriving now.
      if (event.kind !== "snapshot" && fact.phase === "running"
        && fact.output_seq > (old?.run_id === fact.run_id ? old.output_seq : 0)) {
        this.outputListeners.get(key)?.forEach((listener) => listener());
      }
    }
    this.facts = next;
    if (event.kind === "snapshot") this.ready = true;
    if (changed) this.changed();
  }

  status(projectId: string, sessionId: string, fallback: ConversationRuntimeStatus): ConversationRuntimeStatus {
    const key = keyOf(projectId, sessionId);
    if (this.local.has(key)) return "running";
    const fact = this.facts.get(key);
    if (fact) return fact.phase === "stopping" ? "running" : fact.phase;
    return this.ready && fallback === "running" ? "idle" : fallback;
  }

  // Local submission/stream settlement must finish before this client can submit again.
  acquire(key: string, lease: symbol) {
    const owners = this.local.get(key) ?? new Set<symbol>();
    owners.add(lease);
    this.local.set(key, owners);
    this.changed();
  }
  release(key: string, lease: symbol) {
    const owners = this.local.get(key);
    if (!owners?.delete(lease)) return;
    if (!owners.size) this.local.delete(key);
    this.changed();
  }
  subscribeOutput(projectId: string, sessionId: string, listener: () => void) {
    const key = keyOf(projectId, sessionId);
    const listeners = this.outputListeners.get(key) ?? new Set<() => void>();
    listeners.add(listener);
    this.outputListeners.set(key, listeners);
    return () => {
      listeners.delete(listener);
      if (!listeners.size) this.outputListeners.delete(key);
    };
  }
}

export const conversationRuntime = new ConversationRuntimeStore();
