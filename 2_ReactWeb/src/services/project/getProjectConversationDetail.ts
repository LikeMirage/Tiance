import type { ConversationSession, ConversationSessionState } from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export type ConversationDetail = {
  project_id: string;
  revision: number;
  session: ConversationSession;
  state: ConversationSessionState;
};

export function getProjectConversationDetail(projectId: string, sessionId: string, signal?: AbortSignal) {
  return fetchJson<ConversationDetail>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/detail`,
    { cache: "no-store", signal },
  );
}
