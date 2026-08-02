import { useCallback, useEffect, useReducer, useRef } from "react";

import type {
  ChatPanelSessionSelectionRequest,
  ChatPanelSessionSelectionResult,
} from "../../../features/ai-panel/model/chatSessionSelectionRequest";
import {
  initialConversationSelectionState,
  reduceConversationSelection,
  visibleConversationSelection,
  type ConversationSelectionRequest,
} from "../../../features/ai-panel/model/conversationSelectionMachine";
import { createDefaultConversation } from "../../../features/ai-panel/model/createDefaultConversation";
import type { ProjectEntryWarmupOptions } from "../../../features/project-entry/model/projectEntryWarmup";
import { saveWorkspaceLastOpened } from "../../../services/workspace/workspaceLastOpened";

type ProjectSelectionHandler = (
  projectId: string,
  options?: ProjectEntryWarmupOptions,
) => boolean | void | Promise<boolean | void>;

type UseWorkspaceConversationSelectionOptions = {
  onConfirmProjectSession: (projectId: string, sessionId: string | null) => void;
  onExpandProject: ProjectSelectionHandler;
  onSelectProject: ProjectSelectionHandler;
  persistWorkspaceSelection?: boolean;
  projectId: string | null;
  selectedSessionId: string | null;
};

export function useWorkspaceConversationSelection({
  onConfirmProjectSession,
  onExpandProject,
  onSelectProject,
  persistWorkspaceSelection = true,
  projectId,
  selectedSessionId,
}: UseWorkspaceConversationSelectionOptions) {
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;
  const selectionRequestIdRef = useRef(0);
  const selectionCompletionRef = useRef<{
    requestId: number;
    resolve: (confirmed: boolean) => void;
  } | null>(null);
  const lastSavedWorkspaceSessionRef = useRef<string | null>(null);
  const [selectionState, dispatchSelection] = useReducer(
    reduceConversationSelection,
    initialConversationSelectionState,
  );
  const selectionStateRef = useRef(selectionState);
  selectionStateRef.current = selectionState;

  const saveWorkspaceSessionSelection = useCallback((
    nextProjectId: string,
    nextSessionId: string | null,
  ) => {
    if (!persistWorkspaceSelection) return;
    const key = `${nextProjectId}:${nextSessionId ?? ""}`;
    if (lastSavedWorkspaceSessionRef.current === key) return;
    lastSavedWorkspaceSessionRef.current = key;
    void saveWorkspaceLastOpened({
      project_id: nextProjectId,
      session_id: nextSessionId,
    }).catch(() => {
      if (lastSavedWorkspaceSessionRef.current === key) {
        lastSavedWorkspaceSessionRef.current = null;
      }
    });
  }, [persistWorkspaceSelection]);

  useEffect(() => {
    dispatchSelection({ type: "project_changed", projectId });
  }, [projectId]);

  useEffect(() => {
    if (selectionState.status === "selecting" || !selectionCompletionRef.current) return;
    selectionCompletionRef.current.resolve(false);
    selectionCompletionRef.current = null;
  }, [selectionState.status]);

  const completeSelection = useCallback((requestId: number, confirmed: boolean) => {
    const completion = selectionCompletionRef.current;
    if (!completion || completion.requestId !== requestId) return;
    selectionCompletionRef.current = null;
    completion.resolve(confirmed);
  }, []);

  const startSessionSelection = useCallback((
    targetProjectId: string,
    sessionId: string,
    source: ConversationSelectionRequest["source"],
    messageId?: string,
  ) => {
    selectionCompletionRef.current?.resolve(false);
    selectionRequestIdRef.current += 1;
    const request: ConversationSelectionRequest = {
      requestId: selectionRequestIdRef.current,
      source,
      target: { projectId: targetProjectId, sessionId, ...(messageId ? { messageId } : {}) },
    };
    dispatchSelection({ type: "request", request });
    const completion = new Promise<boolean>((resolve) => {
      selectionCompletionRef.current = { requestId: request.requestId, resolve };
    });
    return { completion, requestId: request.requestId };
  }, []);

  const markProjectReady = useCallback((requestId: number) => {
    dispatchSelection({ type: "project_ready", requestId });
  }, []);

  const failProjectSelection = useCallback((requestId: number, error: unknown) => {
    dispatchSelection({
      type: "failed",
      current: selectionStateRef.current.current,
      message: error instanceof Error ? error.message : "会话所在项目载入失败。",
      reason: "failed",
      requestId,
    });
    completeSelection(requestId, false);
  }, [completeSelection]);

  const cancelProjectSelection = useCallback((requestId: number) => {
    dispatchSelection({ type: "cancelled", requestId });
    completeSelection(requestId, false);
  }, [completeSelection]);

  const handleChatActiveSessionChange = useCallback((
    nextProjectId: string,
    nextSessionId: string | null,
  ) => {
    if (nextProjectId !== projectIdRef.current) return;
    const target = { projectId: nextProjectId, sessionId: nextSessionId };
    const currentState = selectionStateRef.current;
    if (currentState.status === "selecting") {
      if (
        currentState.request.target.projectId !== nextProjectId ||
        currentState.request.target.sessionId !== nextSessionId
      ) {
        return;
      }
      dispatchSelection({
        type: "confirmed",
        requestId: currentState.request.requestId,
        target,
      });
      completeSelection(currentState.request.requestId, true);
    } else {
      dispatchSelection({ type: "sync_current", target });
    }
    onConfirmProjectSession(nextProjectId, nextSessionId);
    saveWorkspaceSessionSelection(nextProjectId, nextSessionId);
  }, [completeSelection, onConfirmProjectSession, saveWorkspaceSessionSelection]);

  const handleChatSessionSelectionResult = useCallback((
    result: ChatPanelSessionSelectionResult,
  ) => {
    const current = {
      projectId: result.projectId,
      sessionId: result.activeSessionId,
    };
    dispatchSelection({
      type: "failed",
      current,
      message: result.message ?? (
        result.status === "missing"
          ? "目标会话不存在，已回到当前可用会话。"
          : "会话切换失败，请重试。"
      ),
      reason: result.status,
      requestId: result.requestId,
    });
    completeSelection(result.requestId, false);
    onConfirmProjectSession(result.projectId, result.activeSessionId);
    saveWorkspaceSessionSelection(result.projectId, result.activeSessionId);
  }, [completeSelection, onConfirmProjectSession, saveWorkspaceSessionSelection]);

  const handleSelectOverviewSession = useCallback(async (
    targetProjectId: string,
    sessionId: string,
    messageId?: string,
  ) => {
    const { completion, requestId } = startSessionSelection(
      targetProjectId,
      sessionId,
      messageId ? "branch" : "overview",
      messageId,
    );
    try {
      const didSelect = await onSelectProject(targetProjectId, {
        refreshConversations: true,
        sessionId,
      });
      if (didSelect === false) {
        cancelProjectSelection(requestId);
        return false;
      }
      markProjectReady(requestId);
      return await completion;
    } catch (error) {
      failProjectSelection(requestId, error);
      return false;
    }
  }, [cancelProjectSelection, failProjectSelection, markProjectReady, onSelectProject, startSessionSelection]);

  const handleEnterOverviewSession = useCallback(async (
    targetProjectId: string,
    sessionId: string,
  ) => {
    const { completion, requestId } = startSessionSelection(
      targetProjectId,
      sessionId,
      "overview",
    );
    try {
      const didExpand = await onExpandProject(targetProjectId, {
        refreshConversations: true,
        sessionId,
      });
      if (didExpand === false) {
        cancelProjectSelection(requestId);
        return false;
      }
      markProjectReady(requestId);
      return await completion;
    } catch (error) {
      failProjectSelection(requestId, error);
      return false;
    }
  }, [cancelProjectSelection, failProjectSelection, markProjectReady, onExpandProject, startSessionSelection]);

  const handleCreateOverviewSession = useCallback(async (targetProjectId: string) => {
    const session = await createDefaultConversation(targetProjectId);
    const { completion, requestId } = startSessionSelection(
      targetProjectId,
      session.session_id,
      "create",
    );
    try {
      const didSelect = await onSelectProject(targetProjectId, {
        refreshConversations: true,
        sessionId: session.session_id,
      });
      if (didSelect === false) {
        cancelProjectSelection(requestId);
        return;
      }
      markProjectReady(requestId);
      await completion;
    } catch (error) {
      failProjectSelection(requestId, error);
    }
  }, [cancelProjectSelection, failProjectSelection, markProjectReady, onSelectProject, startSessionSelection]);

  const visibleChatSession = visibleConversationSelection(selectionState) ?? (
    projectId ? { projectId, sessionId: selectedSessionId } : null
  );
  const chatSessionSelectionRequest: ChatPanelSessionSelectionRequest | null =
    selectionState.status === "selecting"
      ? {
          messageId: selectionState.request.target.messageId,
          projectId: selectionState.request.target.projectId,
          requestId: selectionState.request.requestId,
          sessionId: selectionState.request.target.sessionId,
        }
      : null;

  return {
    chatSessionSelectionRequest,
    handleChatActiveSessionChange,
    handleChatSessionSelectionResult,
    handleCreateOverviewSession,
    handleEnterOverviewSession,
    handleSelectOverviewSession,
    sessionSelectionError: selectionState.status === "failed"
      ? selectionState.failure.message
      : null,
    visibleChatSession,
  };
}
