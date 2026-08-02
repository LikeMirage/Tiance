import { useEffect, useRef } from "react";

import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { resumeChatCompletionStream } from "../../../services/llm/resumeChatCompletionStream";
import { HttpRequestError } from "../../../services/http/httpClient";
import type { ClientToolExecutor } from "../../client-tools/model/clientToolBridge";
import { createChatStreamAccumulator, type UpdateSessionMessages } from "./chatStreamAccumulator";
import type { ChatMessage } from "./chatMessage";
import {
  prepareConversationStreamFullReplay,
  prepareConversationStreamResume,
} from "./conversationStreamResume";
import { processChatStreamEventSideEffects } from "./chatStreamEventSideEffects";
import {
  clearChatStreamEventSequence,
  processSequencedChatStreamEvent,
  type ChatStreamEventSequenceState,
} from "./chatStreamEventSequence";

type UseDetachedConversationStreamOptions = {
  activeSessionId: string | null;
  activeSessionKey: string | null;
  clientToolExecutor?: ClientToolExecutor | null;
  isActive: boolean;
  isSessionMessagesPresented: (projectId: string, sessionId: string) => boolean;
  isThinkingStuckToBottom: (messageId: string) => boolean;
  markSessionStreaming: (sessionKey: string) => void;
  projectId: string | null;
  reloadSessionMessages: (
    projectId: string,
    sessionId: string,
    options?: {
      forceRefresh?: boolean;
      preserveLocalIfShorter?: boolean;
      signal?: AbortSignal;
    },
  ) => Promise<boolean>;
  reloadSessionUsageSummary: (
    projectId: string,
    sessionId: string,
    options?: { forceRefresh?: boolean },
  ) => Promise<void>;
  reloadSessions: (projectId: string) => Promise<void>;
  runtimeStatus: string | null;
  scrollThinkingContentToBottom: (messageId: string) => void;
  streamEventSequenceState: ChatStreamEventSequenceState;
  streamingEnabled: boolean;
  streamingSessionKeys: Set<string>;
  setSessionRuntimeStatus: (
    projectId: string,
    sessionId: string,
    runtimeStatus: ConversationRuntimeStatus,
  ) => void;
  unmarkSessionStreaming: (sessionKey: string) => void;
  updateSessionMessages: UpdateSessionMessages;
};

export function useDetachedConversationStream({
  activeSessionId,
  activeSessionKey,
  clientToolExecutor,
  isActive,
  isSessionMessagesPresented,
  isThinkingStuckToBottom,
  markSessionStreaming,
  projectId,
  reloadSessionMessages,
  reloadSessionUsageSummary,
  reloadSessions,
  runtimeStatus,
  scrollThinkingContentToBottom,
  streamEventSequenceState,
  streamingEnabled,
  streamingSessionKeys,
  setSessionRuntimeStatus,
  unmarkSessionStreaming,
  updateSessionMessages,
}: UseDetachedConversationStreamOptions) {
  const streamingSessionKeysRef = useRef(streamingSessionKeys);
  const reconnectControllersRef = useRef(new Map<string, AbortController>());
  streamingSessionKeysRef.current = streamingSessionKeys;

  useEffect(() => () => {
    for (const controller of reconnectControllersRef.current.values()) {
      controller.abort();
    }
    reconnectControllersRef.current.clear();
  }, []);

  useEffect(() => {
    if (!isActive || runtimeStatus !== "running") return undefined;
    if (!projectId || !activeSessionId || !activeSessionKey) return undefined;
    if (streamingSessionKeysRef.current.has(activeSessionKey)) return undefined;
    if (reconnectControllersRef.current.has(activeSessionKey)) return undefined;

    const controller = new AbortController();
    reconnectControllersRef.current.set(activeSessionKey, controller);
    let assistantId: string | null = null;
    let initialAssistantMessage: ChatMessage | null = null;
    let checkpointMessageId: string | null = null;
    let accumulator: ReturnType<typeof createChatStreamAccumulator> | null = null;
    let shouldRefreshPersistedUsageOnNextToolCall = false;
    let shouldClearEventSequence = false;
    let terminalRuntimeStatus: ConversationRuntimeStatus | null = null;
    markSessionStreaming(activeSessionKey);

    const createAccumulatorForMessage = (
      id: string,
      initialMessage: ChatMessage | null,
    ) => createChatStreamAccumulator({
      assistantId: id,
      initialMessage,
      isSessionPresented: () => isSessionMessagesPresented(projectId, activeSessionId),
      isThinkingStuckToBottom,
      onUsage: (usage) => {
        shouldRefreshPersistedUsageOnNextToolCall = true;
        dispatchProjectConversationUpdated({
          kind: "usage",
          projectId,
          sessionId: activeSessionId,
          usage,
        });
        emitLlmUsageChanged();
      },
      scrollThinkingContentToBottom,
      sessionId: activeSessionId,
      streamProjectId: projectId,
      streamingEnabled,
      updateSessionMessages,
    });

    const reconnect = async () => {
      const [didReloadMessages] = await Promise.all([
        reloadSessionMessages(projectId, activeSessionId, {
          forceRefresh: true,
          signal: controller.signal,
        }).catch(() => false),
        reloadSessionUsageSummary(projectId, activeSessionId, {
          forceRefresh: true,
        }).catch(() => undefined),
      ]);
      if (controller.signal.aborted) return;
      dispatchProjectConversationUpdated({
        kind: "content",
        projectId,
        sessionId: activeSessionId,
      });

      updateSessionMessages(projectId, activeSessionId, (messages) => {
        const now = Date.now();
        const resumeSnapshot = prepareConversationStreamResume(
          messages,
          crypto.randomUUID(),
          now,
        );
        assistantId = resumeSnapshot.assistantMessage.id;
        initialAssistantMessage = resumeSnapshot.assistantMessage;
        checkpointMessageId = didReloadMessages
          ? resumeSnapshot.checkpointMessageId
          : null;
        return resumeSnapshot.messages;
      });
      if (!assistantId || controller.signal.aborted) return;

      accumulator = createAccumulatorForMessage(
        assistantId,
        initialAssistantMessage,
      );

      await resumeChatCompletionStream(
        projectId,
        activeSessionId,
        async (event) => {
          if (event.kind === "conversation_resume_reset") {
            accumulator?.clearFlushTimer();
            clearChatStreamEventSequence(activeSessionKey, streamEventSequenceState);
            await reloadSessionMessages(projectId, activeSessionId, {
              forceRefresh: true,
              preserveLocalIfShorter: true,
              signal: controller.signal,
            }).catch(() => false);
            if (controller.signal.aborted) return;
            updateSessionMessages(projectId, activeSessionId, (messages) => {
              const resetSnapshot = prepareConversationStreamFullReplay(
                messages,
                crypto.randomUUID(),
                Date.now(),
              );
              assistantId = resetSnapshot.assistantMessage.id;
              initialAssistantMessage = resetSnapshot.assistantMessage;
              return resetSnapshot.messages;
            });
            if (!assistantId || !initialAssistantMessage) return;
            accumulator = createAccumulatorForMessage(
              assistantId,
              initialAssistantMessage,
            );
            return;
          }
          await processSequencedChatStreamEvent(
            activeSessionKey,
            event,
            streamEventSequenceState,
            async () => {
              if (
                event.kind === "conversation_run_settled" &&
                event.status === "cancelled"
              ) {
                accumulator?.finalizeCancelled();
                return;
              }
              const shouldRender = await processChatStreamEventSideEffects(
                event,
                clientToolExecutor,
              );
              if (shouldRender) {
                accumulator?.handleEvent(event);
              }
              if (
                event.kind === "tool_call"
                && shouldRefreshPersistedUsageOnNextToolCall
              ) {
                shouldRefreshPersistedUsageOnNextToolCall = false;
                void reloadSessionUsageSummary(projectId, activeSessionId, {
                  forceRefresh: true,
                }).catch(() => undefined);
              }
            },
          );
        },
        controller.signal,
        checkpointMessageId,
      );
      shouldClearEventSequence = true;
      accumulator.flushNow();
      terminalRuntimeStatus = accumulator.hadError() ? "error" : "idle";
    };

    void reconnect()
      .catch((error) => {
        if (error instanceof HttpRequestError) {
          shouldClearEventSequence = true;
          if (error.status === 404) {
            terminalRuntimeStatus = "idle";
          }
        }
      })
      .finally(() => {
        accumulator?.clearFlushTimer();
        if (!controller.signal.aborted) {
          dispatchProjectConversationUpdated({
            kind: "content",
            projectId,
            sessionId: activeSessionId,
          });
        }
        if (reconnectControllersRef.current.get(activeSessionKey) === controller) {
          reconnectControllersRef.current.delete(activeSessionKey);
        }
        if (shouldClearEventSequence) {
          clearChatStreamEventSequence(activeSessionKey, streamEventSequenceState);
        }
        if (terminalRuntimeStatus) {
          setSessionRuntimeStatus(
            projectId,
            activeSessionId,
            terminalRuntimeStatus,
          );
        }
        unmarkSessionStreaming(activeSessionKey);
        if (!controller.signal.aborted) {
          void reloadSessionMessages(projectId, activeSessionId, {
            forceRefresh: true,
            preserveLocalIfShorter: terminalRuntimeStatus === null,
          }).catch(() => undefined);
          void reloadSessionUsageSummary(projectId, activeSessionId, {
            forceRefresh: true,
          }).catch(() => undefined);
          void reloadSessions(projectId).catch(() => undefined);
        }
      });
    return undefined;
  }, [
    activeSessionId,
    activeSessionKey,
    clientToolExecutor,
    isActive,
    isSessionMessagesPresented,
    isThinkingStuckToBottom,
    markSessionStreaming,
    projectId,
    reloadSessionMessages,
    reloadSessionUsageSummary,
    reloadSessions,
    runtimeStatus,
    scrollThinkingContentToBottom,
    setSessionRuntimeStatus,
    streamEventSequenceState,
    streamingEnabled,
    updateSessionMessages,
    unmarkSessionStreaming,
  ]);
}
