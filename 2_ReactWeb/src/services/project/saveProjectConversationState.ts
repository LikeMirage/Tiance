import type {
  ConversationDraftReferences,
  ConversationRuntimeStatus,
  ConversationSessionState,
} from "../../entities/llm-chat/model/conversation";
import { fetchJson } from "../http/httpClient";

export type SaveProjectConversationStateInput = {
  active_session_id?: string | null;
  session_runtime_statuses?: Record<string, ConversationRuntimeStatus>;
  session_drafts?: Record<string, string>;
  session_references?: Record<string, ConversationDraftReferences>;
};

export type SaveProjectConversationStateResponse = {
  project_id: string;
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
