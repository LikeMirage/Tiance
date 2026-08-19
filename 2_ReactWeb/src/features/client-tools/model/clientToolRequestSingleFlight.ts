import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";
import {
  claimClientToolRequest,
  type ClientToolClaimLease,
} from "../../../services/llm/claimClientToolRequest";
import { renewClientToolClaim } from "../../../services/llm/renewClientToolClaim";
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
  claimRequest?: (requestId: string, executorId: string) => Promise<ClientToolClaimLease>;
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
    const resultPromise = this.claimRequest(requestId, this.executorId).then(async (lease) => {
      const ownership = normalizeOwnership(lease, this.executorId);
      if (!ownership) {
        this.executionStore.remove(requestId);
        return null;
      }

      const stored = this.executionStore.read(requestId);
      if (stored?.state === "completed") {
        return { ownership, result: stored.result };
      }
      if (stored?.state === "executing" || lease.resumed) {
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
    void resultPromise.then(() => {
      entry.executionSettled = true;
      if (this.entries.get(requestId) === entry) {
        this.touch(requestId, entry);
        this.evictCompletedResults();
      }
    });
    return entry;
  }

  private startLeaseHeartbeat(
    requestId: string,
    ownership: ClientToolOwnership,
    abortController: AbortController,
  ): () => void {
    const intervalMs = Math.max(1_000, Math.floor(ownership.leaseDurationSeconds * 1_000 / 3));
    const timer = globalThis.setInterval(() => {
      void this.renewClaim(requestId, ownership).then((renewed) => {
        if (!renewed) abortController.abort();
      }).catch(() => {
        // A transient network error does not prove ownership was lost. The
        // backend lease remains the authority and a later renewal may succeed.
      });
    }, intervalMs);
    return () => globalThis.clearInterval(timer);
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
  if (signal.aborted) return cancelledClientToolResult();
  let resolveCancelled: (() => void) | null = null;
  const cancelled = new Promise<ClientToolExecutionResult>((resolve) => {
    resolveCancelled = () => resolve(cancelledClientToolResult());
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

function cancelledClientToolResult(): ClientToolExecutionResult {
  return {
    ok: false,
    error: "调用会话已停止等待；已开始的动作不会被伪装成已回滚。",
  };
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
