import type { ConversationSessionListResponse, ConversationSessionState } from "../../entities/llm-chat/model/conversation";
import { fetchJson, HttpRequestError } from "../http/httpClient";
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

// Hover and keyboard focus share one speculative summary. A click takes ownership;
// subsequent pointer movement can only cancel an unclaimed request.
type SummaryPrefetch = {
  projectId: string;
  expires: number;
  controller: AbortController;
  result: Promise<ConversationSummaries | null>;
};
let prefetch: SummaryPrefetch | null = null;

export function prefetchConversationSummaries(projectId: string) {
  if (prefetch?.projectId === projectId && prefetch.expires > Date.now()) return;
  prefetch?.controller.abort();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  const result = getProjectConversationSummaries(projectId, controller.signal)
    .catch(() => null).finally(() => clearTimeout(timeout));
  prefetch = { projectId, expires: Date.now() + 3_000, controller, result };
}

async function takePrefetchedSummary(projectId: string, signal?: AbortSignal) {
  if (prefetch?.projectId !== projectId) return null;
  const entry = prefetch;
  prefetch = null;
  if (entry.expires <= Date.now()) { entry.controller.abort(); return null; }
  signal?.throwIfAborted();
  const cancel = () => entry.controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  try { return await entry.result; }
  finally { signal?.removeEventListener("abort", cancel); }
}

export async function loadSelectedConversationList(
  projectId: string,
  selectedId: string | null,
  previousStates: Record<string, ConversationSessionState>,
  signal?: AbortSignal,
  usePrefetch = false,
): Promise<ConversationSessionListResponse> {
  const prepared = usePrefetch ? await takePrefetchedSummary(projectId, signal) : null;
  signal?.throwIfAborted();
  const summary = prepared && (!selectedId || prepared.items.some(item => item.session_id === selectedId))
    ? prepared : await getProjectConversationSummaries(projectId, signal);
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
  let detail;
  try {
    detail = await getProjectConversationDetail(projectId, activeId, signal);
  } catch (error) {
    // A session can be deleted between hovering a project and selecting it.
    if (summary === prepared && error instanceof HttpRequestError && error.status === 404) {
      return loadSelectedConversationList(projectId, selectedId, previousStates, signal);
    }
    throw error;
  }
  if (!detail.session.settings) throw new Error("会话设置读取不完整，请重试。");
  return {
    ...summary,
    // The list revision still describes membership, not a later detail read.
    active_session_id: activeId,
    items: summary.items.map((item) => item.session_id === activeId ? detail.session : item),
    session_states: { ...states, [activeId]: detail.state },
  };
}
