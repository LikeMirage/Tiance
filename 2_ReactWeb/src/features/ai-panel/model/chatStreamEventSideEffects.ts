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
import { runClientToolRequestOnce } from "../../client-tools/model/clientToolRequestSingleFlight";

const DYNAMIC_TOOL_EXECUTOR_NAME = "execute_dynamic_tool";
const THEME_DESIGNER_NAME = "theme_designer";
const THEME_REFRESH_ACTIONS = new Set([
  "derive_palette",
  "edit",
  "switch",
  "restore",
]);

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
  if (detail) {
    requestAppThemeRefresh(detail);
  }
}

export function readThemeRefreshRequestFromToolResult(
  event: { kind: string; tool_result?: ChatToolResultEvent | null },
): AppThemeRefreshDetail | null {
  if (event.kind !== "tool_result" || !event.tool_result?.ok) return null;

  const toolResult = event.tool_result;
  const payload = parseToolResultContent(toolResult.content);
  const argumentsPayload = parseToolResultContent(toolResult.arguments);
  const themeResult = resolveThemeToolResult(toolResult.name, payload, argumentsPayload);
  if (!themeResult || !THEME_REFRESH_ACTIONS.has(themeResult.action)) return null;

  return {
    reason: "theme_designer",
    themeId: themeResult.themeId,
  };
}

export async function processChatStreamEventSideEffects(
  event: ChatStreamEvent,
  executor: ClientToolExecutor | null | undefined,
) {
  if (
    event.kind === "conversation_run_started"
    || event.kind === "conversation_run_settled"
  ) {
    return false;
  }
  if (event.kind === "client_tool_request") {
    await handleClientToolRequest(event.client_tool_request, executor);
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

function resolveThemeToolResult(
  toolName: string,
  payload: Record<string, unknown> | null,
  argumentsPayload: Record<string, unknown> | null,
): { action: string; themeId: string | null } | null {
  if (toolName === THEME_DESIGNER_NAME) {
    return readThemeToolResult(
      readRecord(payload?.data),
      argumentsPayload,
    );
  }
  if (toolName !== DYNAMIC_TOOL_EXECUTOR_NAME) return null;

  const wrapperData = readRecord(payload?.data);
  const targetName =
    readString(wrapperData?.tool_name) ||
    readString(argumentsPayload?.tool_name);
  if (targetName !== THEME_DESIGNER_NAME) return null;

  const targetResult = readRecord(wrapperData?.result);
  if (targetResult?.ok !== true) return null;

  return readThemeToolResult(
    readRecord(targetResult?.data),
    readRecord(wrapperData?.arguments) || readRecord(argumentsPayload?.arguments),
  );
}

function readThemeToolResult(
  data: Record<string, unknown> | null,
  argumentsPayload: Record<string, unknown> | null,
): { action: string; themeId: string | null } {
  return {
    action: readString(data?.action) || readString(argumentsPayload?.action),
    themeId:
      readString(data?.theme_id) ||
      readString(data?.active_theme_id) ||
      readString(argumentsPayload?.theme_id) ||
      null,
  };
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
