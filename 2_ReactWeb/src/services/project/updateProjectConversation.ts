import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../entities/llm-runtime/model/generationParams";
import { fetchJson } from "../http/httpClient";

export type UpdateProjectConversationInput = {
  title?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  reasoning_mode?: DsLlmReasoningMode | null;
  settings?: Partial<ConversationSessionSettings> | null;
};

export function updateProjectConversation(
  projectId: string,
  sessionId: string,
  input: UpdateProjectConversationInput,
) {
  return fetchJson<ConversationSession>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}
