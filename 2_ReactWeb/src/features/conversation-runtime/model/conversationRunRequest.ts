import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import type {
  ChatClientCapability,
  ChatCompletionMessageInput,
  ChatCompletionRequest,
} from "../../../entities/llm-chat/model/chatCompletion";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { buildGenerationParams } from "./generationParams";

export function buildConversationRunRequest(input: {
  messages: ChatCompletionMessageInput[];
  modelId: string;
  projectId: string;
  providerId: string;
  reasoningMode: DsLlmReasoningMode | null;
  sessionId: string;
  settings: ConversationSessionSettings;
  clientCapabilities: readonly ChatClientCapability[];
}): ChatCompletionRequest {
  return {
    provider_id: input.providerId,
    model_id: input.modelId,
    project_id: input.projectId,
    session_id: input.sessionId,
    messages: input.messages,
    max_tool_calls: input.settings.max_tool_calls,
    client_capabilities: [...input.clientCapabilities],
    generation: buildGenerationParams(input.settings, input.reasoningMode),
  };
}
