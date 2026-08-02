import type { ConversationSession } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function applyConversationRole(
  projectId: string,
  sessionId: string,
  roleProjectId: string,
) {
  return fetchJson<ConversationSession>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/role`,
    {
      method: "POST",
      body: JSON.stringify({ role_project_id: roleProjectId }),
    },
  );
}
