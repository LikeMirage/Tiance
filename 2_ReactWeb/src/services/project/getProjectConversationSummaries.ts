import type { ConversationSessionListResponse, ConversationSessionState } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";
import { getProjectConversationDetail } from "./getProjectConversationDetail";

export type ConversationSummaries = Omit<ConversationSessionListResponse, "session_states"> & {
  session_states: Record<string, Omit<ConversationSessionState, "draft" | "references">>;
};

export function getProjectConversationSummaries(projectId: string, signal?: AbortSignal) {
  return fetchJson<ConversationSummaries>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/summaries`,
    { cache: "no-store", signal },
  );
}

export async function loadSelectedConversationList(
  projectId: string,
  selectedId: string | null,
  previousStates: Record<string, ConversationSessionState>,
  signal?: AbortSignal,
): Promise<ConversationSessionListResponse> {
  const summary = await getProjectConversationSummaries(projectId, signal);
  const ids = new Set(summary.items.map((item) => item.session_id));
  const activeId = selectedId && ids.has(selectedId) ? selectedId
    : summary.active_session_id && ids.has(summary.active_session_id) ? summary.active_session_id
    : summary.items[0]?.session_id ?? null;
  // Preserve locally loaded drafts; absent detail is never treated as an empty
  // persisted draft. Only the selected session is hydrated and made editable.
  const states = Object.fromEntries(Object.entries(summary.session_states).map(([id, state]) => [id, {
    draft: previousStates[id]?.draft ?? "",
    references: previousStates[id]?.references ?? [],
    ...state,
  }]));
  if (!activeId) return { ...summary, active_session_id: null, session_states: states };
  const detail = await getProjectConversationDetail(projectId, activeId, signal);
  if (!detail.session.settings) throw new Error("会话设置读取不完整，请重试。");
  return {
    ...summary,
    // The list revision still describes membership, not a later detail read.
    active_session_id: activeId,
    items: summary.items.map((item) => item.session_id === activeId ? detail.session : item),
    session_states: { ...states, [activeId]: detail.state },
  };
}
