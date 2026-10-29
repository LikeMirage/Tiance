import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";
import {
  claimClientToolRequest,
  type ClientToolClaimLease,
} from "../../../services/llm/claimClientToolRequest";
import { renewClientToolClaim } from "../../../services/llm/renewClientToolClaim";
import { createUuid } from "../../../shared/model/createUuid";
import {
  submitClientToolResult,
  type ClientToolResultAck,
} from "../../../services/llm/submitClientToolResult";
import type {
  ClientToolExecutionResult,
  ClientToolExecutor,
} from "./clientToolBridge";
import {
  clientToolExecutionStore,
  getClientToolExecutorId,
  type ClientToolExecutionStore,
} from "./clientToolExecutionSession";

const MAX_COMPLETED_RESULTS = 2_048;

type ClientToolOwnership = {
  executorId: string;
  claimId: string;
  leaseDurationSeconds: number;
};

type ClientToolResultSubmitter = (
  requestId: string,
  result: ClientToolExecutionResult,
  ownership: ClientToolOwnership,
) => Promise<ClientToolResultAck>;

type SingleFlightExecution = {
  ownership: ClientToolOwnership;
  result: ClientToolExecutionResult;
};

type SingleFlightEntry = {
  abortController: AbortController;
  deliveryState: "retryable" | "accepted" | "closed";
  executionSettled: boolean;
  resultPromise: Promise<SingleFlightExecution | null>;
  submitPromise: Promise<void> | null;
};

type ClientToolRequestSingleFlightOptions = {
  maxCompletedResults?: number;
  executorId?: string;
  executionStore?: ClientToolExecutionStore;
  submitResult?: ClientToolResultSubmitter;
  claimRequest?: typeof claimClientToolRequest;
  renewClaim?: (requestId: string, ownership: ClientToolOwnership) => Promise<boolean>;
};

/**
 * Coordinates client-tool execution and result delivery by server request id.
 *
 * The backend owns request truth. This coordinator persists only enough local
 * execution evidence to finish result delivery after a frontend reload. An
 * interrupted side effect is never repeated automatically when its outcome is
 * unknown.
 */
export class ClientToolRequestSingleFlight {
  private readonly entries = new Map<string, SingleFlightEntry>();
  private readonly maxCompletedResults: number;
  private readonly executorId: string;
  private readonly executionStore: ClientToolExecutionStore;
  private readonly submitResult: ClientToolResultSubmitter;
  private readonly claimRequest: NonNullable<ClientToolRequestSingleFlightOptions["claimRequest"]>;
  private readonly renewClaim: NonNullable<ClientToolRequestSingleFlightOptions["renewClaim"]>;

  constructor(options: ClientToolRequestSingleFlightOptions = {}) {
    this.maxCompletedResults = normalizePositiveInteger(
      options.maxCompletedResults,
      MAX_COMPLETED_RESULTS,
    );
    this.executorId = options.executorId ?? getClientToolExecutorId();
    this.executionStore = options.executionStore ?? clientToolExecutionStore;
    this.submitResult = options.submitResult ?? submitClientToolResult;
    this.claimRequest = options.claimRequest ?? claimClientToolRequest;
    this.renewClaim = options.renewClaim ?? renewClientToolClaim;
  }

  run(
    request: ChatClientToolRequestEvent,
    executor: ClientToolExecutor,
  ): Promise<void> {
    const requestId = request.request_id.trim();
    if (!requestId) {
      return Promise.reject(new Error("客户端工具请求 ID 不能为空。"));
    }

    let entry = this.entries.get(requestId);
    if (!entry) {
      entry = this.createEntry(requestId, request, executor);
    } else if (entry.executionSettled) {
      this.touch(requestId, entry);
    }

    if (entry.deliveryState !== "retryable") {
      return Promise.resolve();
    }
    if (entry.submitPromise) return entry.submitPromise;

    return this.startSubmit(requestId, entry);
  }

  cancel(requestId: string) {
    const normalizedRequestId = requestId.trim();
    if (!normalizedRequestId) return false;
    const entry = this.entries.get(normalizedRequestId);
    if (!entry || entry.executionSettled) return false;
    entry.abortController.abort();
    return true;
  }

  private createEntry(
    requestId: string,
    request: ChatClientToolRequestEvent,
    executor: ClientToolExecutor,
  ): SingleFlightEntry {
    const abortController = new AbortController();
    const existing = this.executionStore.read(requestId);
    const attemptId = existing?.state === "claiming" ? existing.attemptId : createUuid();
    if (!existing) this.executionStore.write(requestId, { state: "claiming", attemptId });
    const stopDeadline = watchConfiguredDeadline(request.timeout_seconds, abortController);
    let claiming = true;
    const resultPromise = this.claimWithRetry(requestId, attemptId, request, abortController.signal)
      .catch((error: unknown) => {
        if (abortController.signal.aborted) return null;
        throw error;
      }).then(async (lease) => {
        claiming = false;
        if (!lease) {
          if (this.executionStore.read(requestId)?.state === "claiming") this.executionStore.remove(requestId);
          return null;
        }
        const ownership = normalizeOwnership(lease, this.executorId);
        if (!ownership) {
          this.executionStore.remove(requestId);
          return null;
        }

        const stored = this.executionStore.read(requestId);
        if (stored?.state === "completed") {
          return { ownership, result: stored.result };
        }
        if (stored?.state === "executing" || (lease.resumed && lease.attempt_id !== attemptId)) {
          const result = interruptedClientToolResult();
          this.executionStore.write(requestId, { state: "completed", result });
          return { ownership, result };
        }

        this.executionStore.write(requestId, { state: "executing" });
        const stopHeartbeat = this.startLeaseHeartbeat(
          requestId,
          ownership,
          abortController,
        );
        try {
          const result = await executeClientToolSafely(
            request,
            executor,
            abortController.signal,
          );
          this.executionStore.write(requestId, { state: "completed", result });
          return { ownership, result };
        } finally {
          stopHeartbeat();
        }
      });
    const entry: SingleFlightEntry = {
      abortController,
      deliveryState: "retryable",
      executionSettled: false,
      resultPromise,
      submitPromise: null,
    };
    this.entries.set(requestId, entry);
    const settled = () => {
      stopDeadline();
      entry.executionSettled = true;
      if (this.entries.get(requestId) === entry) {
        this.touch(requestId, entry);
        this.evictCompletedResults();
      }
    };
    void resultPromise.then(settled, () => {
      stopDeadline();
      // Only a failed claim can return to the claim stage. Never erase evidence
      // of a started execution just because result delivery failed.
      if (claiming && this.entries.get(requestId) === entry) this.entries.delete(requestId);
      else settled();
    });
    return entry;
  }

  private async claimWithRetry(
    requestId: string,
    attemptId: string,
    request: ChatClientToolRequestEvent,
    signal: AbortSignal,
  ): Promise<ClientToolClaimLease> {
    let retryDelayMs = 1000;
    while (true) {
      signal.throwIfAborted();
      try {
        return await this.claimRequest(requestId, this.executorId, { attemptId, signal });
      } catch (error) {
        const status = error && typeof error === "object" && "status" in error ? Number(error.status) : 0;
        // The configured tool budget bounds retries; these delays only pace
        // transport attempts. Explicit 4xx errors await a later replay/login.
        if (signal.aborted || !hasConfiguredDeadline(request.timeout_seconds)
          || (status >= 400 && status < 500 && status !== 408 && status !== 429)) throw error;
        await waitForClaimRetry(retryDelayMs, signal);
        retryDelayMs = Math.min(retryDelayMs * 2, 5000);
      }
    }
  }

  private startLeaseHeartbeat(
    requestId: string,
    ownership: ClientToolOwnership,
    abortController: AbortController,
  ): () => void {
    const intervalMs = Math.max(1_000, Math.floor(ownership.leaseDurationSeconds * 1_000 / 3));
    let stopped = false;
    let pending = false;
    const timer = globalThis.setInterval(() => {
      if (pending || stopped) return;
      pending = true;
      void this.renewClaim(requestId, ownership).then((renewed) => {
        if (!stopped && !renewed) abortController.abort();
      }).catch(() => {
        // A transient network error does not prove ownership was lost. The
        // backend request remains the authority and a later check may succeed.
      }).finally(() => { pending = false; });
    }, intervalMs);
    return () => { stopped = true; globalThis.clearInterval(timer); };
  }

  private startSubmit(
    requestId: string,
    entry: SingleFlightEntry,
  ): Promise<void> {
    const submission = entry.resultPromise
      .then((execution) => execution === null
        ? null
        : this.submitResult(requestId, execution.result, execution.ownership))
      .then((ack) => {
        entry.deliveryState = ack?.accepted ? "accepted" : "closed";
        if (ack) this.executionStore.remove(requestId);
      });
    const trackedSubmission = submission.then(
      () => {
        this.finishSubmit(requestId, entry, trackedSubmission);
      },
      (error: unknown) => {
        this.finishSubmit(requestId, entry, trackedSubmission);
        throw error;
      },
    );
    entry.submitPromise = trackedSubmission;
    return trackedSubmission;
  }

  private finishSubmit(
    requestId: string,
    entry: SingleFlightEntry,
    submission: Promise<void>,
  ) {
    if (entry.submitPromise === submission) {
      entry.submitPromise = null;
    }
    if (this.entries.get(requestId) === entry && entry.executionSettled) {
      this.touch(requestId, entry);
      this.evictCompletedResults();
    }
  }

  private touch(requestId: string, entry: SingleFlightEntry) {
    this.entries.delete(requestId);
    this.entries.set(requestId, entry);
  }

  private evictCompletedResults() {
    let completedCount = 0;
    for (const entry of this.entries.values()) {
      if (entry.executionSettled) completedCount += 1;
    }
    if (completedCount <= this.maxCompletedResults) return;

    for (const [requestId, entry] of this.entries) {
      if (completedCount <= this.maxCompletedResults) break;
      if (!entry.executionSettled || entry.submitPromise) continue;
      this.entries.delete(requestId);
      completedCount -= 1;
    }
  }
}

const sharedClientToolRequestSingleFlight = new ClientToolRequestSingleFlight();

export function runClientToolRequestOnce(
  request: ChatClientToolRequestEvent,
  executor: ClientToolExecutor,
): Promise<void> {
  return sharedClientToolRequestSingleFlight.run(request, executor);
}

export function cancelClientToolRequest(requestId: string) {
  return sharedClientToolRequestSingleFlight.cancel(requestId);
}

async function executeClientToolSafely(
  request: ChatClientToolRequestEvent,
  executor: ClientToolExecutor,
  signal: AbortSignal,
): Promise<ClientToolExecutionResult> {
  if (signal.aborted) return cancelledClientToolResult(signal);
  let resolveCancelled: (() => void) | null = null;
  const cancelled = new Promise<ClientToolExecutionResult>((resolve) => {
    resolveCancelled = () => resolve(cancelledClientToolResult(signal));
    signal.addEventListener("abort", resolveCancelled, { once: true });
  });
  const execution = (async (): Promise<ClientToolExecutionResult> => {
    try {
      return await executor(request, { signal });
    } catch (error) {
      return {
        ok: false,
        error: error instanceof Error ? error.message : "前端工具执行失败。",
      };
    }
  })();
  try {
    return await Promise.race([execution, cancelled]);
  } finally {
    if (resolveCancelled) signal.removeEventListener("abort", resolveCancelled);
  }
}

function cancelledClientToolResult(signal: AbortSignal): ClientToolExecutionResult {
  return {
    ok: false,
    error: signal.reason?.name === "TimeoutError" ? "客户端工具执行超时。"
      : "调用会话已停止等待；已开始的动作不会被伪装成已回滚。",
  };
}

function hasConfiguredDeadline(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function watchConfiguredDeadline(seconds: number | null | undefined, controller: AbortController) {
  if (!hasConfiguredDeadline(seconds)) return () => undefined;
  const deadline = performance.now() + seconds * 1000;
  let timer: ReturnType<typeof setTimeout>;
  const check = () => {
    const remaining = deadline - performance.now();
    if (remaining <= 0) controller.abort(new DOMException("客户端工具执行超时。", "TimeoutError"));
    else timer = globalThis.setTimeout(check, Math.min(remaining, 2_147_483_647));
  };
  check();
  return () => globalThis.clearTimeout(timer);
}

function waitForClaimRetry(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      reject(signal.reason);
    };
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

function interruptedClientToolResult(): ClientToolExecutionResult {
  return {
    ok: false,
    content: {
      error_code: "CLIENT_TOOL_EXECUTION_INTERRUPTED",
      message: "前端执行环境在结果确认前发生重载，无法确认动作是否完成。",
    },
    error: "前端执行环境在结果确认前发生重载；为避免重复副作用，本次动作未自动重试。",
  };
}

function normalizeOwnership(
  lease: ClientToolClaimLease,
  executorId: string,
): ClientToolOwnership | null {
  if (
    !lease.acquired
    || !lease.claim_id
    || typeof lease.lease_duration_seconds !== "number"
    || lease.lease_duration_seconds <= 0
  ) {
    return null;
  }
  return {
    executorId,
    claimId: lease.claim_id,
    leaseDurationSeconds: lease.lease_duration_seconds,
  };
}

function normalizePositiveInteger(
  value: number | undefined,
  fallback: number,
): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : fallback;
}
