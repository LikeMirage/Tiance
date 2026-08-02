import type { ConversationSession } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function setProjectConversationPinned(
  projectId: string,
  sessionId: string,
  pinned: boolean,
) {
  return fetchJson<ConversationSession>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/pin`,
    {
      method: "PATCH",
      body: JSON.stringify({ pinned }),
    },
  );
}
