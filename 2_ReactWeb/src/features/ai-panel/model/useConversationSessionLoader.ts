import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  initialConversationSessionLoadState,
  reduceConversationSessionLoad,
} from "./conversationSessionLoadMachine";

type ConversationSessionLoadResult = {
  message?: string;
  status: "applied" | "failed" | "ignored";
};

type UseConversationSessionLoaderOptions = {
  hasProjectSnapshot: (projectId: string) => boolean;
  isActive?: boolean;
  loadSessions: (projectId: string) => Promise<ConversationSessionLoadResult>;
  projectId: string | null;
};

export function useConversationSessionLoader({
  hasProjectSnapshot,
  isActive = true,
  loadSessions,
  projectId,
}: UseConversationSessionLoaderOptions) {
  const [loadState, dispatchLoad] = useReducer(
    reduceConversationSessionLoad,
    initialConversationSessionLoadState,
  );
  const [retryKey, setRetryKey] = useState(0);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!isActive || !projectId) {
      dispatchLoad({ type: "clear" });
      return undefined;
    }
    const requestedProjectId = projectId;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const hasSnapshot = hasProjectSnapshot(requestedProjectId);
    dispatchLoad({
      type: "begin",
      hasSnapshot,
      projectId: requestedProjectId,
      requestId,
    });

    let disposed = false;

    const load = async () => {
      const result = await loadSessions(requestedProjectId);
      if (disposed || requestIdRef.current !== requestId) return;
      if (result.status === "failed") {
        dispatchLoad({
          type: "failed",
          hasSnapshot,
          message: result.message ?? "会话载入失败，请重试。",
          projectId: requestedProjectId,
          requestId,
        });
        return;
      }
      dispatchLoad({ type: "ready", projectId: requestedProjectId, requestId });
    };

    void load().catch((error) => {
      if (disposed || requestIdRef.current !== requestId) return;
      dispatchLoad({
        type: "failed",
        hasSnapshot,
        message: error instanceof Error ? error.message : "会话载入失败，请重试。",
        projectId: requestedProjectId,
        requestId,
      });
    });

    return () => {
      disposed = true;
    };
  }, [
    hasProjectSnapshot,
    isActive,
    loadSessions,
    projectId,
    retryKey,
  ]);

  const retryLoadSessions = useCallback(() => {
    setRetryKey((current) => current + 1);
  }, []);

  return {
    isLoadingSessions: Boolean(
      projectId && (loadState.projectId !== projectId || loadState.status === "loading"),
    ),
    retryLoadSessions,
    sessionLoadError:
      projectId && loadState.projectId === projectId && loadState.status === "error"
        ? loadState.message
        : null,
  };
}
