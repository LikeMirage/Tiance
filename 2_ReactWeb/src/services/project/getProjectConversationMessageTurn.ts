import type { ConversationMessageTurnResponse } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversationMessageTurn(
  projectId: string,
  sessionId: string,
  userMessageId: string,
  signal?: AbortSignal,
) {
  return fetchJson<ConversationMessageTurnResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(userMessageId)}/turn`,
    { signal },
  );
}
