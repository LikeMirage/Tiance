import type {
  ChatClientToolRequestEvent,
  ChatStreamEvent,
  ChatToolResultEvent,
} from "../../../entities/llm-chat/model/chatCompletion";
import {
  requestAppThemeRefresh,
  type AppThemeRefreshDetail,
} from "../../../shared/theme";
import type { ClientToolExecutor } from "../../client-tools/model/clientToolBridge";
import { unsupportedClientToolResult } from "../../client-tools/model/clientToolBridge";
import {
  cancelClientToolRequest,
  runClientToolRequestOnce,
} from "../../client-tools/model/clientToolRequestSingleFlight";

export async function handleClientToolRequest(
  request: ChatClientToolRequestEvent,
  executor: ClientToolExecutor | null | undefined,
) {
  const resolvedExecutor: ClientToolExecutor = executor
    ?? (async (pendingRequest) => unsupportedClientToolResult(pendingRequest.name));
  await runClientToolRequestOnce(request, resolvedExecutor);
}

export function requestThemeRefreshFromToolResult(
  event: { kind: string; tool_result?: ChatToolResultEvent | null },
) {
  const detail = readThemeRefreshRequestFromToolResult(event);
  if (detail) requestAppThemeRefresh(detail);
}

export function readThemeRefreshRequestFromToolResult(
  event: { kind: string; tool_result?: ChatToolResultEvent | null },
): AppThemeRefreshDetail | null {
  if (event.kind !== "tool_result" || !event.tool_result?.ok) return null;

  const payload = parseToolResultContent(event.tool_result.content);
  const invalidation = findResourceInvalidation(payload, "themes");
  if (!invalidation) return null;

  return {
    reason: "resource_invalidation",
    themeId: readString(invalidation.resource_id) || null,
  };
}

export async function processChatStreamEventSideEffects(
  event: ChatStreamEvent,
  executor: ClientToolExecutor | null | undefined,
) {
  if (event.kind === "conversation_run_started" || event.kind === "conversation_run_settled") {
    return false;
  }
  if (event.kind === "client_tool_request") {
    void handleClientToolRequest(event.client_tool_request, executor).catch(() => undefined);
    return false;
  }
  if (event.kind === "client_tool_request_cancelled") {
    cancelClientToolRequest(event.request_id);
    return false;
  }
  requestThemeRefreshFromToolResult(event);
  return true;
}

function parseToolResultContent(content: string): Record<string, unknown> | null {
  try {
    return readRecord(JSON.parse(content));
  } catch {
    return null;
  }
}

function findResourceInvalidation(
  value: unknown,
  resource: string,
): Record<string, unknown> | null {
  if (!value || typeof value !== "object") return null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findResourceInvalidation(item, resource);
      if (found) return found;
    }
    return null;
  }
  const record = value as Record<string, unknown>;
  const invalidations = record.resource_invalidations;
  if (Array.isArray(invalidations)) {
    const match = invalidations.find((item) => readRecord(item)?.resource === resource);
    const resolved = readRecord(match);
    if (resolved) return resolved;
  }
  for (const nested of Object.values(record)) {
    const found = findResourceInvalidation(nested, resource);
    if (found) return found;
  }
  return null;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
