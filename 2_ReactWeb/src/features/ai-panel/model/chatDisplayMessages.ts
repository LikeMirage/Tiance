import {
  readToolProcessItemFromMessage,
  isChatNotificationMessage,
  upsertToolProcessItem,
  type ChatAssistantProcessItem,
  type ChatMessage,
  type ChatToolProcessItem,
} from "./chatMessage";
import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";

type BuildChatDisplayMessagesOptions = {
  runtimeStatus?: ConversationRuntimeStatus | null;
};

/** View-only cache. Message objects are immutable; replacing any source message
 * invalidates its entire user turn. Entries removed from the input are released.
 */
export function createChatDisplayProjector() {
  type Entry = {
    sources: ChatMessage[];
    status: BuildChatDisplayMessagesOptions["runtimeStatus"];
    display: ChatMessage[];
  };
  let entries = new Map<string, Entry>();
  let previous: ChatMessage[] = [];
  return (messages: ChatMessage[], options: BuildChatDisplayMessagesOptions = {}) => {
    const nextEntries = new Map<string, Entry>();
    const result: ChatMessage[] = [];
    let start = 0;
    for (let end = 1; end <= messages.length; end += 1) {
      if (end < messages.length && messages[end].role !== "user") continue;
      const key = messages[start].id;
      // Every preceding turn is closed, independently of the current run.
      const status = end === messages.length ? options.runtimeStatus : "idle";
      let entry = entries.get(key);
      if (!entry || entry.status !== status || entry.sources.length !== end - start
        || entry.sources.some((source, index) => source !== messages[start + index])) {
        const sources = messages.slice(start, end);
        entry = { sources, status, display: buildChatDisplayMessages(sources, { runtimeStatus: status }) };
      }
      nextEntries.set(key, entry);
      for (const message of entry.display) result.push(message);
      start = end;
    }
    entries = nextEntries;
    if (result.length === previous.length && result.every((message, index) => message === previous[index])) {
      return previous;
    }
    previous = result;
    return result;
  };
}

export function buildChatDisplayMessages(
  messages: ChatMessage[],
  options: BuildChatDisplayMessagesOptions = {},
) {
  const visibleMessages = messages.filter((message) => !message.notificationPending);
  const groupedMessages = groupToolMessagesWithAssistant(visibleMessages);
  const displayMessages = coalesceAssistantTurnProcesses(groupedMessages);
  const finalized = finalizeTerminalConversationTurns(displayMessages, options.runtimeStatus);
  if (options.runtimeStatus !== "running") return finalized;
  const lastUser = finalized.reduce((last, message, index) => message.role === "user" ? index : last, -1);
  const activeIndex = finalized.reduce((last, message, index) => message.role === "assistant" && message.finishReason !== "output_limit" ? index : last, -1);
  if (activeIndex <= lastUser || finalized[activeIndex].status === "running"
    || finalized[activeIndex].status === "cancelled" || finalized[activeIndex].status === "error") return finalized;
  return finalized.map((message, index) => index === activeIndex ? { ...message, status: "running" } : message);
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
      const previousIndex = findToolOwnerIndex(grouped, item);
      const previousMessage = grouped[previousIndex];
      if (
        previousMessage &&
        (previousMessage.role === "assistant" || previousMessage.role === "error") &&
        !previousMessage.runAttemptFailure &&
        hasMatchingToolCall(previousMessage, item.callId, item.name)
      ) {
        grouped[previousIndex] = upsertToolResultIntoAssistant(
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

    if (pendingItems.length > 0 && isChatNotificationMessage(message)) {
      // Older histories can contain a tool result before its assistant row.
      // Notices between them must not become a new tool-group boundary.
      pendingMessages.push(message);
      return;
    }

    if (
      pendingItems.length > 0 &&
      message.role === "assistant" &&
      message.finishReason !== "output_limit"
    ) {
      const nextToolCalls = pendingItems.reduce(
        (items, item) => upsertToolProcessItem(items, item),
        message.toolCalls ?? [],
      );
      grouped.push({
        ...message,
        toolCalls: nextToolCalls,
        ...(pendingMessages.some(isChatNotificationMessage) ? {
          processItems: [
            ...pendingMessages.flatMap((item) => buildProcessItemsForMergedAssistantMessage(item, false)),
            ...(message.processItems ?? []).filter((item) => item.type !== "tool"
              || !pendingItems.some((tool) => (tool.callId && tool.callId === item.tool.callId)
                || (!tool.callId && tool.name === item.tool.name))),
          ],
        } : {}),
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
) {
  let changed = false;
  const result: ChatMessage[] = [];
  let assistantTurnMessages: ChatMessage[] = [];

  const flushAssistantTurn = () => {
    if (assistantTurnMessages.length === 0) return;
    const mergedTurn = mergeAssistantTurnMessages(assistantTurnMessages);
    if (mergedTurn.length !== assistantTurnMessages.length) {
      changed = true;
    }
    result.push(...mergedTurn);
    assistantTurnMessages = [];
  };

  messages.forEach((message) => {
    if (message.finishReason === "output_limit") {
      flushAssistantTurn();
      result.push(message);
      return;
    }
    if (message.role === "assistant" || message.role === "tool" || isChatNotificationMessage(message)) {
      assistantTurnMessages.push(message);
      return;
    }
    flushAssistantTurn();
    result.push(message);
  });

  flushAssistantTurn();
  return changed ? result : messages;
}

function mergeAssistantTurnMessages(
  messages: ChatMessage[],
) {
  const finalMessage = findLastAssistantLikeMessage(messages);
  if (!finalMessage) return messages;
  const finalIndex = messages.indexOf(finalMessage);
  const firstAssistant = messages.find((message) => message.role === "assistant")!;
  const leading = messages.slice(0, messages.indexOf(firstAssistant));
  const trailing = messages.slice(finalIndex + 1);
  const turnMessages = messages.slice(messages.indexOf(firstAssistant), finalIndex + 1);
  if (turnMessages.length === 1) return messages;

  const processItems = turnMessages.flatMap((message) =>
    buildProcessItemsForMergedAssistantMessage(message, message.id === finalMessage.id),
  );
  const toolCalls = turnMessages.flatMap((message) => message.toolCalls ?? []);
  const terminalToolStatus = resolveMessageTerminalToolStatus(finalMessage);
  const finalizedProcessItems = terminalToolStatus
    ? finalizeUnresolvedProcessTools(processItems, terminalToolStatus, finalMessage)
    : processItems;
  const finalizedToolCalls = terminalToolStatus
    ? toolCalls.map((tool) => finalizeUnresolvedTool(tool, terminalToolStatus, finalMessage))
    : toolCalls;
  const turnUsage = mergeAssistantTurnUsage(turnMessages.filter((message) => !isChatNotificationMessage(message)));

  return [...leading, {
    ...finalMessage,
    // A notification or a new model round must never replace the mounted turn.
    displayKey: firstAssistant.displayKey ?? firstAssistant.id,
    createdAt: firstAssistant.createdAt ?? finalMessage.createdAt,
    processItems: finalizedProcessItems,
    toolCalls: finalizedToolCalls,
    usage: turnUsage,
  }, ...trailing];
}

const CHAT_USAGE_FIELDS = [
  "prompt_tokens",
  "completion_tokens",
  "total_tokens",
  "prompt_cache_hit_tokens",
  "prompt_cache_miss_tokens",
  "reasoning_tokens",
] as const satisfies readonly (keyof ChatUsage)[];

function mergeAssistantTurnUsage(messages: ChatMessage[]): ChatUsage | null {
  const usages = messages.flatMap((message) => message.usage ? [message.usage] : []);
  if (usages.length === 0) return null;
  if (usages.length === 1) return usages[0];

  const merged: ChatUsage = {};
  for (const field of CHAT_USAGE_FIELDS) {
    const values = usages
      .map((usage) => usage[field])
      .filter((value): value is number => typeof value === "number");
    if (values.length > 0) {
      merged[field] = values.reduce((total, value) => total + value, 0);
    }
  }

  if (
    merged.total_tokens === undefined &&
    (merged.prompt_tokens !== undefined || merged.completion_tokens !== undefined)
  ) {
    merged.total_tokens = (merged.prompt_tokens ?? 0) + (merged.completion_tokens ?? 0);
  }

  const estimatedFields = [...new Set(usages.flatMap((usage) => usage.estimated_fields ?? []))]
    .sort();
  if (estimatedFields.length > 0) {
    merged.estimated_fields = estimatedFields;
  }
  return merged;
}

function findLastAssistantLikeMessage(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant") {
      return message;
    }
  }
  return null;
}

function buildProcessItemsForMergedAssistantMessage(
  message: ChatMessage,
  isFinalMessage: boolean,
): ChatAssistantProcessItem[] {
  if (isChatNotificationMessage(message)) {
    return [{ id: message.id, type: "notification", message }];
  }
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

function findToolOwnerIndex(messages: ChatMessage[], tool: ChatToolProcessItem) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "user" || message.finishReason === "output_limit") break;
    if (message.role === "assistant" && hasMatchingToolCall(message, tool.callId, tool.name)) return index;
    if (!isChatNotificationMessage(message) && message.role !== "assistant" && message.role !== "tool") break;
  }
  return -1;
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
    const outcome = messages.slice(start, end).map((message) => message.runOutcome)
      .find((value) => value?.status === "error" || value?.status === "cancelled");
    const explicitStatus = outcome?.status === "error" || outcome?.status === "cancelled" ? outcome.status : finalAssistant
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
