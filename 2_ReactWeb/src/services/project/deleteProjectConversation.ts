import { fetchNoContent } from "../http/httpClient";

export function deleteProjectConversation(projectId: string, sessionId: string) {
  return fetchNoContent(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}
