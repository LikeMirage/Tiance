import {
  readToolProcessItemFromMessage,
  upsertToolProcessItem,
  type ChatAssistantProcessItem,
  type ChatMessage,
  type ChatToolProcessItem,
} from "./chatMessage";
import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";

type BuildChatDisplayMessagesOptions = {
  runtimeStatus?: ConversationRuntimeStatus | null;
};

export function buildChatDisplayMessages(
  messages: ChatMessage[],
  options: BuildChatDisplayMessagesOptions = {},
) {
  const groupedMessages = groupToolMessagesWithAssistant(messages);
  const displayMessages = coalesceAssistantTurnProcesses(
    groupedMessages,
    options.runtimeStatus,
  );
  return finalizeTerminalConversationTurns(displayMessages, options.runtimeStatus);
}

export function resolveAssistantBodyContent(message: ChatMessage) {
  const processContentItems = (message.processItems ?? [])
    .filter((item): item is Extract<ChatAssistantProcessItem, { type: "content" }> =>
      item.type === "content",
    )
    .map((item) => item.content)
    .filter((content) => content.trim().length > 0);

  if (processContentItems.length === 0) {
    return message.content;
  }

  const fullProcessContent = processContentItems.join("");
  if (message.content.startsWith(fullProcessContent)) {
    return message.content.slice(fullProcessContent.length);
  }

  const matchedProcessContent = [...processContentItems]
    .sort((left, right) => right.length - left.length)
    .find((content) => message.content === content || message.content.startsWith(content));

  return matchedProcessContent
    ? message.content.slice(matchedProcessContent.length)
    : message.content;
}

function groupToolMessagesWithAssistant(messages: ChatMessage[]) {
  let changed = false;
  const grouped: ChatMessage[] = [];
  let pendingMessages: ChatMessage[] = [];
  let pendingItems: ChatToolProcessItem[] = [];

  const flushPendingMessages = () => {
    if (pendingMessages.length === 0) return;
    grouped.push(...pendingMessages);
    pendingMessages = [];
    pendingItems = [];
  };

  messages.forEach((message) => {
    if (message.role === "tool") {
      const item = readToolProcessItemFromMessage(message);
      if (!item) {
        flushPendingMessages();
        grouped.push(message);
        return;
      }
      const previousMessage = grouped[grouped.length - 1];
      if (
        previousMessage &&
        (previousMessage.role === "assistant" || previousMessage.role === "error") &&
        hasMatchingToolCall(previousMessage, item.callId, item.name)
      ) {
        grouped[grouped.length - 1] = upsertToolResultIntoAssistant(
          previousMessage,
          item,
        );
        changed = true;
        return;
      }
      changed = true;
      pendingMessages.push(message);
      pendingItems = upsertToolProcessItem(pendingItems, item);
      return;
    }

    if (
      pendingItems.length > 0 &&
      (message.role === "assistant" || message.role === "error")
    ) {
      const nextToolCalls = pendingItems.reduce(
        (items, item) => upsertToolProcessItem(items, item),
        message.toolCalls ?? [],
      );
      grouped.push({
        ...message,
        toolCalls: nextToolCalls,
      });
      pendingMessages = [];
      pendingItems = [];
      return;
    }

    flushPendingMessages();
    grouped.push(message);
  });

  flushPendingMessages();
  return changed ? grouped : messages;
}

function coalesceAssistantTurnProcesses(
  messages: ChatMessage[],
  runtimeStatus: ConversationRuntimeStatus | null | undefined,
) {
  let changed = false;
  const result: ChatMessage[] = [];
  let assistantTurnMessages: ChatMessage[] = [];

  const flushAssistantTurn = (isLastTurn: boolean) => {
    if (assistantTurnMessages.length === 0) return;
    const mergedTurn = mergeAssistantTurnMessages(
      assistantTurnMessages,
      isAssistantTurnClosed(runtimeStatus, isLastTurn),
    );
    if (mergedTurn.length !== assistantTurnMessages.length) {
      changed = true;
    }
    result.push(...mergedTurn);
    assistantTurnMessages = [];
  };

  messages.forEach((message) => {
    if (message.role === "assistant" || message.role === "error" || message.role === "tool") {
      assistantTurnMessages.push(message);
      return;
    }
    flushAssistantTurn(false);
    result.push(message);
  });

  flushAssistantTurn(true);
  return changed ? result : messages;
}

function mergeAssistantTurnMessages(
  messages: ChatMessage[],
  isTurnClosed: boolean,
) {
  if (messages.length <= 1) return messages;
  const finalMessage = findLastAssistantLikeMessage(messages);
  if (!finalMessage) return messages;
  if (finalMessage.status === "running") return messages;
  if (
    !resolveAssistantBodyContent(finalMessage).trim() &&
    resolveMessageTerminalToolStatus(finalMessage) === null &&
    !isTurnClosed
  ) {
    return messages;
  }

  const processItems = messages.flatMap((message) =>
    buildProcessItemsForMergedAssistantMessage(message, message.id === finalMessage.id),
  );
  const toolCalls = messages.flatMap((message) => message.toolCalls ?? []);
  const terminalToolStatus = resolveMessageTerminalToolStatus(finalMessage);
  const finalizedProcessItems = terminalToolStatus
    ? finalizeUnresolvedProcessTools(processItems, terminalToolStatus, finalMessage)
    : processItems;
  const finalizedToolCalls = terminalToolStatus
    ? toolCalls.map((tool) => finalizeUnresolvedTool(tool, terminalToolStatus, finalMessage))
    : toolCalls;

  return [{
    ...finalMessage,
    createdAt: messages[0].createdAt ?? finalMessage.createdAt,
    processItems: finalizedProcessItems,
    toolCalls: finalizedToolCalls,
  }];
}

function isAssistantTurnClosed(
  runtimeStatus: ConversationRuntimeStatus | null | undefined,
  isLastTurn: boolean,
) {
  if (!isLastTurn) return true;
  return runtimeStatus === "idle" || runtimeStatus === "error";
}

function findLastAssistantLikeMessage(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant" || message.role === "error") {
      return message;
    }
  }
  return null;
}

function buildProcessItemsForMergedAssistantMessage(
  message: ChatMessage,
  isFinalMessage: boolean,
): ChatAssistantProcessItem[] {
  if (message.role === "tool") {
    const item = readToolProcessItemFromMessage(message);
    return item ? [{ id: item.id, type: "tool", tool: item }] : [];
  }

  const items = [...(message.processItems ?? [])];
  if (!isFinalMessage) {
    const bodyContent = resolveAssistantBodyContent(message).trim();
    if (bodyContent) {
      items.push({
        id: `content-${message.id}-body`,
        type: "content",
        content: bodyContent,
      });
    }
  }
  return items;
}

function hasMatchingToolCall(
  message: ChatMessage,
  callId: string,
  name: string,
) {
  return (message.toolCalls ?? []).some((item) =>
    (callId && item.callId === callId) || (!callId && item.name === name),
  );
}

function upsertToolResultIntoAssistant(
  message: ChatMessage,
  toolItem: ChatToolProcessItem,
): ChatMessage {
  const toolCalls = upsertToolProcessItem(message.toolCalls ?? [], toolItem);
  return {
    ...message,
    processItems: (message.processItems ?? []).map((item) =>
      item.type === "tool" &&
      ((toolItem.callId && item.tool.callId === toolItem.callId) ||
        (!toolItem.callId && item.tool.name === toolItem.name))
        ? { ...item, tool: mergeToolTiming(item.tool, toolItem) }
        : item,
    ),
    toolCalls,
  };
}

function mergeToolTiming(
  current: ChatToolProcessItem,
  next: ChatToolProcessItem,
): ChatToolProcessItem {
  return {
    ...next,
    startedAt: current.startedAt ?? next.startedAt,
    finishedAt: next.finishedAt ?? current.finishedAt,
  };
}

function finalizeUnresolvedProcessTools(
  items: ChatAssistantProcessItem[],
  terminalStatus: "cancelled" | "error",
  finalMessage: ChatMessage,
) {
  return items.map((item) => {
    if (item.type !== "tool") return item;
    const tool = finalizeUnresolvedTool(item.tool, terminalStatus, finalMessage);
    return tool === item.tool ? item : { ...item, tool };
  });
}

function finalizeUnresolvedTool(
  tool: ChatToolProcessItem,
  terminalStatus: "cancelled" | "error",
  finalMessage: ChatMessage,
): ChatToolProcessItem {
  if (tool.status !== "preparing" && tool.status !== "running") return tool;
  return {
    ...tool,
    status: terminalStatus,
    finishedAt:
      finalMessage.updatedAt ??
      finalMessage.createdAt ??
      tool.finishedAt ??
      tool.startedAt ??
      0,
  };
}

function finalizeTerminalConversationTurns(
  messages: ChatMessage[],
  runtimeStatus: ConversationRuntimeStatus | null | undefined,
) {
  if (messages.length === 0) return messages;
  let changed = false;
  let turnStart = 0;
  const next = [...messages];

  const finalizeTurn = (start: number, end: number, isLastTurn: boolean) => {
    const finalAssistant = findLastAssistantLikeMessage(messages.slice(start, end));
    const explicitStatus = finalAssistant
      ? resolveMessageTerminalToolStatus(finalAssistant)
      : null;
    const terminalStatus = explicitStatus ?? resolveRuntimeTerminalToolStatus(
      runtimeStatus,
      isLastTurn,
    );
    if (!terminalStatus) return;

    for (let index = start; index < end; index += 1) {
      const message = next[index];
      if (message.role !== "assistant" && message.role !== "error") continue;
      const finalizedMessage = finalizeMessageUnresolvedTools(
        message,
        terminalStatus,
        finalAssistant ?? message,
      );
      if (finalizedMessage !== message) {
        next[index] = finalizedMessage;
        changed = true;
      }
    }
  };

  for (let index = 0; index <= messages.length; index += 1) {
    const isBoundary = index === messages.length || messages[index].role === "user";
    if (!isBoundary) continue;
    if (index > turnStart) {
      finalizeTurn(turnStart, index, index === messages.length);
    }
    turnStart = index;
  }
  return changed ? next : messages;
}

function finalizeMessageUnresolvedTools(
  message: ChatMessage,
  terminalStatus: "cancelled" | "error",
  finalMessage: ChatMessage,
) {
  const processItems = finalizeUnresolvedProcessTools(
    message.processItems ?? [],
    terminalStatus,
    finalMessage,
  );
  const toolCalls = (message.toolCalls ?? []).map((tool) =>
    finalizeUnresolvedTool(tool, terminalStatus, finalMessage),
  );
  const processChanged = processItems.some(
    (item, index) => item !== message.processItems?.[index],
  );
  const toolsChanged = toolCalls.some(
    (tool, index) => tool !== message.toolCalls?.[index],
  );
  return processChanged || toolsChanged
    ? { ...message, processItems, toolCalls }
    : message;
}

function resolveMessageTerminalToolStatus(
  message: ChatMessage,
): "cancelled" | "error" | null {
  if (message.status === "cancelled") return "cancelled";
  if (message.status === "error" || message.role === "error") return "error";
  return null;
}

function resolveRuntimeTerminalToolStatus(
  runtimeStatus: ConversationRuntimeStatus | null | undefined,
  isLastTurn: boolean,
): "cancelled" | "error" | null {
  if (!isLastTurn) return "cancelled";
  if (runtimeStatus === "error") return "error";
  if (runtimeStatus === "idle") return "cancelled";
  return null;
}
