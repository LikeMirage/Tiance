import type { ConversationSessionSettings } from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";

export function buildGenerationParams(
  settings: ConversationSessionSettings,
  reasoningMode: DsLlmReasoningMode | null,
) {
  const generation: {
    max_output_tokens?: number;
    reasoning?: { mode: DsLlmReasoningMode };
    temperature?: number;
    top_p?: number;
  } = {};

  generation.max_output_tokens = settings.max_output_tokens;
  if (reasoningMode) generation.reasoning = { mode: reasoningMode };
  if (settings.temperature !== null) generation.temperature = settings.temperature;
  if (settings.top_p !== null) generation.top_p = settings.top_p;

  return Object.keys(generation).length > 0 ? generation : undefined;
}
