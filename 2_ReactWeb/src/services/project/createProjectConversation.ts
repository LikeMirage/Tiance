import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../entities/llm-runtime/model/generationParams";
import { fetchJson } from "../http/httpClient";

export type CreateProjectConversationInput = {
  activate?: boolean;
  created_by?: "user" | "ai";
  title?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  parent_session_id?: string | null;
  reasoning_mode?: DsLlmReasoningMode | null;
  role_project_id?: string | null;
  settings?: Partial<ConversationSessionSettings> | null;
};

export function createProjectConversation(
  projectId: string,
  input: CreateProjectConversationInput = {},
) {
  return fetchJson<ConversationSession>(
    `/api/projects/${encodeURIComponent(projectId)}/conversations`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}
