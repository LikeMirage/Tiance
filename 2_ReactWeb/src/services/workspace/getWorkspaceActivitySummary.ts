import { fetchJson } from "../http/httpClient";

export type WorkspaceActivitySummaryResponse = {
  conversation_count: number;
  sent_message_count: number;
  ai_runtime_ms: number;
};

export function getWorkspaceActivitySummary(init?: Pick<RequestInit, "signal">) {
  return fetchJson<WorkspaceActivitySummaryResponse>("/api/workspace/activity-summary", {
    cache: "no-store",
    signal: init?.signal,
  });
}

export function clearWorkspaceConversationCount(init?: Pick<RequestInit, "signal">) {
  return fetchJson<WorkspaceActivitySummaryResponse>(
    "/api/workspace/activity-summary/conversation-count/clear",
    {
      method: "POST",
      signal: init?.signal,
    },
  );
}

export function synchronizeWorkspaceConversationCount(
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<WorkspaceActivitySummaryResponse>(
    "/api/workspace/activity-summary/conversation-count/sync-current",
    {
      method: "POST",
      signal: init?.signal,
    },
  );
}
