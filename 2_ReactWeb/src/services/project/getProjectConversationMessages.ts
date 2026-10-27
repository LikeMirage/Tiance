export const CONVERSATION_MESSAGE_PAGE_SIZE = 80;

import type { ConversationMessageListResponse } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function getProjectConversationMessages(
  projectId: string,
  sessionId: string,
  options: {
    beforeMessageId?: string | null;
    afterMessageId?: string | null;
    limit?: number | null;
    signal?: AbortSignal;
  } = {},
) {
  const params = new URLSearchParams();
  if (options.limit !== null && options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.beforeMessageId) {
    params.set("before_message_id", options.beforeMessageId);
  }
  if (options.afterMessageId) params.set("after_message_id", options.afterMessageId);
  const query = params.toString();
  return fetchJson<ConversationMessageListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/messages${query ? `?${query}` : ""}`,
    { signal: options.signal },
  );
}
