import { releasePendingChatNotifications, mergeLiveChatNotifications } from "./chatNotifications";
import { createUuid } from "../../../shared/model/createUuid";
import type { ChatStreamEvent, ChatUsage } from "../../../entities/llm-chat/model/chatCompletion";
import {
  isChatNotificationMessage,
  appendAssistantContentProcess,
  mapConversationMessages,
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
  let modelResponseInFlight = initialMessage?.modelResponseInFlight ?? false;
  let runUserMessageId = "";
  let runId = "";
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
            modelResponseInFlight,
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
    modelResponseInFlight = false;
    updateSessionMessages(streamProjectId, sessionId, releasePendingChatNotifications);
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
            modelResponseInFlight: false,
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
        run_id: runId || assistantId,
        session_id: sessionId,
        user_message_id: runUserMessageId,
        error_code: errorCode,
        error_message: error,
        attempt_index: normalizedAttemptIndex,
        attempt_count: Math.max(normalizedAttemptIndex, attemptCount),
        occurred_at: new Date(now).toISOString(),
      },
      retryStatus: null,
    };
  };

  const adoptTrailingNotifications = () => {
    updateSessionMessages(streamProjectId, sessionId, (messages) => {
      const index = messages.findIndex((message) => message.id === assistantId);
      if (index < 0) return messages;
      let end = index + 1;
      while (end < messages.length && isChatNotificationMessage(messages[end]) && !messages[end].notificationPending) end += 1;
      const notices = messages.slice(index + 1, end);
      if (!notices.length) return messages;
      moveBufferedContentToProcess();
      const items = notices.map((message) => ({ id: message.id, type: "notification" as const, message }));
      processItems = [...processItems, ...items];
      // Notices are durable facts even when the next attempt rolls text back.
      const committedIds = new Set(committedProcessItems.map((item) => item.id));
      committedProcessItems = [...committedProcessItems, ...items.filter((item) => !committedIds.has(item.id))];
      const next = [...messages.slice(0, index + 1), ...messages.slice(end)];
      return updateAssistantProcessItems(next, assistantId, processItems, contentBuffer);
    });
  };

  const finishModelResponse = (notifications = [] as ChatMessage[], hasTools = false) => {
    flushNow();
    modelResponseInFlight = false;
    processItems = finishOpenThinkingProcess(processItems, Date.now());
    updateSessionMessages(streamProjectId, sessionId, (messages) => {
      const next = releasePendingChatNotifications(mergeLiveChatNotifications(messages, notifications));
      return next.map((message) => message.id === assistantId
        ? { ...message, modelResponseInFlight: false, processItems } : message);
    });
    if (hasTools) adoptTrailingNotifications();
  };

  const finalizeCompleted = () => {
    finishModelResponse();
    updateSessionMessages(streamProjectId, sessionId, (messages) => messages.map((message) =>
      message.id === assistantId ? { ...message, status: streamHadError ? "error" : "done", modelResponseInFlight: false } : message));
  };

  let replayingEarlierAutomaticTurn = false;
  const handleEvent = (event: ChatStreamEvent) => {
    if (event.kind === "conversation_run_started") {
      runUserMessageId = event.user_message_id;
      runId = event.run_id || `run_${runUserMessageId}`;
      updateSessionMessages(streamProjectId, sessionId, (messages) => {
        const lastUser = [...messages].reverse().find((message) => message.role === "user");
        replayingEarlierAutomaticTurn = lastUser?.messageSource === "output_limit"
          && lastUser.id !== event.user_message_id;
        return messages;
      });
      return;
    }
    if (replayingEarlierAutomaticTurn) return;
    if (event.kind === "conversation_notice") {
      const notices = mapConversationMessages([event.message]);
      updateSessionMessages(streamProjectId, sessionId, (messages) => mergeLiveChatNotifications(messages, notices));
      return;
    }
    if (event.kind === "model_response_started") {
      adoptTrailingNotifications();
      modelResponseInFlight = true;
      flushNow();
      return;
    }
    if (event.kind === "model_response_finished") {
      finishModelResponse(mapConversationMessages(event.notifications ?? []), Boolean(event.has_tool_calls));
      return;
    }
    if (event.kind === "done") { finishModelResponse(); return; }

    if (event.kind === "output_limit") {
      finishModelResponse();
      if (event.usage) onUsage(event.usage);
      if (flushTimer !== null) { window.clearTimeout(flushTimer); flushTimer = null; }
      const previousAssistantId = assistantId;
      const nextAssistantId = event.will_recover ? createUuid() : assistantId;
      const saved = event.saved_message ? mapConversationMessages([event.saved_message])[0] : null;
      const nextUser = event.next_user_message ? mapConversationMessages([event.next_user_message])[0] : null;
      const hasCommitted = Boolean(committedContentBuffer.trim() || committedThinkingBuffer.trim()
        || committedProcessItems.length || committedToolCallIds.size);
      updateSessionMessages(streamProjectId, sessionId, (messages) => {
        const previous = messages.find((message) => message.id === previousAssistantId);
        const alreadyPersisted = saved && messages.some((message) => message.id === saved.id);
        const result = messages.flatMap((message) => {
          if (message.id !== previousAssistantId) return [message];
          const retained = hasCommitted && !alreadyPersisted ? [{ ...message, content: committedContentBuffer,
            thinkingContent: committedThinkingBuffer, processItems: committedProcessItems,
            toolCalls: (message.toolCalls ?? []).filter((tool) => committedToolCallIds.has(tool.callId)),
            status: "done", retryStatus: null }] : [];
          // Replace the streamed fragment at its own position. A queued notice
          // belongs after that fragment, before any automatic continuation.
          return saved && !alreadyPersisted ? [...retained, saved] : retained;
        });
        if (saved && !result.some((message) => message.id === saved.id)) result.push(saved);
        if (nextUser && !result.some((message) => message.id === nextUser.id)) result.push(nextUser);
        result.push({
          id: nextAssistantId, role: "assistant", content: "", thinkingContent: "", status: "running", usage: null,
          providerId: previous?.providerId, modelId: previous?.modelId,
          isThinkingExpanded: true, thinkingStartedAt: Date.now(), thinkingFinishedAt: null, createdAt: Date.now(),
        });
        return result;
      });
      assistantId = nextAssistantId;
      contentBuffer = ""; thinkingBuffer = ""; contentPartsBuffer = []; processItems = [];
      committedContentBuffer = ""; committedThinkingBuffer = ""; committedContentPartsBuffer = []; committedProcessItems = [];
      committedToolCallIds = new Set(); committedHasCollapsedThinking = false;
      hasCollapsedThinkingOnBodyStart = false; retryStatus = null;
      currentAttemptIndex = 1; currentAttemptCount = 1;
      streamRole = "assistant"; streamHadError = false;
      return;
    }
    if (event.kind === "retry_reset") {
      modelResponseInFlight = false;
      updateSessionMessages(streamProjectId, sessionId, releasePendingChatNotifications);
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
      adoptTrailingNotifications();
      retryStatus = {
        error: event.error || "",
        errorCode: event.error_code?.trim() || null,
        attemptIndex,
        attemptCount: currentAttemptCount,
      };
      const hasCommittedProcess = processItems.length > 0
        || Boolean(contentBuffer.trim() || thinkingBuffer.trim());
      if (hasCommittedProcess) {
        moveBufferedContentToProcess();
        processItems = [...processItems, {
          id: attemptFailureMessage.id,
          type: "attempt_failure",
          message: attemptFailureMessage,
        }];
        // Display-only notices retain their positions on another retry.
        committedContentBuffer = contentBuffer;
        committedProcessItems = [...processItems];
      }
      updateSessionMessages(streamProjectId, sessionId, (prev) => prev.flatMap((message) =>
        message.id === assistantId
          ? [...(hasCommittedProcess ? [] : [attemptFailureMessage]), {
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
      modelResponseInFlight = false;
      updateSessionMessages(streamProjectId, sessionId, releasePendingChatNotifications);
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
    finalizeCompleted,
    flushNow,
    hadError: () => streamHadError,
    getAssistantId: () => assistantId,
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
