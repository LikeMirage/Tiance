import { useEffect, useRef } from "react";

import type {
  ChatClientCapability,
} from "../../../entities/llm-chat/model/chatCompletion";
import type {
  ConversationBranchNode,
  ConversationRuntimeStatus,
  ConversationSession,
  ConversationSessionState,
} from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { settleAutomaticConversationNaming } from "../../../services/project/settleAutomaticConversationNaming";
import { buildSessionKey } from "../../ai-panel/model/sessionKey";
import type { SessionStreamingLease } from "../../ai-panel/model/sessionStreamingRegistry";
import type { ClientToolExecutor } from "./clientToolBridge";
import type { ConversationBackgroundRunRegistry } from "./conversationBackgroundRun";

type AutomaticNamingConversationRunsOptions = {
  backgroundRuns: ConversationBackgroundRunRegistry;
  branchNodes: ConversationBranchNode[];
  clientToolExecutor: ClientToolExecutor | null;
  clientToolCapabilities: readonly ChatClientCapability[];
  markSessionStreaming: (sessionKey: string) => SessionStreamingLease;
  projectId: string | null;
  reloadSessions: (projectId: string) => Promise<void>;
  saveSessionState: (
    projectId: string,
    sessionId: string,
    patch: { draft?: string; runtime_status?: ConversationRuntimeStatus },
  ) => void;
  sessionStates: Record<string, ConversationSessionState>;
  sessions: ConversationSession[];
  setSessionRuntimeStatus: (
    projectId: string,
    sessionId: string,
    status: ConversationRuntimeStatus,
  ) => void;
  unmarkSessionStreaming: (sessionKey: string, lease: SessionStreamingLease) => void;
};

export function useAutomaticNamingConversationRuns({
  backgroundRuns,
  branchNodes,
  clientToolExecutor,
  clientToolCapabilities,
  markSessionStreaming,
  projectId,
  reloadSessions,
  saveSessionState,
  sessionStates,
  sessions,
  setSessionRuntimeStatus,
  unmarkSessionStreaming,
}: AutomaticNamingConversationRunsOptions) {
  const claimedSessionIdsRef = useRef(new Set<string>());

  useEffect(() => {
    if (!projectId || !clientToolExecutor) return;
    const sessionById = new Map(
      sessions.map((session) => [session.session_id, session]),
    );
    for (const node of branchNodes) {
      if (
        node.deleted_at
        || node.relation_kind !== "functional"
        || node.function_type !== "automatic_naming"
        || node.created_by !== "system"
      ) {
        continue;
      }
      const session = sessionById.get(node.session_id);
      const state = sessionStates[node.session_id];
      const taskPrompt = state?.draft.trim() ?? "";
      if (
        !session
        || !taskPrompt
        || !["idle", "running"].includes(state?.runtime_status ?? "idle")
        || claimedSessionIdsRef.current.has(node.session_id)
        || backgroundRuns.hasActiveRun(projectId, node.session_id)
      ) {
        continue;
      }

      claimedSessionIdsRef.current.add(node.session_id);
      const sessionKey = buildSessionKey(projectId, node.session_id);
      let streamingLease: SessionStreamingLease | null = null;
      let run;
      try {
        run = backgroundRuns.startOrResume({
          clientToolExecutor: () => clientToolExecutor,
          clientCapabilities: () => clientToolCapabilities,
          initialStrategy: "resume_then_start",
          message: taskPrompt,
          projectId,
          session,
          userMessageId: `automatic_naming_${node.session_id}`,
          onStarted: () => {
            streamingLease = markSessionStreaming(sessionKey);
            saveSessionState(projectId, node.session_id, {
              draft: "",
              runtime_status: "running",
            });
            setSessionRuntimeStatus(projectId, node.session_id, "running");
            dispatchProjectConversationUpdated({
              kind: "content",
              projectId,
              sessionId: node.session_id,
            });
          },
          onSettled: async (outcome) => {
            try {
              await settleAutomaticConversationNaming(
                projectId,
                node.session_id,
                outcome ?? "error",
              );
            } finally {
              if (streamingLease) {
                unmarkSessionStreaming(sessionKey, streamingLease);
              }
              setSessionRuntimeStatus(
                projectId,
                node.session_id,
                outcome === "error" ? "error" : "idle",
              );
              dispatchProjectConversationUpdated({
                kind: "content",
                projectId,
                sessionId: node.session_id,
              });
              await reloadSessions(projectId);
            }
          },
        });
      } catch {
        claimedSessionIdsRef.current.delete(node.session_id);
        continue;
      }
      void run.completion.finally(() => {
        claimedSessionIdsRef.current.delete(node.session_id);
      }).catch(() => undefined);
    }
  }, [
    backgroundRuns,
    branchNodes,
    clientToolExecutor,
    clientToolCapabilities,
    markSessionStreaming,
    projectId,
    reloadSessions,
    saveSessionState,
    sessionStates,
    sessions,
    setSessionRuntimeStatus,
    unmarkSessionStreaming,
  ]);
}
