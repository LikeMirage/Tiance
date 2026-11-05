import { fetchJson } from "../http/httpClient";

export type ConversationNavigationResponse = {
  revision: number;
  reset_revision: number;
  items: {
    user_message_id: string;
    turn_number: number;
    user_preview: string;
    assistant_preview: string;
    assistant_message_id: string | null;
  }[];
};

export function getConversationNavigation(projectId: string, sessionId: string, signal: AbortSignal) {
  return fetchJson<ConversationNavigationResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/messages/navigation`,
    { signal },
  );
}
