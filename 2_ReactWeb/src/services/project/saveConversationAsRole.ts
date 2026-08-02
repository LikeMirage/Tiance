import type { ConversationSession } from "../../entities/llm-chat/model/conversation";
import type { Project } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export type SaveConversationAsRoleResult = {
  role: Project;
  session: ConversationSession;
};

export function saveConversationAsRole(
  projectId: string,
  sessionId: string,
  input: { name: string; category_id: string | null },
) {
  return fetchJson<SaveConversationAsRoleResult>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/save-as-role`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}
