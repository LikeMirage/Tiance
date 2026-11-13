import { conversationRuntime } from "../../../entities/llm-chat/model/conversationRuntime";

export type SessionStreamingLease = symbol;

/**
 * Tracks which run currently owns the local streaming state for each session.
 * A late cleanup from an older run must not clear a newer run's state.
 */
export class SessionStreamingRegistry {
  private readonly leases = new Map<string, SessionStreamingLease>();

  acquire(sessionKey: string): SessionStreamingLease {
    const lease = Symbol(sessionKey);
    const previous = this.leases.get(sessionKey);
    conversationRuntime.acquire(sessionKey, lease);
    if (previous) conversationRuntime.release(sessionKey, previous);
    this.leases.set(sessionKey, lease);
    return lease;
  }

  release(sessionKey: string, lease: SessionStreamingLease): boolean {
    if (this.leases.get(sessionKey) !== lease) return false;
    this.leases.delete(sessionKey);
    conversationRuntime.release(sessionKey, lease);
    return true;
  }

  has(sessionKey: string): boolean {
    return this.leases.has(sessionKey);
  }

  clearProject(projectId: string): boolean {
    const prefix = `${projectId}:`;
    let changed = false;
    for (const sessionKey of this.leases.keys()) {
      if (!sessionKey.startsWith(prefix)) continue;
      conversationRuntime.release(sessionKey, this.leases.get(sessionKey)!);
      this.leases.delete(sessionKey);
      changed = true;
    }
    return changed;
  }

  keys(): Set<string> {
    return new Set(this.leases.keys());
  }
}
