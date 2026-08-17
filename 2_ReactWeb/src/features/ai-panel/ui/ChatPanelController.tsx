import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type {
  ProjectFileDragData,
  ProjectFileReferenceRequest,
} from "../../../entities/project/model/projectFileDragData";
import type {
  EditorExternalPathReferenceRequest,
  EditorReferenceViewerPayload,
} from "../../../entities/editor/model/editorReference";
import type { ConversationMessageReferences } from "../../../entities/llm-chat/model/chatCompletion";
import type { ConversationSession } from "../../../entities/llm-chat/model/conversation";
import { stopChatCompletionStream } from "../../../services/llm/stopChatCompletionStream";
import { useComposerResize } from "../model/useComposerResize";
import {
  getLastMessageContextMeasurement,
  type ChatMessage,
} from "../model/chatMessage";
import { useChatStreamControllers } from "../model/useChatStreamControllers";
import { useChatModelOptions } from "../model/useChatModelOptions";
import { useThinkingAutoScroll } from "../model/useThinkingAutoScroll";
import { useBodyAutoScroll } from "../model/useBodyAutoScroll";
import { useConversationUsage } from "../model/useConversationUsage";
import { useSessionMessages } from "../model/useSessionMessages";
import { useSessionSettingsEditor } from "../model/useSessionSettingsEditor";
import { useChatGeneration } from "../model/useChatGeneration";
import { useDetachedConversationStream } from "../model/useDetachedConversationStream";
import { useConversationSessions } from "../model/useConversationSessions";
import { useConversationReasoning } from "../model/useConversationReasoning";
import { useChatConversationCreator } from "../model/useChatConversationCreator";
import { useChatExternalSessionSelection } from "../model/useChatExternalSessionSelection";
import { useChatPanelMessageInteractions } from "../model/useChatPanelMessageInteractions";
import { useConversationBranching } from "../model/useConversationBranching";
import type { MessageVariantTarget } from "../model/conversationMessageVariants";
import { useChatPanelModelSelection } from "../model/useChatPanelModelSelection";
import { useChatInjectionPreviewDraft } from "../model/useChatInjectionPreviewDraft";
import { fromConversationDraftReferences } from "../model/conversationDraftReferences";
import { useChatDraftReferences } from "../model/useChatDraftReferences";
import { useChatPanelClientToolRegistry } from "../model/useChatPanelClientToolRegistry";
import { useChatComposerReferences } from "../model/useChatComposerReferences";
import {
  useActiveSessionLiveReload,
  useActiveSessionMessagesLoader,
  useChatPanelPopoverDismiss,
  useStreamingClockTick,
} from "../model/useChatPanelLifecycleEffects";
import type {
  ChatPanelSessionSelectionRequest,
  ChatPanelSessionSelectionResult,
} from "../model/chatSessionSelectionRequest";
import { resolveSessionSettings } from "../model/sessionSettings";
import { buildSessionKey } from "../model/sessionKey";
import type { CodeBlockSavePayload } from "../../markdown-preview/model/codeBlockFile";
import type { ClientToolRegistration } from "../../client-tools/model/clientToolBridge";
import { useAutomaticNamingConversationRuns } from "../../client-tools/model/useAutomaticNamingConversationRuns";
import type { ConversationExportRequest } from "../../conversation-export/model/conversationExport";
import { ConversationExportDialog } from "../../conversation-export/ui/ConversationExportDialog";
import {
  isNotFoundRequestError,
} from "../model/chatPanelRequestErrors";
import { ChatComposer } from "./ChatComposer";
import { ChatHeader, type ChatPanelView } from "./ChatHeader";
import { ChatPanelBodyFrame } from "./ChatPanelBodyFrame";
import type { ConversationDataFileName } from "./ChatDataDashboardPanel";
import { ChatSettingsTabs } from "./ChatSettingsTabs";
import type { ChatSettingsPanel } from "./ChatSettingsView";

type Props = {
  projectId: string | null;
  activeConversationDataFile?: ConversationDataFileName | null;
  clientToolRegistrations?: readonly ClientToolRegistration[];
  composerInitialHeight?: number;
  isActive?: boolean;
  isImageReferenceUploadPending?: boolean;
  references?: ConversationMessageReferences;
  onActiveUserMessageChange?: (
    projectId: string,
    sessionId: string,
    messageId: string | null,
  ) => void;
  onActiveSessionChange?: (projectId: string, sessionId: string | null) => void;
  onSessionSelectionResult?: (result: ChatPanelSessionSelectionResult) => void;
  onComposerHeightCommit?: (height: number) => void;
  onOpenConversationDataFile?: (sessionId: string, fileName: ConversationDataFileName) => void;
  onOpenConversationBranches?: () => void;
  onOpenConversationOverview?: () => void;
  onOpenReference?: (payload: EditorReferenceViewerPayload) => void;
  onPreviewHtmlCode?: (html: string) => void;
  onReferenceProjectFile?: (file: ProjectFileDragData) => void;
  onReferenceExternalPath?: (reference: EditorExternalPathReferenceRequest) => void;
  onClearReferences?: () => void;
  onDraftReferencesChange?: (references: ConversationMessageReferences) => void;
  onRemoveFileReference?: (referenceId: string) => void;
  onRemoveImageReference?: (referenceId: string) => void;
  onRemoveTextReference?: (referenceId: string) => void;
  onSaveCodeBlock?: (payload: CodeBlockSavePayload) => Promise<string>;
  onSelectExportDirectory?: () => Promise<string | null>;
  preferredSessionId?: string | null;
  projectFileReferenceRequest?: ProjectFileReferenceRequest | null;
  projectRootPath?: string;
  sessionSelectionError?: string | null;
  sessionSelectionRequest?: ChatPanelSessionSelectionRequest | null;
};

const EMPTY_CLIENT_TOOL_REGISTRATIONS: readonly ClientToolRegistration[] = [];

export function ChatPanelController({
  projectId,
  activeConversationDataFile,
  clientToolRegistrations = EMPTY_CLIENT_TOOL_REGISTRATIONS,
  composerInitialHeight,
  isActive = true,
  isImageReferenceUploadPending = false,
  references = [],
  onActiveUserMessageChange,
  onActiveSessionChange,
  onSessionSelectionResult,
  onComposerHeightCommit,
  onOpenConversationDataFile,
  onOpenConversationBranches,
  onOpenConversationOverview,
  onOpenReference,
  onPreviewHtmlCode,
  onReferenceExternalPath,
  onReferenceProjectFile,
  onClearReferences,
  onDraftReferencesChange,
  onRemoveFileReference,
  onRemoveImageReference,
  onRemoveTextReference,
  onSaveCodeBlock,
  onSelectExportDirectory,
  preferredSessionId = null,
  projectFileReferenceRequest,
  projectRootPath = "",
  sessionSelectionError = null,
  sessionSelectionRequest,
}: Props) {
  const [activeView, setActiveView] = useState<ChatPanelView>("chat");
  const [exportRequest, setExportRequest] = useState<ConversationExportRequest | null>(null);
  const isChatPresentationVisibleRef = useRef(isActive);
  isChatPresentationVisibleRef.current = isActive && activeView === "chat";
  const [activeSettingsPanel, setActiveSettingsPanel] = useState<ChatSettingsPanel>("basic");
  const variantNavigationRequestIdRef = useRef(0);
  const [variantNavigationRequest, setVariantNavigationRequest] = useState<{
    behavior: ScrollBehavior;
    messageId: string;
    requestId: number;
    sessionKey: string;
  } | null>(null);
  const showChatView = useCallback(() => setActiveView("chat"), []);
  const queueMessageNavigation = useCallback((sessionId: string, messageId: string) => {
    if (!projectId) return;
    variantNavigationRequestIdRef.current += 1;
    setVariantNavigationRequest({
      behavior: "auto",
      messageId,
      requestId: variantNavigationRequestIdRef.current,
      sessionKey: buildSessionKey(projectId, sessionId),
    });
  }, [projectId]);
  const {
    error: modelLoadError,
    isLoading: isModelLoading,
    models,
    reloadModels,
    selectedModel,
    setSelectedModel,
  } = useChatModelOptions();
  const [isModelMenuOpen, setIsModelMenuOpen] = useState(false);
  const {
    composerHeight,
    handleResizeStart,
    isResizing,
  } = useComposerResize({
    initialHeight: composerInitialHeight,
    onHeightCommit: onComposerHeightCommit,
  });
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const usageAreaRef = useRef<HTMLDivElement>(null);
  const activeProjectIdRef = useRef(projectId);
  activeProjectIdRef.current = projectId;
  const activeSessionIdRef = useRef<string | null>(null);
  const processedStreamEventSequencesRef = useRef(new Map<string, number>());
  const claimedStreamEventSequencesRef = useRef(new Set<string>());
  const queuedStreamEventSequencesRef = useRef(new Map<string, Promise<void>>());
  const streamEventSequenceState = useMemo(() => ({
    claimed: claimedStreamEventSequencesRef,
    processed: processedStreamEventSequencesRef,
    queues: queuedStreamEventSequencesRef,
  }), []);
  const handledSessionSelectionRequestIdRef = useRef<number | null>(null);
  const {
    abortProjectStreams,
    abortSessionStream,
    createSessionStreamController,
    releaseSessionStreamController,
  } = useChatStreamControllers();
  const {
    applyCachedSessionMessages,
    isSessionMessagesPresented,
    markSessionMessagesAccessed,
    publishSessionMessages,
    pruneSessionMessages,
    reloadSessionMessages,
    replaceSessionMessages,
    sessionMessages,
    updateSessionMessages,
  } = useSessionMessages({
    activeProjectIdRef,
    activeSessionIdRef,
    isPresentationVisibleRef: isChatPresentationVisibleRef,
  });
  const {
    activateSession,
    applyForkResult,
    activeSessionId,
    branchNodes,
    draft,
    isLoadingSessions,
    isSessionStreaming,
    markConversationProjectUnavailable,
    markSessionStreaming,
    messageVariants,
    publishCurrentDraftSnapshot,
    reloadSessions,
    reloadSessionsForSelection,
    retryLoadSessions,
    saveConversationState,
    saveSessionState,
    settledDraft,
    sessionStates,
    sessionLoadError,
    sessions,
    setActiveSessionId,
    setDraft,
    setSessionRuntimeStatus,
    setSessionStates,
    setSessions,
    streamingSessionKeys,
    unmarkSessionStreaming,
    unavailableProjectIdRef,
  } = useConversationSessions({
    abortProjectStreams,
    activeProjectIdRef,
    activeSessionIdRef,
    isActive,
    preferredSessionId,
    projectId,
    showChatView,
  });
  const {
    backgroundConversationRuns,
    clientToolCapabilities,
    clientToolExecutor: combinedClientToolExecutor,
  } = useChatPanelClientToolRegistry({
    activateSession,
    activeProjectIdRef,
    clientToolRegistrations,
    reloadSessionsForSelection,
    setSessionRuntimeStatus,
  });
  useAutomaticNamingConversationRuns({
    backgroundRuns: backgroundConversationRuns,
    branchNodes,
    clientToolExecutor: combinedClientToolExecutor,
    clientToolCapabilities,
    markSessionStreaming,
    projectId,
    reloadSessions,
    saveSessionState,
    sessionStates,
    sessions,
    setSessionRuntimeStatus,
    unmarkSessionStreaming,
  });
  const activeSession = sessions.find((session) => session.session_id === activeSessionId) ?? null;
  const handleRoleSessionUpdated = useCallback((updatedSession: ConversationSession) => {
    setSessions((current) => current.map((session) =>
      session.session_id === updatedSession.session_id ? updatedSession : session
    ));
  }, [setSessions]);
  const openConversationExport = useCallback(() => {
    if (!activeSession || !projectId) return;
    setExportRequest({
      initialDirectory: projectRootPath,
      messageId: null,
      projectId,
      scope: "conversation",
      sessionId: activeSession.session_id,
      sessionTitle: activeSession.title,
    });
  }, [activeSession, projectId, projectRootPath]);
  const openAssistantMessageExport = useCallback((message: ChatMessage) => {
    if (!activeSession || !projectId) return;
    setExportRequest({
      initialDirectory: projectRootPath,
      messageId: message.id,
      projectId,
      scope: "message",
      sessionId: activeSession.session_id,
      sessionTitle: activeSession.title,
    });
  }, [activeSession, projectId, projectRootPath]);
  useEffect(() => {
    if (!exportRequest) return;
    if (exportRequest.projectId !== projectId || exportRequest.sessionId !== activeSessionId) {
      setExportRequest(null);
    }
  }, [activeSessionId, exportRequest, projectId]);
  const canStartConversation = Boolean(
    activeSession || (!isLoadingSessions && !sessionLoadError),
  );
  const activeSessionSettings = useMemo(
    () => resolveSessionSettings(activeSession),
    [activeSession],
  );

  const {
    handleDropExternalPaths,
    handleDropProjectFile,
    handleExternalFileDrop,
    handlePasteFiles,
    uploadStatus,
  } = useChatComposerReferences({
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    onReferenceExternalPath,
    onReferenceProjectFile,
    projectFileReferenceRequest,
    projectId,
    projectRootPath,
    showChatView,
  });

  const pendingExternalSessionSelection =
    sessionSelectionRequest &&
    handledSessionSelectionRequestIdRef.current !== sessionSelectionRequest.requestId
      ? sessionSelectionRequest
      : null;

  useEffect(() => {
    if (!projectId || isLoadingSessions) return;
    if (
      pendingExternalSessionSelection &&
      (
        projectId !== pendingExternalSessionSelection.projectId ||
        activeSessionId !== pendingExternalSessionSelection.sessionId
      )
    ) {
      return;
    }
    onActiveSessionChange?.(projectId, activeSessionId);
  }, [
    activeSessionId,
    isLoadingSessions,
    onActiveSessionChange,
    pendingExternalSessionSelection?.requestId,
    pendingExternalSessionSelection?.sessionId,
    projectId,
  ]);

  useChatExternalSessionSelection({
    activateSession,
    activeSessionId,
    handledRequestIdRef: handledSessionSelectionRequestIdRef,
    onResult: onSessionSelectionResult,
    onNavigateToMessage: queueMessageNavigation,
    projectId,
    request: sessionSelectionRequest,
    reloadSessions: reloadSessionsForSelection,
    sessions,
    showChatView,
  });

  const {
    activeModel,
    activeReasoningMode,
    reasoningOptions,
    runtimeCapabilities,
    shouldShowReasoningControl,
    supportedReasoningModes,
    updateActiveReasoningMode,
  } = useConversationReasoning({
    activeProjectIdRef,
    activeSession,
    activeSessionId,
    isModelLoading,
    models,
    projectId,
    reloadSessions,
    selectedModel,
    setSessions,
  });
  const activeSessionKey = projectId && activeSessionId ? buildSessionKey(projectId, activeSessionId) : null;
  const isStreamPresentationVisible = isActive && activeView === "chat";
  const isActiveSessionStreaming = activeSessionKey ? streamingSessionKeys.has(activeSessionKey) : false;
  const supportsImageInput = runtimeCapabilities?.inputModalities.includes("image") ?? false;
  useLayoutEffect(() => {
    if (!projectId || !activeSessionId) {
      return;
    }
    markSessionMessagesAccessed(projectId, activeSessionId);
    if (!isActiveSessionStreaming) {
      applyCachedSessionMessages(projectId, activeSessionId);
    }
    publishSessionMessages(projectId, activeSessionId);
  }, [
    activeSessionId,
    applyCachedSessionMessages,
    isActiveSessionStreaming,
    isStreamPresentationVisible,
    markSessionMessagesAccessed,
    projectId,
    publishSessionMessages,
  ]);
  const isModelPickerDisabled = isModelLoading;
  const messages = activeSessionKey ? sessionMessages[activeSessionKey] ?? [] : [];
  const contextMeasurement = useMemo(
    () => getLastMessageContextMeasurement(messages),
    [messages],
  );
  const activeSessionState = activeSessionId ? sessionStates[activeSessionId] : null;
  const saveSessionReferences = useCallback((
    targetProjectId: string,
    targetSessionId: string,
    nextReferences: ConversationMessageReferences,
  ) => {
    saveSessionState(targetProjectId, targetSessionId, { references: nextReferences });
  }, [saveSessionState]);
  useChatDraftReferences({
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    activeSessionState,
    onDraftReferencesChange,
    projectId,
    references,
    saveSessionReferences,
  });
  const isActiveSessionBusy =
    isActiveSessionStreaming || activeSessionState?.runtime_status === "running";
  const navigateToMessageVariant = useCallback((target: MessageVariantTarget) => {
    queueMessageNavigation(target.sessionId, target.messageId);
  }, [queueMessageNavigation]);
  const isActiveSessionRunningPresentation =
    isStreamPresentationVisible && isActiveSessionBusy;
  useEffect(() => {
    const retainedSessionKeys = new Set([
      ...processedStreamEventSequencesRef.current.keys(),
    ]);
    pruneSessionMessages({
      activeProjectId: projectId,
      activeSessionId,
      retainedSessionKeys,
      streamingSessionKeys,
    });
  }, [
    activeSessionId,
    projectId,
    pruneSessionMessages,
    streamingSessionKeys,
  ]);

  const clockTick = useStreamingClockTick(isActiveSessionRunningPresentation);
  useChatInjectionPreviewDraft({
    activeModel,
    activeReasoningMode,
    activeSessionId,
    activeSessionSettings,
    references,
    isActiveSessionStreaming: isActiveSessionBusy,
    projectId,
    settledDraft,
    supportsImageInput,
  });
  const {
    bodyRef,
    handleBodyScroll,
    isSessionSettling,
    pauseAutoScrollForNavigation,
    preserveCurrentView,
    scrollToBottom,
    showScrollToBottom,
    viewRestoreRequest,
    onViewRestoreHandled,
  } = useBodyAutoScroll({
    activeSessionKey,
    isChatViewActive: activeView === "chat",
    messages,
    navigationTargetSessionKey: variantNavigationRequest?.sessionKey ?? null,
  });
  const handleExternalNavigationHandled = useCallback((requestId: number) => {
    setVariantNavigationRequest((current) => (
      current?.requestId === requestId ? null : current
    ));
  }, []);
  useLayoutEffect(() => {
    if (activeView !== "settings") return;
    bodyRef.current?.scrollTo({ left: 0, top: 0, behavior: "auto" });
  }, [activeSettingsPanel, activeView, bodyRef]);
  const {
    handleThinkingContentScroll,
    handleThinkingContentWheel,
    isThinkingStuckToBottom,
    pauseThinkingAutoScroll,
    scrollThinkingContentToBottom,
    setThinkingContentRef,
  } = useThinkingAutoScroll(messages);
  const {
    branchError,
    forkUserMessage,
    getVariantNavigation,
  } = useConversationBranching({
    activeSessionId,
    applyForkResult,
    isActiveSessionBusy,
    messageVariants,
    onActivateSession: activateSession,
    onDraftReferencesChange: (references) => {
      onDraftReferencesChange?.(fromConversationDraftReferences(references));
    },
    onNavigateToVariant: navigateToMessageVariant,
    projectId,
    reloadSessionMessages,
    sessions,
  });
  const {
    expandedUserMessageIds,
    messageInteractions,
  } = useChatPanelMessageInteractions({
    activeSessionId,
    handleThinkingContentScroll,
    handleThinkingContentWheel,
    onOpenReference,
    onPreviewHtmlCode,
    onSaveCodeBlock,
    pauseThinkingAutoScroll,
    projectId,
    setThinkingContentRef,
    updateSessionMessages,
    getVariantNavigation,
    onExportAssistantMessage: openAssistantMessageExport,
    onForkUserMessage: (message) => {
      void forkUserMessage(message);
    },
  });
  const {
    isUsagePopoverOpen,
    reloadSessionUsageSummary,
    selectedUsage,
    sessionUsage,
    setIsUsagePopoverOpen,
    setUsageScopeKey,
    usageScopeKey,
    usageScopeOptions,
  } = useConversationUsage({
    activeProjectIdRef,
    activeSessionId,
    activeSessionKey,
    isActive,
    projectId,
  });
  const {
    saveActiveSessionTitle,
    saveActiveSystemPrompt,
    saveErrorMessage,
    sessionTitleDraft,
    setSessionTitleDraft,
    setSystemPromptDraft,
    systemPromptDraft,
    updateActiveSessionSettings,
  } = useSessionSettingsEditor({
    activeProjectIdRef,
    activeSession,
    activeSessionId,
    activeSessionSettings,
    projectId,
    reloadSessions,
    setSessions,
  });

  useActiveSessionMessagesLoader({
    activeSessionId,
    isActive,
    isSessionStreaming,
    isNotFoundRequestError,
    projectId,
    reloadSessionMessages,
    reloadSessions,
  });

  useActiveSessionLiveReload({
    activeRuntimeStatus: activeSessionState?.runtime_status ?? null,
    activeSessionId,
    branchNodes,
    isActive,
    isActiveSessionStreaming,
    isSessionStreaming,
    isNotFoundRequestError,
    messages,
    projectId,
    reloadSessionMessages,
    reloadSessions,
    sessionStates,
  });

  useDetachedConversationStream({
    activeSessionId,
    activeSessionKey,
    clientToolExecutor: combinedClientToolExecutor,
    isActive: isStreamPresentationVisible,
    isSessionMessagesPresented,
    isThinkingStuckToBottom,
    markSessionStreaming,
    projectId,
    reloadSessionMessages,
    reloadSessionUsageSummary,
    reloadSessions,
    runtimeStatus: activeSessionState?.runtime_status ?? null,
    scrollThinkingContentToBottom,
    streamEventSequenceState,
    streamingEnabled: activeSessionSettings.streaming_enabled,
    streamingSessionKeys,
    setSessionRuntimeStatus,
    unmarkSessionStreaming,
    updateSessionMessages,
  });

  useChatPanelPopoverDismiss({
    modelMenuRef,
    setIsModelMenuOpen,
    setIsUsagePopoverOpen,
    usageAreaRef,
  });

  const { send } = useChatGeneration({
    activeModel,
    activeProjectIdRef,
    activeSessionId,
    activeSessionIdRef,
    canStartConversation,
    clientToolExecutor: combinedClientToolExecutor,
    clientToolCapabilities,
    clearReferences: onClearReferences ?? (() => undefined),
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
    setSessionRuntimeStatus,
    setSessionStates,
    setSessions,
    streamEventSequenceState,
    showChatView,
    supportsImageInput,
    unmarkSessionStreaming,
    updateSessionMessages,
    unavailableProjectIdRef,
  });

  const stopActiveGeneration = useCallback(() => {
    if (!projectId || !activeSessionId || !activeSessionKey) return;
    preserveCurrentView();
    const stopRequest = stopChatCompletionStream(projectId, activeSessionId);
    let didSettleStop = false;
    abortSessionStream(activeSessionKey);
    void stopRequest
      .then(() => {
        didSettleStop = true;
        setSessionRuntimeStatus(projectId, activeSessionId, "idle");
      })
      .catch(() => undefined)
      .finally(() => {
        void reloadSessions(projectId);
        void reloadSessionMessages(projectId, activeSessionId, {
          forceRefresh: true,
          preserveLocalIfShorter: !didSettleStop,
        }).catch(() => undefined);
      });
  }, [
    abortSessionStream,
    activeSessionId,
    activeSessionKey,
    projectId,
    preserveCurrentView,
    reloadSessionMessages,
    reloadSessions,
    setSessionRuntimeStatus,
  ]);

  const {
    createConversationError,
    createNewConversation,
    isCreatingConversation,
  } = useChatConversationCreator({
    activeProjectIdRef,
    activeSessionIdRef,
    isNotFoundRequestError,
    markConversationProjectUnavailable,
    projectId,
    replaceSessionMessages,
    saveConversationState,
    setActiveSessionId,
    setDraft,
    setSessionStates,
    setSessions,
    showChatView,
  });

  const selectModel = useChatPanelModelSelection({
    activeProjectIdRef,
    activeSessionId,
    projectId,
    reloadSessions,
    setIsModelMenuOpen,
    setSelectedModel,
    setSessions,
  });
  const hasComposerMessageContent = Boolean(
    draft.trim() ||
      references.length,
  );
  const isImageUploadPending = uploadStatus.kind === "saving" || isImageReferenceUploadPending;
  const composerUploadStatus = isImageUploadPending
    ? { kind: "saving" as const, message: null }
    : uploadStatus;
  const handleActiveUserMessageChange = useCallback((messageId: string | null) => {
    if (projectId && activeSessionId) {
      onActiveUserMessageChange?.(projectId, activeSessionId, messageId);
    }
  }, [activeSessionId, onActiveUserMessageChange, projectId]);

  return (
    <>
      <ChatHeader
        activeSession={activeSession}
        activeView={activeView}
        canCreateConversation={Boolean(
          projectId && !isLoadingSessions && !sessionLoadError && !isCreatingConversation
        )}
        canExportConversation={Boolean(activeSession)}
        canOpenBranches={Boolean(projectId)}
        canOpenConversationOverview={Boolean(projectId && onOpenConversationOverview)}
        isLoadingSession={Boolean(projectId && isLoadingSessions && !activeSession)}
        onCreateConversation={createNewConversation}
        onExportConversation={openConversationExport}
        onOpenBranches={() => onOpenConversationBranches?.()}
        onOpenConversationOverview={() => onOpenConversationOverview?.()}
        onShowChat={() => setActiveView("chat")}
        onToggleSettings={() => {
          if (activeView === "settings") {
            setActiveView("chat");
            return;
          }
          if (activeView === "chat") {
            preserveCurrentView();
          }
          setActiveSettingsPanel("basic");
          setActiveView("settings");
        }}
      />

      {createConversationError ? (
        <div className="ai-panel__inline-error" role="status">
          {createConversationError}
        </div>
      ) : null}

      {sessionLoadError ? (
        <div className="ai-panel__inline-error" role="status">
          <span>{sessionLoadError}</span>
          <button type="button" onClick={retryLoadSessions}>重试</button>
        </div>
      ) : null}

      {sessionSelectionError ? (
        <div className="ai-panel__inline-error" role="status">
          {sessionSelectionError}
        </div>
      ) : null}

      {branchError ? (
        <div className="ai-panel__inline-error" role="status">
          {branchError}
        </div>
      ) : null}

      {activeView === "settings" && (
        <ChatSettingsTabs
          activePanel={activeSettingsPanel}
          onClose={showChatView}
          onSelectPanel={setActiveSettingsPanel}
        />
      )}

      <ChatPanelBodyFrame
        activeSessionKey={activeSessionKey}
        activeView={activeView}
        bodyRef={bodyRef}
        externalNavigationRequest={variantNavigationRequest}
        viewRestoreRequest={viewRestoreRequest}
        isMessageNavigationTrackingEnabled={
          !isSessionSettling && variantNavigationRequest === null
        }
        onActiveUserMessageChange={handleActiveUserMessageChange}
        onMessageNavigationStart={pauseAutoScrollForNavigation}
        onExternalNavigationHandled={handleExternalNavigationHandled}
        onViewRestoreHandled={onViewRestoreHandled}
        onBodyScroll={handleBodyScroll}
        chat={{
          autoCollapseAssistantProcess: activeSessionSettings.auto_collapse_assistant_process,
          clockTick,
          expandedUserMessageIds,
          interactions: messageInteractions,
          isActiveSessionStreaming: isActiveSessionRunningPresentation,
          isLoadingSession: Boolean(projectId && isLoadingSessions && !activeSession),
          messages,
          runtimeStatus: isActiveSessionStreaming
            ? "running"
            : activeSessionState?.runtime_status ?? null,
          scrollParentRef: bodyRef,
        }}
        scrollBottom={{
          isVisible: showScrollToBottom && messages.length > 0,
          onClick: () => scrollToBottom("smooth"),
        }}
        settings={{
          activeReasoningMode,
          activeConversationDataFile,
          activeSession,
          activeSettingsPanel,
          activeSessionSettings,
          projectId,
          onOpenConversationDataFile,
          onRoleSessionUpdated: handleRoleSessionUpdated,
          onSaveSessionTitle: saveActiveSessionTitle,
          onSaveSystemPrompt: saveActiveSystemPrompt,
          saveErrorMessage,
          onSessionTitleDraftChange: setSessionTitleDraft,
          onSystemPromptDraftChange: setSystemPromptDraft,
          onUpdateReasoningMode: updateActiveReasoningMode,
          onUpdateSessionSettings: updateActiveSessionSettings,
          reasoningOptions,
          sessionTitleDraft,
          shouldShowReasoningControl,
          systemPromptDraft,
        }}
      />

      {activeView === "chat" ? (
        <ChatComposer
          generation={{
            isStreaming: isActiveSessionBusy,
            onStop: stopActiveGeneration,
          }}
          input={{
            canSend: Boolean(
              hasComposerMessageContent &&
              activeModel &&
              projectId &&
              !isActiveSessionBusy &&
              !isImageUploadPending &&
              canStartConversation
            ),
            draft,
            externalFileDropScopeKey: projectId && activeSessionId
              ? `${projectId}:${activeSessionId}`
              : null,
            references,
            onDraftChange: setDraft,
            onExternalFileDrop: handleExternalFileDrop,
            onDropProjectFile: handleDropProjectFile,
            onOpenReference,
            onPasteFiles: handlePasteFiles,
            onRemoveFileReference,
            onRemoveImageReference,
            onRemoveTextReference,
            onSend: () => {
              if (isImageUploadPending) return;
              void send();
            },
            uploadStatus: composerUploadStatus,
          }}
          layout={{
            height: composerHeight,
            isResizing,
            onResizeStart: handleResizeStart,
          }}
          modelPicker={{
            activeModel,
            activeSession,
            isDisabled: isModelPickerDisabled,
            isLoading: isModelLoading,
            isOpen: isModelMenuOpen,
            loadError: modelLoadError,
            menuRef: modelMenuRef,
            models,
            onReload: reloadModels,
            onSelect: selectModel,
            onToggleOpen: setIsModelMenuOpen,
          }}
          reasoning={{
            activeMode: activeReasoningMode,
            isVisible: shouldShowReasoningControl,
            onChange: updateActiveReasoningMode,
            options: reasoningOptions,
          }}
          usage={{
            areaRef: usageAreaRef,
            contextTokens: contextMeasurement.tokens,
            contextTokensEstimated: contextMeasurement.estimated,
            isOpen: isUsagePopoverOpen,
            onSelectScope: setUsageScopeKey,
            onToggleOpen: setIsUsagePopoverOpen,
            scopeKey: usageScopeKey,
            scopeOptions: usageScopeOptions,
            selected: selectedUsage,
            session: sessionUsage,
          }}
        />
      ) : null}
      {exportRequest ? (
        <ConversationExportDialog
          key={`${exportRequest.sessionId}:${exportRequest.messageId ?? "conversation"}`}
          request={exportRequest}
          onClose={() => setExportRequest(null)}
          onSelectDirectory={onSelectExportDirectory ?? (async () => null)}
        />
      ) : null}
    </>
  );
}
