import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { normalizeLlmReasoningMode } from "../../../entities/llm-runtime/model/reasoningModes";
import type { ChatModelOption } from "./chatModelOption";

export function resolveReasoningMode(
  value: unknown,
  supportedModes: readonly DsLlmReasoningMode[],
): DsLlmReasoningMode {
  const normalized = normalizeLlmReasoningMode(value);
  if (normalized && supportedModes.includes(normalized)) {
    return normalized;
  }
  return supportedModes[0] ?? "off";
}

export function resolveSessionModel(
  session: ConversationSession | null,
  models: ChatModelOption[],
) {
  if (!session?.provider_id || !session.model_id) return null;
  return models.find((model) =>
    model.providerId === session.provider_id && model.modelId === session.model_id,
  ) ?? null;
}
