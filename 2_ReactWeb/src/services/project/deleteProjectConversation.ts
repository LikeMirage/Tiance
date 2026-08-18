import { fetchNoContent } from "../http/httpClient";

export function deleteProjectConversation(
  projectId: string,
  sessionId: string,
  sessionIds: string[],
) {
  return fetchNoContent(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}`,
    {
      body: JSON.stringify({ session_ids: sessionIds }),
      method: "DELETE",
    },
  );
}
