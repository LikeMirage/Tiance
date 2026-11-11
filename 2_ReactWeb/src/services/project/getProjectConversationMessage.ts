import type { ConversationMessage } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversationMessage(
  projectId: string, sessionId: string, messageId: string, signal: AbortSignal,
) {
  return fetchJson<ConversationMessage>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}`,
    { signal },
  );
}
