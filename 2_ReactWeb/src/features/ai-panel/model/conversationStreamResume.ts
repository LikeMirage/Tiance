import { buildChatDisplayMessages, resolveAssistantBodyContent } from "./chatDisplayMessages";
import {
  appendAssistantContentProcess,
  getLastMessageContextMeasurement,
  readToolProcessItemFromMessage,
  upsertToolProcessItem,
  upsertToolProcessItemInTimeline,
  type ChatAssistantProcessItem,
  type ChatMessage,
  type ChatToolProcessItem,
} from "./chatMessage";

export type ConversationStreamResumeSnapshot = {
  assistantMessage: ChatMessage;
  checkpointMessageId: string | null;
  messages: ChatMessage[];
};

export function prepareConversationStreamResume(
  messages: ChatMessage[],
  fallbackAssistantId: string,
  now = Date.now(),
): ConversationStreamResumeSnapshot {
  const lastMessage = messages[messages.length - 1] ?? null;
  const checkpointMessageId = lastMessage && (
    lastMessage.role === "assistant" || lastMessage.role === "tool"
  )
    ? lastMessage.id
    : null;
  const lastUserIndex = findLastUserMessageIndex(messages);
  const preservedMessages = lastUserIndex >= 0
    ? messages.slice(0, lastUserIndex + 1)
    : messages;
  const runningTurnMessages = lastUserIndex >= 0
    ? messages.slice(lastUserIndex + 1)
    : [];
  const assistantMessage = buildResumedAssistantMessage(
    runningTurnMessages,
    fallbackAssistantId,
    now,
  );

  return {
    assistantMessage,
    checkpointMessageId,
    messages: [...preservedMessages, assistantMessage],
  };
}

export function prepareConversationStreamFullReplay(
  messages: ChatMessage[],
  fallbackAssistantId: string,
  now = Date.now(),
): ConversationStreamResumeSnapshot {
  const lastUserIndex = findLastUserMessageIndex(messages);
  const preservedMessages = lastUserIndex >= 0
    ? messages.slice(0, lastUserIndex + 1)
    : messages;
  const assistantMessage = createEmptyRunningAssistantMessage(
    fallbackAssistantId,
    now,
  );
  return {
    assistantMessage,
    checkpointMessageId: null,
    messages: [...preservedMessages, assistantMessage],
  };
}

function buildResumedAssistantMessage(
  messages: ChatMessage[],
  fallbackAssistantId: string,
  now: number,
): ChatMessage {
  const displayMessages = buildChatDisplayMessages(messages);
  const assistantMessages = displayMessages.filter(
    (message) => message.role === "assistant" || message.role === "error",
  );
  const baseMessage = assistantMessages[assistantMessages.length - 1] ?? null;
  let processItems: ChatAssistantProcessItem[] = [];
  let toolCalls: ChatToolProcessItem[] = [];

  displayMessages.forEach((message) => {
    if (message.role === "tool") {
      const tool = readToolProcessItemFromMessage(message);
      if (tool) {
        processItems = upsertToolProcessItemInTimeline(processItems, tool);
        toolCalls = upsertToolProcessItem(toolCalls, tool);
      }
      return;
    }
    if (message.role !== "assistant" && message.role !== "error") return;

    for (const item of message.processItems ?? []) {
      processItems = item.type === "tool"
        ? upsertToolProcessItemInTimeline(processItems, item.tool)
        : [...processItems, item];
    }
    const bodyContent = resolveAssistantBodyContent(message);
    if (bodyContent.trim()) {
      processItems = appendAssistantContentProcess(processItems, bodyContent);
    }
    for (const tool of message.toolCalls ?? []) {
      toolCalls = upsertToolProcessItem(toolCalls, tool);
    }
  });

  const contextMeasurement = getLastMessageContextMeasurement(assistantMessages);
  return {
    id: baseMessage?.id ?? fallbackAssistantId,
    role: "assistant",
    content: "",
    thinkingContent: "",
    status: "running",
    usage: findLatestUsage(assistantMessages),
    contextTokens: contextMeasurement.tokens,
    contextTokensEstimated: contextMeasurement.estimated,
    isThinkingExpanded: false,
    thinkingStartedAt: findEarliestTimestamp(assistantMessages) ?? now,
    thinkingFinishedAt: null,
    processItems,
    toolCalls,
    createdAt: findEarliestTimestamp(assistantMessages) ?? now,
    updatedAt: now,
  };
}

function createEmptyRunningAssistantMessage(
  id: string,
  now: number,
): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    thinkingContent: "",
    status: "running",
    usage: null,
    contextTokens: null,
    contextTokensEstimated: false,
    isThinkingExpanded: true,
    thinkingStartedAt: now,
    thinkingFinishedAt: null,
    processItems: [],
    toolCalls: [],
    createdAt: now,
    updatedAt: now,
  };
}

function findLastUserMessageIndex(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") return index;
  }
  return -1;
}

function findEarliestTimestamp(messages: ChatMessage[]) {
  let earliest: number | null = null;
  messages.forEach((message) => {
    if (message.createdAt === null || message.createdAt === undefined) return;
    earliest = earliest === null ? message.createdAt : Math.min(earliest, message.createdAt);
  });
  return earliest;
}

function findLatestUsage(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].usage) return messages[index].usage;
  }
  return null;
}
