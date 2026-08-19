import type { ClientToolExecutionResult } from "./clientToolBridge";

const EXECUTOR_ID_KEY = "tiance.client-tool-executor-id";
const EXECUTION_KEY_PREFIX = "tiance.client-tool-execution:";

export type ClientToolExecutionRecord =
  | { state: "executing" }
  | { state: "completed"; result: ClientToolExecutionResult };

export type ClientToolExecutionStore = {
  read(requestId: string): ClientToolExecutionRecord | null;
  write(requestId: string, record: ClientToolExecutionRecord): void;
  remove(requestId: string): void;
};

let memoryExecutorId: string | null = null;
const memoryRecords = new Map<string, ClientToolExecutionRecord>();

export function getClientToolExecutorId(): string {
  const storage = getSessionStorage();
  const stored = storage?.getItem(EXECUTOR_ID_KEY)?.trim();
  if (stored) return stored;
  memoryExecutorId ??= crypto.randomUUID();
  try {
    storage?.setItem(EXECUTOR_ID_KEY, memoryExecutorId);
  } catch {
    // The in-memory identity still keeps one loaded frontend internally consistent.
  }
  return memoryExecutorId;
}

export const clientToolExecutionStore: ClientToolExecutionStore = {
  read(requestId) {
    const storage = getSessionStorage();
    if (!storage) return memoryRecords.get(requestId) ?? null;
    try {
      const raw = storage.getItem(storageKey(requestId));
      return raw
        ? parseRecord(JSON.parse(raw))
        : memoryRecords.get(requestId) ?? null;
    } catch {
      return memoryRecords.get(requestId) ?? null;
    }
  },
  write(requestId, record) {
    const storage = getSessionStorage();
    if (!storage) {
      memoryRecords.set(requestId, record);
      return;
    }
    try {
      storage.setItem(storageKey(requestId), JSON.stringify(record));
    } catch {
      memoryRecords.set(requestId, record);
    }
  },
  remove(requestId) {
    memoryRecords.delete(requestId);
    try {
      getSessionStorage()?.removeItem(storageKey(requestId));
    } catch {
      // A closed request no longer depends on browser storage cleanup succeeding.
    }
  },
};

function getSessionStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function storageKey(requestId: string): string {
  return `${EXECUTION_KEY_PREFIX}${requestId}`;
}

function parseRecord(value: unknown): ClientToolExecutionRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.state === "executing") return { state: "executing" };
  if (record.state !== "completed") return null;
  const result = record.result;
  if (!result || typeof result !== "object" || Array.isArray(result)) return null;
  const candidate = result as Record<string, unknown>;
  if (typeof candidate.ok !== "boolean") return null;
  return {
    state: "completed",
    result: {
      ok: candidate.ok,
      ...(Object.hasOwn(candidate, "content") ? { content: candidate.content } : {}),
      ...(typeof candidate.error === "string" ? { error: candidate.error } : {}),
    },
  };
}
