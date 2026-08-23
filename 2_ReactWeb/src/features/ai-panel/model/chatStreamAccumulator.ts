import type { ChatStreamEvent, ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import {
  appendAssistantContentProcess,
  appendThinkingProcessDelta,
  appendToolPreparingProcess,
  createFinishedToolProcessItem,
  createRunningToolProcessItem,
  createWaitingPermissionToolProcessItem,
  finishOpenThinkingProcess,
  removeToolPreparingProcess,
  resolveWaitingPermissionToolProcessItem,
  upsertPreparingToolProcessDeltaInTimeline,
  upsertToolProcessItem,
  upsertToolProcessItemInTimeline,
  type ChatAssistantProcessItem,
  type ChatMessage,
  type ChatRetryStatus,
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
  let retryStatus: ChatRetryStatus | null = initialMessage?.retryStatus ?? null;
  let currentAttemptIndex = Math.max(1, retryStatus?.attemptIndex ?? 1);
  let currentAttemptCount = Math.max(currentAttemptIndex, retryStatus?.attemptCount ?? 1);
  let attemptFailureSerial = 0;
  let hasCollapsedThinkingOnBodyStart = Boolean(initialMessage?.content.trim());
  let committedContentBuffer = contentBuffer;
  let committedThinkingBuffer = thinkingBuffer;
  let committedContentPartsBuffer = [...contentPartsBuffer];
  let committedProcessItems = [...processItems];
  let committedToolCallIds = new Set(
    (initialMessage?.toolCalls ?? [])
      .filter((tool) => tool.status === "done" || tool.status === "error")
      .map((tool) => tool.callId),
  );
  let committedHasCollapsedThinking = hasCollapsedThinkingOnBodyStart;
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
            retryStatus,
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
      flushTimer = null;
    }
    if (streamHadError) return;
    flushStreamUpdate();
  };

  const finalizeCancelled = () => {
    if (flushTimer !== null) {
      window.clearTimeout(flushTimer);
      flushTimer = null;
    }
    const now = Date.now();
    retryStatus = null;
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
            retryStatus: null,
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

  const markRetryAttemptProgress = () => {
    if (retryStatus === null) return;
    retryStatus = null;
    updateSessionMessages(streamProjectId, sessionId, (prev) => prev.map((message) =>
      message.id === assistantId
        ? { ...message, retryStatus: null, updatedAt: Date.now() }
        : message,
    ));
  };

  const createAttemptFailureMessage = (
    error: string,
    errorCode: string | null,
    attemptIndex: number,
    attemptCount: number,
  ): ChatMessage => {
    const now = Date.now();
    const normalizedAttemptIndex = Math.max(1, attemptIndex);
    attemptFailureSerial += 1;
    return {
      id: `run-attempt-failure:live:${assistantId}:${attemptFailureSerial}`,
      role: "error",
      content: error,
      thinkingContent: "",
      status: "error",
      usage: null,
      isThinkingExpanded: false,
      thinkingStartedAt: null,
      thinkingFinishedAt: null,
      createdAt: now,
      updatedAt: now,
      originMessageId: `run-attempt-failure:live:${assistantId}:${attemptFailureSerial}`,
      runAttemptFailure: {
        event_id: -attemptFailureSerial,
        run_id: assistantId,
        session_id: sessionId,
        user_message_id: "",
        error_code: errorCode,
        error_message: error,
        attempt_index: normalizedAttemptIndex,
        attempt_count: Math.max(normalizedAttemptIndex, attemptCount),
        occurred_at: new Date(now).toISOString(),
      },
      retryStatus: null,
    };
  };

  const handleEvent = (event: ChatStreamEvent) => {
    if (event.kind === "retry_reset") {
      if (flushTimer !== null) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      contentBuffer = committedContentBuffer;
      thinkingBuffer = committedThinkingBuffer;
      contentPartsBuffer = [...committedContentPartsBuffer];
      processItems = [...committedProcessItems];
      hasCollapsedThinkingOnBodyStart = committedHasCollapsedThinking;
      streamRole = "assistant";
      streamHadError = false;
      const attemptIndex = Math.max(1, event.attempt_index ?? 1);
      const failedAttemptIndex = Math.max(1, attemptIndex - 1);
      currentAttemptIndex = attemptIndex;
      currentAttemptCount = Math.max(attemptIndex, event.attempt_count ?? attemptIndex);
      const attemptFailureMessage = createAttemptFailureMessage(
        event.error || "",
        event.error_code?.trim() || null,
        failedAttemptIndex,
        currentAttemptCount,
      );
      retryStatus = {
        error: event.error || "",
        errorCode: event.error_code?.trim() || null,
        attemptIndex,
        attemptCount: currentAttemptCount,
      };
      updateSessionMessages(streamProjectId, sessionId, (prev) => prev.flatMap((message) =>
        message.id === assistantId
          ? [attemptFailureMessage, {
              ...message,
              role: "assistant",
              content: contentBuffer,
              contentParts: contentPartsBuffer,
              thinkingContent: thinkingBuffer,
              status: "running",
              retryStatus,
              processItems,
              toolCalls: (message.toolCalls ?? []).filter((tool) =>
                committedToolCallIds.has(tool.callId)),
              updatedAt: Date.now(),
            }]
          : [message],
      ));
      return;
    }

    if (event.kind === "delta" && event.content) {
      markRetryAttemptProgress();
      contentBuffer += event.content;
      if (contentBuffer.trim().length > 0) {
        processItems = finishOpenThinkingProcess(processItems, Date.now());
        hasCollapsedThinkingOnBodyStart = true;
      }
      scheduleStreamFlush();
    }

    if (event.kind === "thinking_delta" && event.content) {
      markRetryAttemptProgress();
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
      markRetryAttemptProgress();
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
      markRetryAttemptProgress();
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

    if (event.kind === "tool_permission_request" && event.tool_permission_request) {
      const request = event.tool_permission_request;
      const current = processItems.find(
        (item): item is Extract<ChatAssistantProcessItem, { type: "tool" }> =>
          item.type === "tool" && item.tool.callId === request.call_id,
      )?.tool ?? null;
      const toolItem = createWaitingPermissionToolProcessItem(request, current);
      processItems = upsertToolProcessItemInTimeline(processItems, toolItem);
      updateSessionMessages(streamProjectId, sessionId, (prev) =>
        upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
      );
    }

    if (event.kind === "tool_permission_resolved" && event.tool_permission_resolution) {
      const resolution = event.tool_permission_resolution;
      const current = processItems.find(
        (item): item is Extract<ChatAssistantProcessItem, { type: "tool" }> =>
          item.type === "tool"
          && item.tool.permissionRequest?.request_id === resolution.request_id,
      )?.tool;
      if (current) {
        const toolItem = resolveWaitingPermissionToolProcessItem(
          current,
          resolution.request_id,
        );
        processItems = upsertToolProcessItemInTimeline(processItems, toolItem);
        updateSessionMessages(streamProjectId, sessionId, (prev) =>
          upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
        );
      }
    }

    if (event.kind === "tool_permission_request_cancelled") {
      const current = processItems.find(
        (item): item is Extract<ChatAssistantProcessItem, { type: "tool" }> =>
          item.type === "tool"
          && item.tool.permissionRequest?.request_id === event.request_id,
      )?.tool;
      if (current) {
        const toolItem: ChatToolProcessItem = {
          ...current,
          status: "cancelled",
          finishedAt: Date.now(),
          permissionRequest: null,
        };
        processItems = upsertToolProcessItemInTimeline(processItems, toolItem);
        updateSessionMessages(streamProjectId, sessionId, (prev) =>
          upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
        );
      }
    }

    if (event.kind === "tool_result" && event.tool_result) {
      const toolItem = createFinishedToolProcessItem(event.tool_result, Date.now());
      processItems = upsertToolProcessItemInTimeline(processItems, toolItem);
      committedContentBuffer = contentBuffer;
      committedThinkingBuffer = thinkingBuffer;
      committedContentPartsBuffer = [...contentPartsBuffer];
      committedProcessItems = [...processItems];
      committedToolCallIds = new Set([...committedToolCallIds, toolItem.callId]);
      committedHasCollapsedThinking = hasCollapsedThinkingOnBodyStart;
      updateSessionMessages(streamProjectId, sessionId, (prev) =>
        upsertAssistantToolProcessItem(prev, assistantId, toolItem, processItems, contentBuffer),
      );
    }

    if (event.kind === "error") {
      if (flushTimer !== null) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      const now = Date.now();
      streamHadError = true;
      streamRole = "assistant";
      retryStatus = null;
      currentAttemptIndex = Math.max(1, event.attempt_index ?? currentAttemptIndex);
      currentAttemptCount = Math.max(
        currentAttemptIndex,
        event.attempt_count ?? currentAttemptCount,
      );
      contentBuffer = committedContentBuffer;
      thinkingBuffer = committedThinkingBuffer;
      contentPartsBuffer = [...committedContentPartsBuffer];
      processItems = [...committedProcessItems];
      hasCollapsedThinkingOnBodyStart = committedHasCollapsedThinking;
      const attemptFailureMessage = createAttemptFailureMessage(
        event.error || "",
        event.error_code?.trim() || null,
        currentAttemptIndex,
        currentAttemptCount,
      );
      const hasCommittedAssistantProcess = Boolean(
        contentBuffer.trim()
        || thinkingBuffer.trim()
        || processItems.length > 0
        || committedToolCallIds.size > 0,
      );
      updateSessionMessages(streamProjectId, sessionId, (prev) => prev.flatMap((message) => {
        if (message.id !== assistantId) return [message];
        if (!hasCommittedAssistantProcess) return [attemptFailureMessage];
        return [{
          ...message,
          role: "assistant",
          content: contentBuffer,
          contentParts: contentPartsBuffer,
          thinkingContent: thinkingBuffer,
          status: "done",
          retryStatus: null,
          processItems,
          toolCalls: (message.toolCalls ?? []).filter((tool) =>
            committedToolCallIds.has(tool.callId)),
          isThinkingExpanded: false,
          thinkingFinishedAt: message.thinkingStartedAt !== null ? now : null,
          updatedAt: now,
        }, attemptFailureMessage];
      }));
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
