import { fetchJson } from "../http/httpClient";

export type ConversationDataViewResponse = {
  content: string;
  name: string;
  project_id: string;
  revision_ms: number;
  session_id: string | null;
  total_count: number | null;
  truncated: boolean;
};

export function getConversationDataView(
  projectId: string,
  name: string,
  sessionId: string | null,
) {
  const query = new URLSearchParams({ name });
  if (sessionId) query.set("session_id", sessionId);
  return fetchJson<ConversationDataViewResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/data-view?${query.toString()}`,
  );
}
