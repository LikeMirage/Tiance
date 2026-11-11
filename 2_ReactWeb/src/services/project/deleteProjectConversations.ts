import { fetchNoContent } from "../http/httpClient";

export function deleteProjectConversations(
  projectId: string, sessionIds: string[], protectedSessionId: string, signal?: AbortSignal,
) {
  return fetchNoContent(`/api/projects/${encodeURIComponent(projectId)}/conversations`, {
    method: "DELETE",
    body: JSON.stringify({ session_ids: sessionIds, protected_session_id: protectedSessionId }),
    signal,
  });
}
