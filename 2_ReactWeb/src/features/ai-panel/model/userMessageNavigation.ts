import type { ChatMessage } from "./chatMessage";
import { resolveUserMessageContent } from "./userMessageReferences";

export type UserMessageNavigationItem = {
  assistantMessageId?: string;
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

    const userContent = resolveUserMessageContent(userMessage);
    const userPreview = normalizePreview(userContent);
    const assistantPreview = normalizePreview(finalReply?.content ?? "");

    items.push({
      assistantMessageId: finalReply?.id,
      assistantPreview,
      turnNumber,
      userMessageId: userMessage.id,
      userPreview: userPreview || "（附件消息）",
    });
  }

  return items;
}

/** The complete index owns numbering. Loaded body pages only enrich previews
 * and add a newly submitted user message before it reaches the saved index. */
export function mergeUserMessageNavigationItems(
  index: UserMessageNavigationItem[], local: UserMessageNavigationItem[],
): UserMessageNavigationItem[] {
  const localById = new Map(local.map((item) => [item.userMessageId, item]));
  const knownIds = new Set(index.map((item) => item.userMessageId));
  const result = index.map((item) => {
    const loaded = localById.get(item.userMessageId);
    return loaded ? { ...item, userPreview: loaded.userPreview,
      assistantPreview: loaded.assistantPreview || item.assistantPreview,
      assistantMessageId: loaded.assistantMessageId ?? item.assistantMessageId } : item;
  });
  let turnNumber = result.at(-1)?.turnNumber ?? 0;
  for (const item of local) {
    if (!knownIds.has(item.userMessageId)) result.push({ ...item, turnNumber: ++turnNumber });
  }
  return result;
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
    if (message.runAttemptFailure && !message.runOutcome) continue;
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
