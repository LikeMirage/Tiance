import type { ChatMessage } from "./chatMessage";
import { resolveUserMessageContent } from "./userMessageReferences";

export type UserMessageNavigationItem = {
  assistantPreview: string;
  turnNumber: number;
  userMessageId: string;
  userPreview: string;
};

const PREVIEW_MAX_LENGTH = 160;

export function buildUserMessageNavigationItems(
  messages: ChatMessage[],
): UserMessageNavigationItem[] {
  const items: UserMessageNavigationItem[] = [];
  let turnNumber = 0;

  for (let index = 0; index < messages.length; index += 1) {
    const userMessage = messages[index];
    if (userMessage.role !== "user") continue;
    turnNumber += 1;

    let turnEnd = index + 1;
    while (turnEnd < messages.length && messages[turnEnd].role !== "user") {
      turnEnd += 1;
    }

    const finalReply = findFinalReply(messages, index + 1, turnEnd);
    if (!finalReply) continue;

    const userContent = resolveUserMessageContent(userMessage);
    const userPreview = normalizePreview(userContent);
    const assistantPreview = normalizePreview(finalReply.content);
    if (!userPreview || !assistantPreview) continue;

    items.push({
      assistantPreview,
      turnNumber,
      userMessageId: userMessage.id,
      userPreview,
    });
  }

  return items;
}

function findFinalReply(
  messages: ChatMessage[],
  start: number,
  end: number,
) {
  let lastToolIndex = -1;
  for (let index = start; index < end; index += 1) {
    if (messages[index].role === "tool") {
      lastToolIndex = index;
    }
  }

  for (let index = end - 1; index >= start; index -= 1) {
    const message = messages[index];
    if (index < lastToolIndex) return null;
    if (message.role !== "assistant" && message.role !== "error") continue;
    if (message.status === "running" || !message.content.trim()) continue;
    return message;
  }
  return null;
}

function normalizePreview(content: string) {
  const normalized = content.replace(/\s+/g, " ").trim();
  if (normalized.length <= PREVIEW_MAX_LENGTH) return normalized;
  return `${normalized.slice(0, PREVIEW_MAX_LENGTH).trimEnd()}...`;
}
