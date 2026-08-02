import type { ConversationSessionListResponse } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversations(projectId: string, signal?: AbortSignal) {
  return fetchJson<ConversationSessionListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations`,
    { cache: "no-store", signal },
  );
}
