import type { ChatMessage } from "./chatMessage";

export function buildModelSwitches(messages: ChatMessage[]) {
  const switches = new Map<string, string>();
  let previousModelId: string | null = null;

  for (const message of messages) {
    const modelId = resolveMessageModelId(message);
    if (!modelId) continue;
    if (previousModelId && modelId !== previousModelId) {
      switches.set(message.id, modelId);
    }
    previousModelId = modelId;
  }

  return switches;
}

export function resolveMessageModelId(message: ChatMessage) {
  const modelId = message.role === "user"
    ? message.targetModelId
    : message.modelId;
  const normalized = modelId?.trim();
  return normalized || null;
}
