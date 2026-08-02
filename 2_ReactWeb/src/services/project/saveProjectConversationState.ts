import type {
  ConversationDraftReferences,
  ConversationRuntimeStatus,
  ConversationSessionState,
} from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export type SaveProjectConversationSessionState = Partial<{
  runtime_status: ConversationRuntimeStatus;
  draft: string;
  references: ConversationDraftReferences;
}>;

export type SaveProjectConversationStateInput = {
  assistant_title?: string | null;
  active_session_id?: string | null;
  session_states?: Record<string, SaveProjectConversationSessionState>;
};

export type SaveProjectConversationStateResponse = {
  project_id: string;
  assistant_title: string;
  active_session_id: string | null;
  session_states: Record<string, ConversationSessionState>;
};

export function saveProjectConversationState(
  projectId: string,
  input: SaveProjectConversationStateInput,
) {
  return fetchJson<SaveProjectConversationStateResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/state`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}
