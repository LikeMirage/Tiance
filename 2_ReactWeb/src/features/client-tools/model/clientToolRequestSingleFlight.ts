import type { ChatClientToolRequestEvent } from "../../../entities/llm-chat/model/chatCompletion";
import {
  submitClientToolResult,
  type ClientToolResultAck,
} from "../../../services/llm/submitClientToolResult";
import type {
  ClientToolExecutionResult,
  ClientToolExecutor,
} from "./clientToolBridge";

const MAX_COMPLETED_RESULTS = 2_048;

type ClientToolResultSubmitter = (
  requestId: string,
  result: ClientToolExecutionResult,
) => Promise<ClientToolResultAck>;

type SingleFlightEntry = {
  deliveryState: "retryable" | "accepted" | "closed";
  executionSettled: boolean;
  resultPromise: Promise<ClientToolExecutionResult>;
  submitPromise: Promise<void> | null;
};

type ClientToolRequestSingleFlightOptions = {
  maxCompletedResults?: number;
  submitResult?: ClientToolResultSubmitter;
};

/**
 * Coordinates client-tool execution and result delivery by server request id.
 *
 * Execution is single-flight and its result is retained in a bounded LRU. Result
 * delivery is independently single-flight: a transient submission failure may be
 * retried by a later SSE replay without ever executing the tool again.
 */
export class ClientToolRequestSingleFlight {
  private readonly entries = new Map<string, SingleFlightEntry>();
  private readonly maxCompletedResults: number;
  private readonly submitResult: ClientToolResultSubmitter;

  constructor(options: ClientToolRequestSingleFlightOptions = {}) {
    this.maxCompletedResults = normalizePositiveInteger(
      options.maxCompletedResults,
      MAX_COMPLETED_RESULTS,
    );
    this.submitResult = options.submitResult ?? submitClientToolResult;
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

  private createEntry(
    requestId: string,
    request: ChatClientToolRequestEvent,
    executor: ClientToolExecutor,
  ): SingleFlightEntry {
    const resultPromise = Promise.resolve()
      .then(() => executeClientToolSafely(request, executor));
    const entry: SingleFlightEntry = {
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

  private startSubmit(
    requestId: string,
    entry: SingleFlightEntry,
  ): Promise<void> {
    const submission = entry.resultPromise
      .then((result) => this.submitResult(requestId, result))
      .then((ack) => {
        entry.deliveryState = ack.accepted ? "accepted" : "closed";
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

async function executeClientToolSafely(
  request: ChatClientToolRequestEvent,
  executor: ClientToolExecutor,
): Promise<ClientToolExecutionResult> {
  try {
    return await executor(request);
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "前端工具执行失败。",
    };
  }
}

function normalizePositiveInteger(
  value: number | undefined,
  fallback: number,
): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : fallback;
}
