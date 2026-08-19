import type { ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ChatCompletionMessageContentPart,
  ConversationMessageReferences,
  ChatToolCallEvent,
  ChatToolResultEvent,
} from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ConversationMessage,
  ConversationRunOutcome,
} from "../../../entities/llm-chat/model/conversation";

export type ChatToolProcessStatus =
  | "preparing"
  | "running"
  | "done"
  | "error"
  | "cancelled";

export type ChatToolProcessItem = {
  id: string;
  callId: string;
  name: string;
  arguments: string;
  result: string;
  error: string;
  ok: boolean | null;
  status: ChatToolProcessStatus;
  startedAt: number | null;
  finishedAt: number | null;
};

export type ChatAssistantProcessItem =
  | {
      id: string;
      type: "thinking";
      content: string;
      status: "running" | "done";
      startedAt: number;
      finishedAt: number | null;
    }
  | {
      id: string;
      type: "tool";
      tool: ChatToolProcessItem;
    }
  | {
      id: string;
      type: "tool_preparing";
      startedAt: number;
    }
  | {
      id: string;
      type: "content";
      content: string;
    };

export type ChatMessage = {
  id: string;
  role: "system" | "user" | "assistant" | "error" | "tool";
  content: string;
  contentParts?: ChatCompletionMessageContentPart[];
  references?: ConversationMessageReferences;
  providerId?: string | null;
  modelId?: string | null;
  targetProviderId?: string | null;
  targetModelId?: string | null;
  thinkingContent: string;
  status: string;
  usage: ChatUsage | null;
  contextTokens?: number | null;
  contextTokensEstimated?: boolean;
  isThinkingExpanded: boolean;
  thinkingStartedAt: number | null;
  thinkingFinishedAt: number | null;
  processItems?: ChatAssistantProcessItem[];
  toolCalls?: ChatToolProcessItem[];
  llmToolCalls?: ChatToolCallEvent[];
  name?: string | null;
  toolCallId?: string | null;
  createdAt?: number | null;
  updatedAt?: number | null;
  originMessageId?: string;
  variantGroupId?: string | null;
  variantIndex?: number;
  runOutcome?: ConversationRunOutcome;
};

export function mapConversationMessages(
  messages: ConversationMessage[],
  runOutcomes: ConversationRunOutcome[] = [],
): ChatMessage[] {
  const mappedMessages = messages.map((message) => ({
    id: message.message_id,
    role: mapConversationMessageRole(message.role),
    content: message.content,
    contentParts: message.content_parts ?? [],
    references: message.references,
    providerId: message.provider_id,
    modelId: message.model_id,
    targetProviderId: message.target_provider_id ?? null,
    targetModelId: message.target_model_id ?? null,
    thinkingContent: message.thinking_content ?? "",
    status: message.status,
    usage: message.usage ?? null,
    contextTokens: message.context_tokens ?? null,
    contextTokensEstimated: message.context_tokens_estimated ?? false,
    isThinkingExpanded: false,
    thinkingStartedAt: null,
    thinkingFinishedAt: null,
    processItems: buildProcessItemsFromConversationMessage(message),
    toolCalls: buildToolProcessItemsFromConversationMessage(message),
    llmToolCalls: normalizeConversationToolCalls(message.tool_calls),
    name: message.name ?? null,
    toolCallId: message.tool_call_id ?? null,
    createdAt: parseMessageTimestamp(message.created_at),
    updatedAt: parseMessageTimestamp(message.updated_at),
    originMessageId: message.origin_message_id || message.message_id,
    variantGroupId: message.variant_group_id ?? null,
    variantIndex: Math.max(1, message.variant_index ?? 1),
  }));
  const mappedOutcomes: ChatMessage[] = runOutcomes.map((outcome) => ({
    id: `run-outcome:${outcome.run_id}`,
    role: "error",
    content: outcome.error_message,
    thinkingContent: "",
    status: "error",
    usage: null,
    isThinkingExpanded: false,
    thinkingStartedAt: null,
    thinkingFinishedAt: null,
    createdAt: parseMessageTimestamp(outcome.settled_at),
    updatedAt: parseMessageTimestamp(outcome.settled_at),
    originMessageId: `run-outcome:${outcome.run_id}`,
    runOutcome: outcome,
  }));
  return [...mappedMessages, ...mappedOutcomes]
    .map((message, stableIndex) => ({ message, stableIndex }))
    .sort((left, right) => {
      const timeDifference = (left.message.createdAt ?? 0) - (right.message.createdAt ?? 0);
      return timeDifference || left.stableIndex - right.stableIndex;
    })
    .map(({ message }) => message);
}

export function getLastMessageContextTokens(messages: ChatMessage[]) {
  return getLastMessageContextMeasurement(messages).tokens;
}

export function getLastMessageContextMeasurement(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const contextTokens = messages[index].contextTokens;
    if (contextTokens !== null && contextTokens !== undefined) {
      return {
        estimated: messages[index].contextTokensEstimated ?? false,
        tokens: contextTokens,
      };
    }
  }
  return { estimated: false, tokens: null };
}

export function buildChatMessageClass(message: ChatMessage) {
  const classes = ["chat-msg"];
  if (message.role === "system") classes.push("chat-msg--system");
  if (message.role === "user") classes.push("chat-msg--user");
  if (message.role === "error") classes.push("chat-msg--error");
  if (message.role === "tool") classes.push("chat-msg--tool");
  return classes.join(" ");
}

function mapConversationMessageRole(role: string): ChatMessage["role"] {
  if (role === "system") return "system";
  if (role === "user") return "user";
  if (role === "error") return "error";
  if (role === "tool") return "tool";
  if (role === "assistant") return "assistant";
  throw new Error(`未知会话消息角色：${role}`);
}

const USER_MESSAGE_EXPAND_TEXT_LENGTH = 420;
const USER_MESSAGE_EXPAND_LINE_COUNT = 5;

export function shouldOfferUserMessageExpand(content: string) {
  return shouldOfferUserMessageExpandFromParts([content]);
}

export function shouldOfferUserMessageExpandFromParts(parts: string[]) {
  if (parts.length === 0) return false;
  let totalLength = 0;
  let lineCount = 1;

  for (let partIndex = 0; partIndex < parts.length; partIndex += 1) {
    const part = parts[partIndex];
    if (partIndex > 0) {
      totalLength += 1;
      lineCount += 1;
      if (lineCount > USER_MESSAGE_EXPAND_LINE_COUNT) return true;
    }
    totalLength += part.length;
    if (totalLength > USER_MESSAGE_EXPAND_TEXT_LENGTH) return true;

    for (let index = 0; index < part.length; index += 1) {
      if (part.charCodeAt(index) === 10) {
        lineCount += 1;
        if (lineCount > USER_MESSAGE_EXPAND_LINE_COUNT) return true;
      }
    }
  }

  return false;
}

export function resolveThinkingElapsedSeconds(message: ChatMessage, clockTick: number) {
  if (message.thinkingStartedAt === null) return null;
  const end = message.thinkingFinishedAt ?? clockTick;
  return Math.max(0, Math.floor((end - message.thinkingStartedAt) / 1000));
}

export function createRunningToolProcessItem(
  toolCall: ChatToolCallEvent,
  now = Date.now(),
): ChatToolProcessItem {
  return {
    id: toolProcessId(toolCall.call_id, toolCall.name),
    callId: toolCall.call_id,
    name: toolCall.name,
    arguments: toolCall.arguments,
    result: "",
    error: "",
    ok: null,
    status: "running",
    startedAt: now,
    finishedAt: null,
  };
}

export function createPreparingToolProcessItem(
  toolCall: ChatToolCallEvent,
  now = Date.now(),
): ChatToolProcessItem {
  return {
    ...createRunningToolProcessItem(toolCall, now),
    status: "preparing",
  };
}

export function upsertPreparingToolProcessDeltaInTimeline(
  items: ChatAssistantProcessItem[],
  toolCall: ChatToolCallEvent,
  now = Date.now(),
) {
  const id = toolProcessId(toolCall.call_id, toolCall.name);
  let index = items.findIndex(
    (item) => item.type === "tool" && (
      item.tool.id === id ||
      (toolCall.call_id && item.tool.callId === toolCall.call_id)
    ),
  );
  if (index < 0 && !toolCall.call_id) {
    for (let itemIndex = items.length - 1; itemIndex >= 0; itemIndex -= 1) {
      const item = items[itemIndex];
      if (item.type === "tool" && item.tool.status === "preparing") {
        index = itemIndex;
        break;
      }
    }
  }
  if (index < 0) {
    const tool = createPreparingToolProcessItem(toolCall, now);
    return [
      ...items,
      {
        id: tool.id,
        type: "tool" as const,
        tool,
      },
    ];
  }
  const next = [...items];
  const item = next[index];
  if (item.type !== "tool") return items;
  const nextTool = {
    ...item.tool,
    id,
    callId: toolCall.call_id || item.tool.callId,
    name: toolCall.name || item.tool.name,
    arguments: item.tool.arguments + toolCall.arguments,
    status: "preparing" as const,
    startedAt: item.tool.startedAt ?? now,
    finishedAt: null,
  };
  next[index] = {
    id: nextTool.id,
    type: "tool",
    tool: nextTool,
  };
  return next;
}

export function createPendingToolProcessItem(
  toolCall: ChatToolCallEvent,
  startedAt: number | null = null,
): ChatToolProcessItem {
  return {
    ...createRunningToolProcessItem(toolCall, startedAt ?? 0),
    status: "running",
    startedAt,
  };
}

export function createFinishedToolProcessItem(
  toolResult: ChatToolResultEvent,
  now = Date.now(),
): ChatToolProcessItem {
  return {
    id: toolProcessId(toolResult.call_id, toolResult.name),
    callId: toolResult.call_id,
    name: toolResult.name,
    arguments: toolResult.arguments,
    result: toolResult.content,
    error: toolResult.error || "",
    ok: toolResult.ok,
    status: toolResult.ok ? "done" : "error",
    startedAt: now,
    finishedAt: now,
  };
}

const toolProcessItemByMessageCache = new WeakMap<ChatMessage, { item: ChatToolProcessItem | null }>();

export function readToolProcessItemFromMessage(
  message: ChatMessage,
): ChatToolProcessItem | null {
  if (message.role !== "tool") return null;
  const cached = toolProcessItemByMessageCache.get(message);
  if (cached) return cached.item;

  try {
    const payload = JSON.parse(message.content) as {
      arguments?: unknown;
      call_id?: unknown;
      error?: unknown;
      ok?: unknown;
      result?: unknown;
      tool?: unknown;
    };
    const name = typeof payload.tool === "string" ? payload.tool : "tool";
    const callId = typeof payload.call_id === "string" ? payload.call_id : "";
    const ok = typeof payload.ok === "boolean" ? payload.ok : null;
    const item = {
      id: toolProcessId(callId, name),
      callId,
      name,
      arguments: stringifyToolValue(payload.arguments),
      result: stringifyToolValue(payload.result),
      error: typeof payload.error === "string" ? payload.error : "",
      ok,
      status: resolveToolProcessStatus(message.status, ok),
      startedAt: message.createdAt ?? null,
      finishedAt: message.createdAt ?? null,
    };
    toolProcessItemByMessageCache.set(message, { item });
    return item;
  } catch {
    toolProcessItemByMessageCache.set(message, { item: null });
    return null;
  }
}

export function upsertToolProcessItem(
  items: ChatToolProcessItem[],
  nextItem: ChatToolProcessItem,
) {
  const index = items.findIndex((item) => matchesToolProcessItem(item, nextItem));
  if (index < 0) return [...items, nextItem];
  const next = [...items];
  next[index] = mergeToolProcessItem(next[index], nextItem);
  return next;
}

export function appendThinkingProcessDelta(
  items: ChatAssistantProcessItem[],
  content: string,
  now: number,
) {
  const lastItem = items[items.length - 1];
  if (lastItem?.type === "thinking" && lastItem.status === "running") {
    const next = [...items];
    next[next.length - 1] = {
      ...lastItem,
      content: lastItem.content + content,
    };
    return next;
  }

  return [
    ...items,
    {
      id: `thinking-${crypto.randomUUID()}`,
      type: "thinking" as const,
      content,
      status: "running" as const,
      startedAt: now,
      finishedAt: null,
    },
  ];
}

export function finishOpenThinkingProcess(
  items: ChatAssistantProcessItem[],
  now: number,
) {
  const lastItem = items[items.length - 1];
  if (lastItem?.type !== "thinking" || lastItem.status !== "running") {
    return items;
  }
  const next = [...items];
  next[next.length - 1] = {
    ...lastItem,
    status: "done",
    finishedAt: lastItem.finishedAt ?? now,
  };
  return next;
}

export function appendToolPreparingProcess(
  items: ChatAssistantProcessItem[],
  now: number,
) {
  const lastItem = items[items.length - 1];
  const baseItems = finishOpenThinkingProcess(items, now);
  if (lastItem?.type === "tool_preparing") {
    return baseItems;
  }
  return [
    ...baseItems,
    {
      id: `tool-preparing-${crypto.randomUUID()}`,
      type: "tool_preparing" as const,
      startedAt: now,
    },
  ];
}

export function appendAssistantContentProcess(
  items: ChatAssistantProcessItem[],
  content: string,
) {
  if (!content.trim()) return items;
  return [
    ...items,
    {
      id: `content-${crypto.randomUUID()}`,
      type: "content" as const,
      content,
    },
  ];
}

export function removeToolPreparingProcess(items: ChatAssistantProcessItem[]) {
  return items.filter((item) => item.type !== "tool_preparing");
}

export function upsertToolProcessItemInTimeline(
  items: ChatAssistantProcessItem[],
  toolItem: ChatToolProcessItem,
) {
  const index = items.findIndex(
    (item) => item.type === "tool" && matchesToolProcessItem(item.tool, toolItem),
  );
  if (index < 0) {
    return [
      ...items,
      {
        id: toolItem.id,
        type: "tool" as const,
        tool: toolItem,
      },
    ];
  }
  const next = [...items];
  const current = next[index];
  if (current.type !== "tool") return items;
  next[index] = {
    id: toolItem.id,
    type: "tool",
    tool: mergeToolProcessItem(current.tool, toolItem),
  };
  return next;
}

export function toolProcessId(callId: string, toolName: string) {
  return `tool-${callId || toolName || crypto.randomUUID()}`;
}

function resolveToolProcessStatus(
  messageStatus: string,
  ok: boolean | null,
): ChatToolProcessStatus {
  if (messageStatus === "running") return "running";
  if (messageStatus === "cancelled") return "cancelled";
  if (messageStatus === "error" || ok === false) return "error";
  return "done";
}

function stringifyToolValue(value: unknown) {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function buildToolProcessItemsFromConversationMessage(
  message: ConversationMessage,
): ChatToolProcessItem[] {
  const startedAt = parseMessageTimestamp(message.created_at);
  return normalizeConversationToolCalls(message.tool_calls)
    .map((toolCall) => createPendingToolProcessItem(toolCall, startedAt));
}

function buildProcessItemsFromConversationMessage(
  message: ConversationMessage,
): ChatAssistantProcessItem[] {
  if (message.role !== "assistant" && message.role !== "error") {
    return [];
  }
  const toolCalls = normalizeConversationToolCalls(message.tool_calls);
  const items: ChatAssistantProcessItem[] = [];
  const thinkingContent = message.thinking_content?.trim() ?? "";
  if (thinkingContent) {
    items.push({
      id: `thinking-${message.message_id}`,
      type: "thinking",
      content: thinkingContent,
      status: "done",
      startedAt: 0,
      finishedAt: 0,
    });
  }
  if (toolCalls.length > 0 && message.content.trim()) {
    items.push({
      id: `content-${message.message_id}`,
      type: "content",
      content: message.content,
    });
  }
  toolCalls.forEach((toolCall) => {
    const tool = createPendingToolProcessItem(
      toolCall,
      parseMessageTimestamp(message.created_at),
    );
    items.push({
      id: tool.id,
      type: "tool",
      tool,
    });
  });
  return items;
}

function normalizeConversationToolCalls(
  toolCalls: ConversationMessage["tool_calls"] | undefined,
): ChatToolCallEvent[] {
  if (!Array.isArray(toolCalls)) return [];
  return toolCalls
    .filter((toolCall) => toolCall.name.trim().length > 0)
    .map((toolCall) => ({
      call_id: toolCall.call_id,
      name: toolCall.name,
      arguments: toolCall.arguments,
    }));
}

function mergeToolProcessItem(
  current: ChatToolProcessItem,
  next: ChatToolProcessItem,
): ChatToolProcessItem {
  return {
    ...next,
    startedAt: current.startedAt ?? next.startedAt,
    finishedAt: next.finishedAt ?? current.finishedAt,
  };
}

function matchesToolProcessItem(
  current: ChatToolProcessItem,
  next: ChatToolProcessItem,
) {
  return current.id === next.id ||
    Boolean(next.callId && current.callId === next.callId) ||
    Boolean(!next.callId && !current.callId && current.name === next.name);
}

function parseMessageTimestamp(value: string | null | undefined) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
