import type { ChatStreamEvent, ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import {
  appendAssistantContentProcess,
  appendThinkingProcessDelta,
  appendToolPreparingProcess,
  createFinishedToolProcessItem,
  createRunningToolProcessItem,
  finishOpenThinkingProcess,
  removeToolPreparingProcess,
  upsertPreparingToolProcessDeltaInTimeline,
  upsertToolProcessItem,
  upsertToolProcessItemInTimeline,
  type ChatAssistantProcessItem,
  type ChatMessage,
  type ChatToolProcessItem,
} from "./chatMessage";

export type UpdateSessionMessages = (
  pid: string,
  sessionId: string,
  updater: (messages: ChatMessage[]) => ChatMessage[],
) => void;

type ChatStreamAccumulatorOptions = {
  assistantId: string;
  initialMessage?: ChatMessage | null;
  isSessionPresented: () => boolean;
  isThinkingStuckToBottom: (messageId: string) => boolean;
  onUsage: (usage: ChatUsage) => void;
  scrollThinkingContentToBottom: (messageId: string) => void;
  sessionId: string;
  streamProjectId: string;
  streamingEnabled: boolean;
  updateSessionMessages: UpdateSessionMessages;
};

const STREAM_FLUSH_DELAY_MS = 1;

export function createChatStreamAccumulator({
  assistantId,
  initialMessage = null,
  isSessionPresented,
  isThinkingStuckToBottom,
  onUsage,
  scrollThinkingContentToBottom,
  sessionId,
  streamProjectId,
  streamingEnabled,
  updateSessionMessages,
}: ChatStreamAccumulatorOptions) {
  let contentBuffer = initialMessage?.content ?? "";
  let thinkingBuffer = initialMessage?.thinkingContent ?? "";
  let contentPartsBuffer = [...(initialMessage?.contentParts ?? [])];
  let processItems: ChatAssistantProcessItem[] = [
    ...(initialMessage?.processItems ?? []),
  ];
  let streamRole: ChatMessage["role"] = initialMessage?.role ?? "assistant";
  let streamHadError = false;
  let hasCollapsedThinkingOnBodyStart = Boolean(initialMessage?.content.trim());
  let flushTimer: number | null = null;

  const flushStreamUpdate = () => {
    flushTimer = null;
    const shouldScrollThinking = thinkingBuffer.length > 0 && contentBuffer.trim().length === 0;
    updateSessionMessages(streamProjectId, sessionId, (prev) => prev.map((message) =>
      message.id === assistantId
        ? {
            ...message,
            role: streamRole,
            content: contentBuffer,
            contentParts: contentPartsBuffer,
            thinkingContent: thinkingBuffer,
            status: streamRole === "error" ? "error" : "running",
            processItems,
            toolCalls: streamHadError
              ? (message.toolCalls ?? []).map((tool) =>
                  finalizeActiveTool(tool, Date.now(), "error"))
              : message.toolCalls,
            isThinkingExpanded: hasCollapsedThinkingOnBodyStart ? false : message.isThinkingExpanded,
            thinkingFinishedAt: contentBuffer.trim().length > 0 && message.thinkingFinishedAt === null
              ? Date.now()
              : message.thinkingFinishedAt,
            updatedAt: Date.now(),
          }
        : message,
    ));
    if (
      shouldScrollThinking &&
      isSessionPresented() &&
      isThinkingStuckToBottom(assistantId)
    ) {
      scrollThinkingContentToBottom(assistantId);
    }
  };

  const scheduleStreamFlush = () => {
    if (!streamingEnabled || flushTimer !== null) return;
    // 保持 ThinkFlow 实测的 1ms 打字机节奏，让事件循环自然合并连续 chunk。
    flushTimer = window.setTimeout(flushStreamUpdate, STREAM_FLUSH_DELAY_MS);
  };

  const flushNow = () => {
    if (flushTimer !== null) {
      window.clearTimeout(flushTimer);
    }
    flushStreamUpdate();
  };

  const finalizeCancelled = () => {
    if (flushTimer !== null) {
      window.clearTimeout(flushTimer);
      flushTimer = null;
    }
    const now = Date.now();
    processItems = removeToolPreparingProcess(
      finishOpenThinkingProcess(processItems, now),
    ).map((item) => item.type === "tool"
      ? { ...item, tool: finalizeActiveTool(item.tool, now, "cancelled") }
      : item);
    updateSessionMessages(streamProjectId, sessionId, (prev) => prev.map((message) =>
      message.id === assistantId
        ? {
            ...message,
            content: contentBuffer,
            contentParts: contentPartsBuffer,
            thinkingContent: thinkingBuffer,
            status: "cancelled",
            processItems,
            toolCalls: (message.toolCalls ?? []).map((tool) =>
              finalizeActiveTool(tool, now, "cancelled")),
            isThinkingExpanded: false,
            thinkingFinishedAt:
              message.thinkingStartedAt !== null &&
              message.thinkingFinishedAt === null
                ? now
                : message.thinkingFinishedAt,
            updatedAt: now,
          }
        : message,
    ));
  };

  const moveBufferedContentToProcess = () => {
    if (!contentBuffer.trim()) return;
    processItems = appendAssistantContentProcess(processItems, contentBuffer);
    contentBuffer = "";
  };

  const handleEvent = (event: ChatStreamEvent) => {
    if (event.kind === "delta" && event.content) {
      contentBuffer += event.content;
      if (contentBuffer.trim().length > 0) {
        processItems = finishOpenThinkingProcess(processItems, Date.now());
        hasCollapsedThinkingOnBodyStart = true;
      }
      scheduleStreamFlush();
    }

    if (event.kind === "thinking_delta" && event.content) {
      thinkingBuffer += event.content;
      processItems = appendThinkingProcessDelta(
        processItems,
        event.content,
        Date.now(),
      );
      scheduleStreamFlush();
    }

    if (event.kind === "usage") {
      updateSessionMessages(streamProjectId, sessionId, (prev) => prev.map((message) =>
        message.id === assistantId
          ? {
              ...message,
              usage: event.usage,
              contextTokens: event.context_tokens ?? message.contextTokens ?? null,
              contextTokensEstimated:
                event.context_tokens_estimated
                ?? message.contextTokensEstimated
                ?? false,
            }
          : message,
      ));
      onUsage(event.usage);
    }

    if (event.kind === "tool_call_delta") {
      const now = Date.now();
      moveBufferedContentToProcess();
      if (event.tool_call) {
        processItems = upsertPreparingToolProcessDeltaInTimeline(
          removeToolPreparingProcess(finishOpenThinkingProcess(processItems, now)),
          event.tool_call,
          now,
        );
      } else {
        processItems = appendToolPreparingProcess(processItems, now);
      }
      updateSessionMessages(streamProjectId, sessionId, (prev) =>
        updateAssistantProcessItems(prev, assistantId, processItems, contentBuffer),
      );
    }

    if (event.kind === "tool_call" && event.tool_call) {
      const now = Date.now();
      moveBufferedContentToProcess();
      const toolItem = createRunningToolProcessItem(event.tool_call, now);
      processItems = upsertToolProcessItemInTimeline(
        removeToolPreparingProcess(finishOpenThinkingProcess(processItems, now)),
        toolItem,
      );
      updateSessionMessages(streamProjectId, sessionId, (prev) =>
        upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
      );
    }

    if (event.kind === "tool_result" && event.tool_result) {
      const toolItem = createFinishedToolProcessItem(event.tool_result, Date.now());
      processItems = upsertToolProcessItemInTimeline(processItems, toolItem);
      updateSessionMessages(streamProjectId, sessionId, (prev) =>
        upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
      );
    }

    if (event.kind === "error") {
      const now = Date.now();
      streamHadError = true;
      streamRole = "error";
      processItems = removeToolPreparingProcess(
        finishOpenThinkingProcess(processItems, now),
      ).map((item) => item.type === "tool"
        ? { ...item, tool: finalizeActiveTool(item.tool, now, "error") }
        : item);
      contentBuffer = event.error || "请求失败";
      flushNow();
    }
  };

  return {
    clearFlushTimer: () => {
      if (flushTimer !== null) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
    },
    finalizeCancelled,
    flushNow,
    hadError: () => streamHadError,
    handleEvent,
  };
}


function finalizeActiveTool(
  tool: ChatToolProcessItem,
  finishedAt: number,
  status: Extract<ChatToolProcessItem["status"], "cancelled" | "error">,
): ChatToolProcessItem {
  if (tool.status !== "preparing" && tool.status !== "running") return tool;
  return {
    ...tool,
    finishedAt,
    status,
  };
}

function upsertAssistantToolProcessItem(
  messages: ChatMessage[],
  assistantId: string,
  toolItem: ChatToolProcessItem,
  processItems: ChatAssistantProcessItem[],
  content: string,
) {
  return messages.map((message) =>
    message.id === assistantId
      ? {
          ...message,
          content,
          processItems,
          toolCalls: upsertToolProcessItem(message.toolCalls ?? [], toolItem),
        }
      : message,
  );
}

function updateAssistantProcessItems(
  messages: ChatMessage[],
  assistantId: string,
  processItems: ChatAssistantProcessItem[],
  content: string,
) {
  return messages.map((message) =>
    message.id === assistantId
      ? {
          ...message,
          content,
          processItems,
        }
      : message,
  );
}
