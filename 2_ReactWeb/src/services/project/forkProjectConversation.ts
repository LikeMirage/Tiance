import type {
  ConversationDraftReferences,
  ConversationForkResponse,
} from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export function forkProjectConversation(
  projectId: string,
  sessionId: string,
  input: {
    source_message_id: string;
    draft: string;
    references: ConversationDraftReferences;
  },
) {
  return fetchJson<ConversationForkResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/fork`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}
