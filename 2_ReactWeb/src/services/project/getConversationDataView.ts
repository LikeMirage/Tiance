import { fetchJson } from "../http/httpClient";

export type ConversationDataViewResponse = {
  content: string;
  name: string;
  project_id: string;
  revision_ms: number;
  session_id: string | null;
  total_count: number | null;
  page: number | null;
  page_size: number | null;
  total_pages: number | null;
  has_previous: boolean;
  has_next: boolean;
};

export function getConversationDataView(
  projectId: string,
  name: string,
  sessionId: string | null,
  options: { page?: number; pageSize?: number; signal?: AbortSignal } = {},
) {
  const query = new URLSearchParams({ name });
  if (sessionId) query.set("session_id", sessionId);
  if (options.page !== undefined) query.set("page", String(options.page));
  if (options.pageSize !== undefined) query.set("page_size", String(options.pageSize));
  return fetchJson<ConversationDataViewResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/data-view?${query.toString()}`,
    { signal: options.signal },
  );
}
