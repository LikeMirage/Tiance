import { useCallback, useMemo, useRef } from "react";
import type { MutableRefObject } from "react";

import type { ConversationRuntimeStatus } from "../../../entities/llm-chat/model/conversation";
import type { ChatClientCapability } from "../../../entities/llm-chat/model/chatCompletion";
import {
  createClientToolRegistry,
  type ClientToolRegistry,
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
  reloadSessionsForSelection,
  setSessionRuntimeStatus,
}: UseChatPanelClientToolRegistryInput) {
  const backgroundConversationRuns = getConversationBackgroundRunRegistry();
  const combinedClientToolExecutorRef = useRef<ClientToolExecutor | null>(null);
  const combinedClientToolCapabilitiesRef = useRef<readonly ChatClientCapability[]>([]);
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

  const clientToolRegistry: ClientToolRegistry = useMemo(() => createClientToolRegistry([
    ...clientToolRegistrations,
    createConversationManagementClientToolRegistration({
      showSession,
    }),
    createConversationInteractionClientToolRegistration({
      backgroundRuns: backgroundConversationRuns,
      getClientToolExecutor: () => combinedClientToolExecutorRef.current,
      getClientCapabilities: () => combinedClientToolCapabilitiesRef.current,
      onSessionRuntimeStatusChanged: setSessionRuntimeStatus,
    }),
  ]), [
    activeProjectIdRef,
    backgroundConversationRuns,
    clientToolRegistrations,
    setSessionRuntimeStatus,
    showSession,
  ]);
  combinedClientToolExecutorRef.current = clientToolRegistry.execute;
  combinedClientToolCapabilitiesRef.current = clientToolRegistry.capabilities;

  return {
    backgroundConversationRuns,
    clientToolCapabilities: clientToolRegistry.capabilities,
    clientToolExecutor: clientToolRegistry.execute,
  };
}
