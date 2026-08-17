import { useCallback, useRef } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import type {
  ConversationRuntimeStatus,
  ConversationSession,
  ConversationSessionState,
} from "../../../entities/llm-chat/model/conversation";
import type {
  ChatClientCapability,
  ChatCompletionMessageInput,
  ConversationMessageReferences,
} from "../../../entities/llm-chat/model/chatCompletion";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { createProjectConversation } from "../../../services/project/createProjectConversation";
import { streamChatCompletion } from "../../../services/llm/streamChatCompletion";
import { isConversationStreamResyncRequired } from "../../../services/llm/conversationStreamErrors";
import { HttpRequestError } from "../../../services/http/httpClient";
import { isAbortError } from "../../../services/http/httpErrors";
import type { ClientToolExecutor } from "../../client-tools/model/clientToolBridge";
import type { ChatModelOption } from "./chatModelOption";
import {
  type ChatMessage,
} from "./chatMessage";
import { buildSessionKey } from "./sessionKey";
import { buildConversationRunRequest } from "../../conversation-runtime/model/conversationRunRequest";
import {
  buildConversationImageContentParts,
  hasConversationReferences,
} from "./conversationReferences";
import {
  emptyConversationDraftReferences,
  toConversationDraftReferences,
} from "./conversationDraftReferences";
import { createChatStreamAccumulator } from "./chatStreamAccumulator";
import { processChatStreamEventSideEffects } from "../../conversation-runtime/model/chatStreamEventSideEffects";
import {
  clearChatStreamEventSequence,
  processSequencedChatStreamEvent,
  type ChatStreamEventSequenceState,
} from "./chatStreamEventSequence";

type SaveSessionState = (
  pid: string,
  sessionId: string,
  patch: Partial<Pick<
    ConversationSessionState,
    "draft" | "references"
  >>,
) => void;

type UpdateSessionMessages = (
  pid: string,
  sessionId: string,
  updater: (messages: ChatMessage[]) => ChatMessage[],
) => void;

type ReloadSessionMessages = (
  pid: string,
  sessionId: string,
  options?: { forceRefresh?: boolean; preserveLocalIfShorter?: boolean },
) => Promise<boolean>;

type SetSessionRuntimeStatus = (
  pid: string,
  sessionId: string,
  runtimeStatus: ConversationRuntimeStatus,
) => void;

type ReloadSessionUsageSummary = (
  pid: string,
  sessionId: string,
  options?: { forceRefresh?: boolean },
) => Promise<void>;

type UseChatGenerationOptions = {
  activeModel: ChatModelOption | null;
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionId: string | null;
  activeSessionIdRef: MutableRefObject<string | null>;
  canStartConversation: boolean;
  clientToolExecutor?: ClientToolExecutor | null;
  clientToolCapabilities: readonly ChatClientCapability[];
  clearReferences: () => void;
  createSessionStreamController: (sessionKey: string) => AbortController;
  draft: string;
  references: ConversationMessageReferences;
  isActiveSessionBusy: boolean;
  isSessionMessagesPresented: (pid: string, sessionId: string) => boolean;
  isNotFoundRequestError: (error: unknown) => boolean;
  isThinkingStuckToBottom: (messageId: string) => boolean;
  markSessionStreaming: (sessionKey: string) => void;
  markConversationProjectUnavailable: (pid: string) => void;
  models: ChatModelOption[];
  projectId: string | null;
  releaseSessionStreamController: (sessionKey: string, controller: AbortController) => void;
  reloadSessionMessages: ReloadSessionMessages;
  reloadSessionUsageSummary: ReloadSessionUsageSummary;
  reloadSessions: (pid: string) => Promise<void>;
  saveSessionState: SaveSessionState;
  preserveCurrentView: () => void;
  publishCurrentDraftSnapshot: (pid: string, sessionId: string) => void;
  scrollThinkingContentToBottom: (messageId: string) => void;
  sessions: ConversationSession[];
  setActiveSessionId: Dispatch<SetStateAction<string | null>>;
  setDraft: Dispatch<SetStateAction<string>>;
  setSessionStates: Dispatch<SetStateAction<Record<string, ConversationSessionState>>>;
  setSessionRuntimeStatus: SetSessionRuntimeStatus;
  setSessions: Dispatch<SetStateAction<ConversationSession[]>>;
  streamEventSequenceState: ChatStreamEventSequenceState;
  showChatView: () => void;
  supportsImageInput: boolean;
  unmarkSessionStreaming: (sessionKey: string) => void;
  updateSessionMessages: UpdateSessionMessages;
  unavailableProjectIdRef: MutableRefObject<string | null>;
};

export function useChatGeneration({
  activeModel,
  activeProjectIdRef,
  activeSessionId,
  activeSessionIdRef,
  canStartConversation,
  clientToolExecutor,
  clientToolCapabilities,
  clearReferences,
  createSessionStreamController,
  draft,
  references,
  isActiveSessionBusy,
  isSessionMessagesPresented,
  isNotFoundRequestError,
  isThinkingStuckToBottom,
  markSessionStreaming,
  markConversationProjectUnavailable,
  models,
  projectId,
  releaseSessionStreamController,
  reloadSessionMessages,
  reloadSessionUsageSummary,
  reloadSessions,
  saveSessionState,
  preserveCurrentView,
  publishCurrentDraftSnapshot,
  scrollThinkingContentToBottom,
  sessions,
  setActiveSessionId,
  setDraft,
  setSessionStates,
  setSessionRuntimeStatus,
  setSessions,
  streamEventSequenceState,
  showChatView,
  supportsImageInput,
  unmarkSessionStreaming,
  updateSessionMessages,
  unavailableProjectIdRef,
}: UseChatGenerationOptions) {
  const sendStartupLockedRef = useRef(false);
  const sendingSessionKeysRef = useRef<Set<string>>(new Set());

  const ensureSession = useCallback(async (pid: string) => {
    if (unavailableProjectIdRef.current === pid) return null;
    const currentSession = sessions.find(
      (session) => session.session_id === activeSessionId,
    );
    if (currentSession) {
      return currentSession;
    }
    let session: ConversationSession;
    try {
      session = await createProjectConversation(pid);
      dispatchProjectConversationUpdated({
        kind: "structure",
        projectId: pid,
        sessionId: session.session_id,
      });
    } catch (err) {
      if (isNotFoundRequestError(err)) {
        markConversationProjectUnavailable(pid);
        return null;
      }
      throw err;
    }
    if (activeProjectIdRef.current === pid) {
      setSessions((prev) => [session, ...prev]);
      setSessionStates((prev) => ({
        ...prev,
        [session.session_id]: prev[session.session_id] ?? {
          runtime_status: "idle",
          draft: "",
          references: emptyConversationDraftReferences(),
          updated_at: new Date().toISOString(),
        },
      }));
      setActiveSessionId(session.session_id);
      activeSessionIdRef.current = session.session_id;
      setDraft("");
    }
    return session;
  }, [
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    isNotFoundRequestError,
    markConversationProjectUnavailable,
    sessions,
    setActiveSessionId,
    setDraft,
    setSessionStates,
    setSessions,
    unavailableProjectIdRef,
  ]);

  const send = useCallback(async () => {
    const text = draft.trim();
    const hasReferences = hasConversationReferences(references);
    if (
      (!text && !hasReferences) ||
      isActiveSessionBusy ||
      !activeModel ||
      !projectId ||
      !canStartConversation
    ) return;
    if (sendStartupLockedRef.current) return;
    sendStartupLockedRef.current = true;
    const streamProjectId = projectId;
    let streamSession: ConversationSession | null;
    try {
      streamSession = await ensureSession(streamProjectId);
    } catch {
      sendStartupLockedRef.current = false;
      return;
    }
    if (!streamSession) {
      sendStartupLockedRef.current = false;
      return;
    }
    const sessionId = streamSession.session_id;
    const streamModel = models.find((model) =>
      model.providerId === streamSession.provider_id &&
      model.modelId === streamSession.model_id
    ) ?? activeModel;
    const streamReasoningMode = streamSession.reasoning_mode;
    const streamSessionKey = buildSessionKey(streamProjectId, sessionId);
    if (sendingSessionKeysRef.current.has(streamSessionKey)) {
      sendStartupLockedRef.current = false;
      return;
    }
    sendingSessionKeysRef.current.add(streamSessionKey);
    sendStartupLockedRef.current = false;
    let streamController: AbortController;
    try {
      streamController = createSessionStreamController(streamSessionKey);
    } catch {
      sendingSessionKeysRef.current.delete(streamSessionKey);
      return;
    }
    const streamSessionSettings = streamSession.settings;
    const canApplyStreamUpdate = () =>
      activeProjectIdRef.current === streamProjectId && activeSessionIdRef.current === sessionId;
    const requestReferences = toConversationDraftReferences(references);
    const requestUserContentParts = supportsImageInput
      ? buildConversationImageContentParts(references, streamProjectId)
      : [];
    const userMessageId = crypto.randomUUID();
    const requestMessages: ChatCompletionMessageInput[] = [{
      role: "user",
      content: text,
      message_id: userMessageId,
      ...(hasReferences ? { references: requestReferences } : {}),
      ...(requestUserContentParts.length
        ? { content_parts: requestUserContentParts }
        : {}),
    }];
    const userMsg: ChatMessage = {
      id: userMessageId,
      role: "user",
      content: text,
      contentParts: requestUserContentParts,
      references: hasReferences ? requestReferences : undefined,
      targetProviderId: streamModel.providerId,
      targetModelId: streamModel.modelId,
      thinkingContent: "",
      status: "done",
      usage: null,
      isThinkingExpanded: false,
      thinkingStartedAt: null,
      thinkingFinishedAt: null,
      createdAt: Date.now(),
    };
    if (canApplyStreamUpdate()) {
      preserveCurrentView();
    }
    updateSessionMessages(streamProjectId, sessionId, (prev) => [...prev, userMsg]);
    if (canApplyStreamUpdate()) {
      setDraft("");
      if (hasReferences) {
        clearReferences();
      }
      showChatView();
    }
    markSessionStreaming(streamSessionKey);
    saveSessionState(streamProjectId, sessionId, {
      draft: "",
      references: emptyConversationDraftReferences(),
    });
    setSessionRuntimeStatus(streamProjectId, sessionId, "running");

    const assistantId = crypto.randomUUID();
    const assistantStartedAt = Date.now();
    updateSessionMessages(streamProjectId, sessionId, (prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        providerId: streamModel.providerId,
        modelId: streamModel.modelId,
        thinkingContent: "",
        status: "running",
        usage: null,
        isThinkingExpanded: true,
        thinkingStartedAt: assistantStartedAt,
        thinkingFinishedAt: null,
        processItems: [],
        toolCalls: [],
        createdAt: assistantStartedAt,
        updatedAt: assistantStartedAt,
      },
    ]);

    let shouldRefreshPersistedUsageOnNextToolCall = false;
    const streamAccumulator = createChatStreamAccumulator({
      assistantId,
      isSessionPresented: () => isSessionMessagesPresented(streamProjectId, sessionId),
      isThinkingStuckToBottom,
      onUsage: (usage) => {
        shouldRefreshPersistedUsageOnNextToolCall = true;
        dispatchProjectConversationUpdated({
          kind: "usage",
          projectId: streamProjectId,
          sessionId,
          usage,
        });
      },
      scrollThinkingContentToBottom,
      sessionId,
      streamProjectId,
      streamingEnabled: streamSessionSettings.streaming_enabled,
      updateSessionMessages,
    });
    let shouldClearEventSequence = false;
    let publishedRunningContent = false;
    let streamWasCancelled = false;

    try {
      await streamChatCompletion(buildConversationRunRequest({
        providerId: streamModel.providerId,
        modelId: streamModel.modelId,
        projectId: streamProjectId,
        sessionId,
        messages: requestMessages,
        settings: streamSessionSettings,
        reasoningMode: streamReasoningMode,
        clientCapabilities: clientToolCapabilities,
      }), {
        onEvent: async (event) => {
          if (!publishedRunningContent) {
            publishedRunningContent = true;
            dispatchProjectConversationUpdated({
              kind: "content",
              projectId: streamProjectId,
              sessionId,
            });
          }
          await processSequencedChatStreamEvent(
            streamSessionKey,
            event,
            streamEventSequenceState,
            async () => {
              if (
                event.kind === "conversation_run_settled" &&
                event.status === "cancelled"
              ) {
                streamWasCancelled = true;
                streamAccumulator.finalizeCancelled();
                return;
              }
              const shouldRender = await processChatStreamEventSideEffects(
                event,
                clientToolExecutor,
              );
              if (shouldRender) {
                streamAccumulator.handleEvent(event);
              }
              if (
                event.kind === "tool_call"
                && shouldRefreshPersistedUsageOnNextToolCall
              ) {
                shouldRefreshPersistedUsageOnNextToolCall = false;
                void reloadSessionUsageSummary(streamProjectId, sessionId, {
                  forceRefresh: true,
                }).catch(() => undefined);
              }
            },
          );
        },
      }, { signal: streamController.signal });
      shouldClearEventSequence = true;
      const streamHadError = streamAccumulator.hadError();
      streamAccumulator.flushNow();
      updateSessionMessages(streamProjectId, sessionId, (prev) => prev.map((message) =>
        message.id === assistantId
          ? {
              ...message,
              status: streamWasCancelled
                ? "cancelled"
                : streamHadError
                  ? "error"
                  : "done",
              updatedAt: Date.now(),
            }
          : message,
      ));
      await reloadSessionMessages(streamProjectId, sessionId, {
        forceRefresh: true,
      }).catch(() => undefined);
      void reloadSessionUsageSummary(streamProjectId, sessionId, { forceRefresh: true }).catch(() => undefined);
      emitLlmUsageChanged({
        providerId: streamModel.providerId,
        modelId: streamModel.modelId,
      });
      setSessionRuntimeStatus(
        streamProjectId,
        sessionId,
        streamHadError ? "error" : "idle",
      );
      await reloadSessions(streamProjectId);
      for (const delayMs of [2000, 5000, 10000]) {
        window.setTimeout(() => {
          if (activeProjectIdRef.current !== streamProjectId) return;
          void reloadSessions(streamProjectId);
          void reloadSessionMessages(streamProjectId, sessionId, {
            forceRefresh: true,
            preserveLocalIfShorter: true,
          }).catch(() => undefined);
          void reloadSessionUsageSummary(streamProjectId, sessionId, { forceRefresh: true }).catch(() => undefined);
          emitLlmUsageChanged();
        }, delayMs);
      }
    } catch (err) {
      streamAccumulator.clearFlushTimer();
      if (isAbortError(err)) {
        shouldClearEventSequence = true;
        streamAccumulator.finalizeCancelled();
        await reloadSessions(streamProjectId);
        for (const delayMs of [300, 1200, 3000]) {
          window.setTimeout(() => {
            if (activeProjectIdRef.current !== streamProjectId) return;
            void reloadSessions(streamProjectId);
            void reloadSessionMessages(streamProjectId, sessionId, {
              forceRefresh: true,
              preserveLocalIfShorter: true,
            }).catch(() => undefined);
            void reloadSessionUsageSummary(streamProjectId, sessionId, { forceRefresh: true }).catch(() => undefined);
          }, delayMs);
        }
        return;
      }
      if (isConversationStreamResyncRequired(err)) {
        shouldClearEventSequence = true;
        setSessionRuntimeStatus(streamProjectId, sessionId, "running");
        await Promise.all([
          reloadSessionMessages(streamProjectId, sessionId, {
            forceRefresh: true,
            preserveLocalIfShorter: true,
          }).catch(() => undefined),
          reloadSessionUsageSummary(streamProjectId, sessionId, {
            forceRefresh: true,
          }).catch(() => undefined),
        ]);
      } else if (err instanceof HttpRequestError) {
        shouldClearEventSequence = true;
        updateSessionMessages(streamProjectId, sessionId, (prev) =>
          prev.map((m) => m.id === assistantId ? {
            ...m,
            role: "error",
            status: "error",
            content: err.message,
            updatedAt: Date.now(),
          } : m));
        if (isNotFoundRequestError(err)) {
          // 会话可能刚被删除；项目是否存在由会话列表接口统一判断。
        } else {
          setSessionRuntimeStatus(
            streamProjectId,
            sessionId,
            err.status === 409 ? "running" : "error",
          );
        }
        await Promise.all([
          reloadSessionMessages(streamProjectId, sessionId, {
            forceRefresh: true,
            preserveLocalIfShorter: true,
          }).catch(() => undefined),
          reloadSessionUsageSummary(streamProjectId, sessionId, {
            forceRefresh: true,
          }).catch(() => undefined),
        ]);
        emitLlmUsageChanged({
          providerId: streamModel.providerId,
          modelId: streamModel.modelId,
        });
      }
      await reloadSessions(streamProjectId);
      for (const delayMs of [300, 1200]) {
        window.setTimeout(() => {
          void reloadSessions(streamProjectId);
        }, delayMs);
      }
    } finally {
      streamAccumulator.clearFlushTimer();
      dispatchProjectConversationUpdated({
        kind: "content",
        projectId: streamProjectId,
        sessionId,
      });
      if (shouldClearEventSequence) {
        clearChatStreamEventSequence(streamSessionKey, streamEventSequenceState);
      }
      unmarkSessionStreaming(streamSessionKey);
      publishCurrentDraftSnapshot(streamProjectId, sessionId);
      releaseSessionStreamController(streamSessionKey, streamController);
      sendingSessionKeysRef.current.delete(streamSessionKey);
    }
  }, [
    activeModel,
    activeProjectIdRef,
    activeSessionIdRef,
    canStartConversation,
    clientToolExecutor,
    clientToolCapabilities,
    clearReferences,
    createSessionStreamController,
    draft,
    ensureSession,
    references,
    isActiveSessionBusy,
    isSessionMessagesPresented,
    isThinkingStuckToBottom,
    markSessionStreaming,
    models,
    projectId,
    releaseSessionStreamController,
    reloadSessionMessages,
    reloadSessionUsageSummary,
    reloadSessions,
    saveSessionState,
    preserveCurrentView,
    publishCurrentDraftSnapshot,
    scrollThinkingContentToBottom,
    setDraft,
    setSessionRuntimeStatus,
    streamEventSequenceState,
    showChatView,
    supportsImageInput,
    unmarkSessionStreaming,
    updateSessionMessages,
  ]);

  return { send };
}
