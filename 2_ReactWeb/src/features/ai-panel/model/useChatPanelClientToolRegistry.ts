import { useCallback, useMemo, useRef } from "react";
import type { MutableRefObject } from "react";

import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import {
  createClientToolRegistry,
  type ClientToolExecutor,
  type ClientToolRegistration,
} from "../../client-tools/model/clientToolBridge";
import { getConversationBackgroundRunRegistry } from "../../client-tools/model/conversationBackgroundRun";
import { createConversationInteractionClientToolRegistration } from "../../client-tools/model/conversationInteractionClientTool";
import { createConversationManagementClientToolRegistration } from "../../client-tools/model/conversationManagementClientTool";
import type { ConversationSessionsReloadResult } from "./useConversationSessions";

type UseChatPanelClientToolRegistryInput = {
  activateSession: (sessionId: string) => void;
  activeProjectIdRef: MutableRefObject<string | null>;
  clientToolRegistrations: readonly ClientToolRegistration[];
  reloadSessions: (projectId: string) => Promise<void>;
  reloadSessionsForSelection: (
    projectId: string,
  ) => Promise<ConversationSessionsReloadResult>;
  setSessionRuntimeStatus: (
    projectId: string,
    sessionId: string,
    runtimeStatus: ConversationRuntimeStatus,
  ) => void;
};

export function useChatPanelClientToolRegistry({
  activateSession,
  activeProjectIdRef,
  clientToolRegistrations,
  reloadSessions,
  reloadSessionsForSelection,
  setSessionRuntimeStatus,
}: UseChatPanelClientToolRegistryInput) {
  const backgroundConversationRuns = getConversationBackgroundRunRegistry();
  const combinedClientToolExecutorRef = useRef<ClientToolExecutor | null>(null);
  const showSession = useCallback(async (
    requestedProjectId: string,
    sessionId: string,
  ) => {
    if (requestedProjectId !== activeProjectIdRef.current) {
      throw new Error("只能在当前打开的项目中显示会话。");
    }
    const result = await reloadSessionsForSelection(requestedProjectId);
    if (result.status === "failed") {
      throw new Error(result.message ?? "会话列表刷新失败。");
    }
    if (!result.sessionIds.has(sessionId)) {
      throw new Error(`会话不存在：${sessionId}`);
    }
    activateSession(sessionId);
  }, [activateSession, activeProjectIdRef, reloadSessionsForSelection]);

  const clientToolExecutor = useMemo(() => createClientToolRegistry([
    ...clientToolRegistrations,
    createConversationManagementClientToolRegistration({
      getCurrentProjectId: () => activeProjectIdRef.current,
      onSessionsChanged: reloadSessions,
      showSession,
    }),
    createConversationInteractionClientToolRegistration({
      backgroundRuns: backgroundConversationRuns,
      getClientToolExecutor: () => combinedClientToolExecutorRef.current,
      getCurrentProjectId: () => activeProjectIdRef.current,
      onSessionsChanged: reloadSessions,
      onSessionRuntimeStatusChanged: setSessionRuntimeStatus,
    }),
  ]).execute, [
    activeProjectIdRef,
    backgroundConversationRuns,
    clientToolRegistrations,
    reloadSessions,
    setSessionRuntimeStatus,
    showSession,
  ]);
  combinedClientToolExecutorRef.current = clientToolExecutor;

  return { backgroundConversationRuns, clientToolExecutor };
}
