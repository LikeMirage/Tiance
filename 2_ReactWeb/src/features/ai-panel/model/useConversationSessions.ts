import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import type {
  ConversationBranchNode,
  ConversationForkResponse,
  ConversationMessageVariant,
  ConversationRuntimeStatus,
  ConversationSession,
  ConversationSessionState,
  ConversationSessionListResponse,
} from "../../../entities/llm-chat/model/conversation";
import { dispatchProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { getProjectConversations } from "../../../services/project/getProjectConversations";
import { isNotFoundRequestError } from "./chatPanelRequestErrors";
import { getCachedProjectEntryWarmup } from "../../project-entry/model/projectEntryWarmup";
import { buildSessionKey } from "./sessionKey";
import { emptyConversationDraftReferences } from "./conversationDraftReferences";
import { mergeStreamingRuntimeStatuses } from "./conversationRuntimeState";
import {
  useConversationStatePersistence,
  type ConversationDraftRequestSnapshot,
  type ConversationSessionStatePatch as SessionStatePatch,
} from "./useConversationStatePersistence";
import { useConversationSessionLoader } from "./useConversationSessionLoader";

const SESSION_LIST_LOAD_TIMEOUT_MS = 12_000;

type ConversationProjectSessionSnapshot = {
  activeSessionId: string | null;
  draft: string;
  sessionStates: Record<string, ConversationSessionState>;
  sessions: ConversationSession[];
  branchNodes: ConversationBranchNode[];
  messageVariants: ConversationMessageVariant[];
};

export type ConversationSessionsReloadResult = {
  activeSessionId: string | null;
  message?: string;
  sessionIds: ReadonlySet<string>;
  status: "applied" | "failed" | "ignored";
};

export type SettledConversationDraft = {
  draft: string;
  projectId: string;
  sessionId: string;
  version: number;
};

type UseConversationSessionsInput = {
  abortProjectStreams: (projectId: string) => void;
  activeProjectIdRef: MutableRefObject<string | null>;
  activeSessionIdRef: MutableRefObject<string | null>;
  isActive?: boolean;
  preferredSessionId?: string | null;
  projectId: string | null;
  showChatView: () => void;
};

export function useConversationSessions({
  abortProjectStreams,
  activeProjectIdRef,
  activeSessionIdRef,
  isActive = true,
  preferredSessionId = null,
  projectId,
  showChatView,
}: UseConversationSessionsInput) {
  const [sessions, setSessions] = useState<ConversationSession[]>([]);
  const [branchNodes, setBranchNodes] = useState<ConversationBranchNode[]>([]);
  const [messageVariants, setMessageVariants] = useState<ConversationMessageVariant[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const [sessionStates, setSessionStates] = useState<Record<string, ConversationSessionState>>({});
  const [draft, setDraft] = useState("");
  const [settledDraft, setSettledDraft] = useState<SettledConversationDraft | null>(null);
  const [streamingSessionKeys, setStreamingSessionKeys] = useState<Set<string>>(() => new Set());
  const streamingSessionKeysRef = useRef(streamingSessionKeys);
  streamingSessionKeysRef.current = streamingSessionKeys;
  const latestDraftRef = useRef({ projectId, activeSessionId, draft });
  const projectSessionSnapshotsRef = useRef(new Map<string, ConversationProjectSessionSnapshot>());
  const reloadSessionsRequestIdsRef = useRef(new Map<string, number>());
  const reloadSessionsInFlightRef = useRef(
    new Map<string, Promise<ConversationSessionsReloadResult>>(),
  );
  const settledDraftVersionRef = useRef(0);
  const unavailableProjectIdRef = useRef<string | null>(null);
  const {
    clearProjectDrafts,
    mergeProtectedDrafts,
    persistSessionState,
    releaseDraftRequest,
    rememberPendingDraft,
    saveConversationState,
    snapshotDraftRequest,
  } = useConversationStatePersistence({
    unavailableProjectIdRef,
  });

  activeProjectIdRef.current = projectId;
  if (loadedProjectId) {
    projectSessionSnapshotsRef.current.set(loadedProjectId, {
      activeSessionId,
      draft,
      sessionStates,
      sessions,
      branchNodes,
      messageVariants,
    });
  }
  // projectId 会先于会话状态切换；未对齐时不能暴露“新项目 + 旧会话”的混合快照。
  const isCurrentProjectLoaded = loadedProjectId === projectId;
  const presentedActiveSessionId = isCurrentProjectLoaded ? activeSessionId : null;
  const presentedDraft = isCurrentProjectLoaded ? draft : "";
  const presentedSessionStates = isCurrentProjectLoaded ? sessionStates : {};
  const presentedSessions = isCurrentProjectLoaded ? sessions : [];
  const presentedBranchNodes = isCurrentProjectLoaded ? branchNodes : [];
  const presentedMessageVariants = isCurrentProjectLoaded ? messageVariants : [];
  const presentedSettledDraft = isCurrentProjectLoaded && settledDraft?.projectId === projectId
    ? settledDraft
    : null;
  const hasRunningSession = isCurrentProjectLoaded && Object.values(sessionStates).some(
    (state) => state.runtime_status === "running",
  );
  activeSessionIdRef.current = presentedActiveSessionId;
  if (isCurrentProjectLoaded) {
    latestDraftRef.current = {
      activeSessionId,
      draft,
      projectId,
    };
  }

  const markSessionStreaming = useCallback((sessionKey: string) => {
    if (streamingSessionKeysRef.current.has(sessionKey)) return;
    const next = new Set(streamingSessionKeysRef.current);
    next.add(sessionKey);
    streamingSessionKeysRef.current = next;
    setStreamingSessionKeys(next);
  }, []);

  const unmarkSessionStreaming = useCallback((sessionKey: string) => {
    if (!streamingSessionKeysRef.current.has(sessionKey)) return;
    const next = new Set(streamingSessionKeysRef.current);
    next.delete(sessionKey);
    streamingSessionKeysRef.current = next;
    setStreamingSessionKeys(next);
  }, []);

  const isSessionStreaming = useCallback(
    (sessionKey: string) => streamingSessionKeysRef.current.has(sessionKey),
    [],
  );

  const clearProjectStreamingSessions = useCallback((pid: string) => {
    const prefix = `${pid}:`;
    const next = new Set(
      [...streamingSessionKeysRef.current].filter((key) => !key.startsWith(prefix)),
    );
    if (next.size === streamingSessionKeysRef.current.size) return;
    streamingSessionKeysRef.current = next;
    setStreamingSessionKeys(next);
  }, []);

  useEffect(() => {
    if (projectId !== unavailableProjectIdRef.current) {
      unavailableProjectIdRef.current = null;
    }
  }, [projectId]);

  const resetConversationState = useCallback(() => {
    setLoadedProjectId(null);
    setSessions([]);
    setBranchNodes([]);
    setMessageVariants([]);
    setActiveSessionId(null);
    activeSessionIdRef.current = null;
    setSessionStates({});
    setSettledDraft(null);
    setDraft("");
  }, []);

  const markConversationProjectUnavailable = useCallback((pid: string) => {
    unavailableProjectIdRef.current = pid;
    projectSessionSnapshotsRef.current.delete(pid);
    clearProjectDrafts(pid);
    if (activeProjectIdRef.current === pid) {
      abortProjectStreams(pid);
      resetConversationState();
      clearProjectStreamingSessions(pid);
    }
  }, [
    abortProjectStreams,
    clearProjectDrafts,
    clearProjectStreamingSessions,
    resetConversationState,
  ]);

  const publishSettledDraft = useCallback((pid: string, sessionId: string, nextDraft: string) => {
    settledDraftVersionRef.current += 1;
    setSettledDraft({
      draft: nextDraft,
      projectId: pid,
      sessionId,
      version: settledDraftVersionRef.current,
    });
  }, []);

  const publishCurrentDraftSnapshot = useCallback((pid: string, sessionId: string) => {
    const current = latestDraftRef.current;
    if (current.projectId !== pid || current.activeSessionId !== sessionId) {
      return;
    }
    publishSettledDraft(pid, sessionId, current.draft);
  }, [publishSettledDraft]);

  const updateSessionStateLocally = useCallback((
    pid: string,
    sessionId: string,
    patch: SessionStatePatch,
  ) => {
    if (activeProjectIdRef.current === pid) {
      setSessionStates((previousStates) => ({
        ...previousStates,
        [sessionId]: mergeSessionStatePatch(previousStates[sessionId], patch),
      }));
    }

    const snapshot = projectSessionSnapshotsRef.current.get(pid);
    if (snapshot) {
      projectSessionSnapshotsRef.current.set(pid, {
        ...snapshot,
        draft: patch.draft !== undefined && snapshot.activeSessionId === sessionId
          ? patch.draft
          : snapshot.draft,
        sessionStates: {
          ...snapshot.sessionStates,
          [sessionId]: mergeSessionStatePatch(snapshot.sessionStates[sessionId], patch),
        },
      });
    }

    if (patch.runtime_status) {
      dispatchProjectConversationUpdated({
        kind: "runtime",
        projectId: pid,
        runtimeStatus: patch.runtime_status,
        sessionId,
      });
    }
  }, [activeProjectIdRef]);

  const saveSessionState = useCallback((
    pid: string,
    sessionId: string,
    patch: SessionStatePatch,
  ) => {
    updateSessionStateLocally(pid, sessionId, patch);
    if (patch.draft !== undefined) {
      publishSettledDraft(pid, sessionId, patch.draft);
    }
    persistSessionState(pid, sessionId, patch);
  }, [persistSessionState, publishSettledDraft, updateSessionStateLocally]);

  const setSessionRuntimeStatus = useCallback((
    pid: string,
    sessionId: string,
    runtimeStatus: ConversationRuntimeStatus,
  ) => {
    // 后端任务是运行状态的持久化来源；前端这里只同步当前呈现和项目快照。
    updateSessionStateLocally(pid, sessionId, {
      runtime_status: runtimeStatus,
    });
  }, [updateSessionStateLocally]);

  const activateSession = useCallback((sessionId: string) => {
    if (!projectId) return;
    const current = latestDraftRef.current;
    if (current.projectId && current.activeSessionId) {
      saveSessionState(current.projectId, current.activeSessionId, { draft: current.draft });
    }
    setActiveSessionId(sessionId);
    activeSessionIdRef.current = sessionId;
    setDraft(sessionStates[sessionId]?.draft ?? "");
    showChatView();
    dispatchProjectConversationUpdated({
      kind: "selection",
      projectId,
      sessionId,
    });
    void saveConversationState(projectId, { active_session_id: sessionId }).catch(() => undefined);
  }, [projectId, saveConversationState, saveSessionState, sessionStates, showChatView]);

  const applyProjectSnapshot = useCallback((
    pid: string,
    snapshot: ConversationProjectSessionSnapshot,
  ) => {
    const sessionIds = new Set(snapshot.sessions.map((session) => session.session_id));
    const restoredSessionId = preferredSessionId && sessionIds.has(preferredSessionId)
      ? preferredSessionId
      : snapshot.activeSessionId && sessionIds.has(snapshot.activeSessionId)
        ? snapshot.activeSessionId
        : snapshot.sessions[0]?.session_id ?? null;
    setLoadedProjectId(pid);
    setSessions(snapshot.sessions);
    setBranchNodes(snapshot.branchNodes);
    setMessageVariants(snapshot.messageVariants);
    setSessionStates(snapshot.sessionStates);
    setActiveSessionId(restoredSessionId);
    activeSessionIdRef.current = restoredSessionId;
    setDraft(restoredSessionId ? snapshot.sessionStates[restoredSessionId]?.draft ?? "" : "");
  }, [activeSessionIdRef, preferredSessionId]);

  const applySessionsResponse = useCallback((
    response: ConversationSessionListResponse,
    draftRequestSnapshot?: ConversationDraftRequestSnapshot,
  ) => {
    const sessionIds = new Set(response.items.map((session) => session.session_id));
    const preferredRestoredSessionId =
      preferredSessionId && sessionIds.has(preferredSessionId) ? preferredSessionId : null;
    const restoredSessionId = preferredRestoredSessionId ??
      (response.active_session_id && sessionIds.has(response.active_session_id)
      ? response.active_session_id
      : response.items[0]?.session_id ?? null);
    const responseSessionStates = mergeProtectedDrafts(
      response.project_id,
      response.session_states,
      draftRequestSnapshot,
    );
    projectSessionSnapshotsRef.current.set(response.project_id, {
      activeSessionId: restoredSessionId,
      draft: restoredSessionId ? responseSessionStates[restoredSessionId]?.draft ?? "" : "",
      sessionStates: responseSessionStates,
      sessions: response.items,
      branchNodes: response.branch_nodes ?? [],
      messageVariants: response.message_variants ?? [],
    });
    setLoadedProjectId(response.project_id);
    setSessions(response.items);
    setBranchNodes(response.branch_nodes ?? []);
    setMessageVariants(response.message_variants ?? []);
    setSessionStates(responseSessionStates);
    setActiveSessionId(restoredSessionId);
    activeSessionIdRef.current = restoredSessionId;
    setDraft(restoredSessionId ? responseSessionStates[restoredSessionId]?.draft ?? "" : "");
  }, [activeSessionIdRef, mergeProtectedDrafts, preferredSessionId]);

  useLayoutEffect(() => {
    if (!projectId) {
      resetConversationState();
      return;
    }
    if (loadedProjectId === projectId) {
      return;
    }

    const localSnapshot = projectSessionSnapshotsRef.current.get(projectId);
    if (localSnapshot) {
      applyProjectSnapshot(projectId, localSnapshot);
      return;
    }

    const cachedResponse = getCachedProjectEntryWarmup(projectId)?.conversations;
    if (cachedResponse && isUsableCachedConversationList(projectId, cachedResponse)) {
      if (unavailableProjectIdRef.current === projectId) {
        unavailableProjectIdRef.current = null;
      }
      applySessionsResponse(cachedResponse);
      return;
    }

    setLoadedProjectId(null);
    setSessions([]);
    setBranchNodes([]);
    setMessageVariants([]);
    setActiveSessionId(null);
    activeSessionIdRef.current = null;
    setSessionStates({});
    setSettledDraft(null);
    setDraft("");
  }, [
    activeSessionIdRef,
    applyProjectSnapshot,
    applySessionsResponse,
    loadedProjectId,
    projectId,
    resetConversationState,
  ]);

  const performReloadSessions = useCallback(async (
    pid: string,
  ): Promise<ConversationSessionsReloadResult> => {
    const requestId = (reloadSessionsRequestIdsRef.current.get(pid) ?? 0) + 1;
    reloadSessionsRequestIdsRef.current.set(pid, requestId);
    const draftRequestSnapshot = snapshotDraftRequest(pid);
    try {
      const response = await getProjectConversationsWithTimeout(pid);
      if (reloadSessionsRequestIdsRef.current.get(pid) !== requestId) {
        return {
          activeSessionId: null,
          sessionIds: new Set<string>(),
          status: "ignored",
        };
      }
      if (unavailableProjectIdRef.current === pid) {
        unavailableProjectIdRef.current = null;
      }
      const sessionIds = new Set(response.items.map((session) => session.session_id));
      const nextActiveSessionId = response.active_session_id && sessionIds.has(response.active_session_id)
        ? response.active_session_id
        : response.items[0]?.session_id ?? null;
      const responseSessionStates = mergeProtectedDrafts(
        pid,
        response.session_states,
        draftRequestSnapshot,
      );

      if (activeProjectIdRef.current !== pid) {
        const previousSnapshot = projectSessionSnapshotsRef.current.get(pid);
        const snapshotSessionStates = mergeStreamingRuntimeStatuses(
          pid,
          responseSessionStates,
          previousSnapshot?.sessionStates ?? {},
          streamingSessionKeysRef.current,
        );
        const snapshotActiveSessionId = previousSnapshot?.activeSessionId &&
          sessionIds.has(previousSnapshot.activeSessionId)
          ? previousSnapshot.activeSessionId
          : nextActiveSessionId;
        projectSessionSnapshotsRef.current.set(pid, {
          activeSessionId: snapshotActiveSessionId,
          draft: snapshotActiveSessionId
            ? snapshotSessionStates[snapshotActiveSessionId]?.draft ?? ""
            : "",
          sessionStates: snapshotSessionStates,
          sessions: response.items,
          branchNodes: response.branch_nodes ?? [],
          messageVariants: response.message_variants ?? [],
        });
        return {
          activeSessionId: snapshotActiveSessionId,
          sessionIds,
          status: "ignored",
        };
      }

      const previousActiveSessionId = activeSessionIdRef.current;
      const resolvedActiveSessionId =
        previousActiveSessionId && sessionIds.has(previousActiveSessionId)
          ? previousActiveSessionId
          : nextActiveSessionId;
      setSessions(response.items);
      setBranchNodes(response.branch_nodes ?? []);
      setMessageVariants(response.message_variants ?? []);
      setLoadedProjectId(response.project_id);
      setSessionStates((prev) => {
        const nextStates = mergeStreamingRuntimeStatuses(
          pid,
          responseSessionStates,
          prev,
          streamingSessionKeysRef.current,
        );
        if (
          !previousActiveSessionId ||
          !sessionIds.has(previousActiveSessionId) ||
          !prev[previousActiveSessionId]
        ) {
          return nextStates;
        }
        const previousState = prev[previousActiveSessionId];
        const responseState = nextStates[previousActiveSessionId] ?? {
          draft: "",
          references: emptyConversationDraftReferences(),
          runtime_status: previousState.runtime_status,
          updated_at: previousState.updated_at,
        };
        const shouldKeepLocalRuntimeStatus =
          streamingSessionKeysRef.current.has(buildSessionKey(pid, previousActiveSessionId));
        return {
          ...nextStates,
          [previousActiveSessionId]: {
            ...responseState,
            references: previousState.references ?? responseState.references,
            runtime_status: shouldKeepLocalRuntimeStatus
              ? previousState.runtime_status
              : responseState.runtime_status,
            draft: latestDraftRef.current.draft,
            updated_at: responseState.updated_at,
          },
        };
      });
      setActiveSessionId((current) =>
        current && sessionIds.has(current) ? current : nextActiveSessionId,
      );
      activeSessionIdRef.current = resolvedActiveSessionId;
      setDraft((currentDraft) =>
        resolvedActiveSessionId
          ? resolvedActiveSessionId === previousActiveSessionId
            ? currentDraft
            : responseSessionStates[resolvedActiveSessionId]?.draft ?? ""
          : "",
      );
      return {
        activeSessionId: resolvedActiveSessionId,
        sessionIds,
        status: "applied",
      };
    } catch (error) {
      if (
        activeProjectIdRef.current !== pid ||
        reloadSessionsRequestIdsRef.current.get(pid) !== requestId
      ) {
        return {
          activeSessionId: null,
          sessionIds: new Set<string>(),
          status: "ignored",
        };
      }
      if (isNotFoundRequestError(error)) {
        markConversationProjectUnavailable(pid);
      }
      return {
        activeSessionId: activeSessionIdRef.current,
        message: error instanceof Error ? error.message : "会话列表刷新失败。",
        sessionIds: new Set<string>(),
        status: "failed",
      };
    } finally {
      releaseDraftRequest(pid, draftRequestSnapshot);
    }
  }, [
    markConversationProjectUnavailable,
    mergeProtectedDrafts,
    releaseDraftRequest,
    snapshotDraftRequest,
  ]);

  const reloadSessionsForSelection = useCallback((pid: string) => {
    const existing = reloadSessionsInFlightRef.current.get(pid);
    if (existing) return existing;
    const request = performReloadSessions(pid);
    reloadSessionsInFlightRef.current.set(pid, request);
    void request.finally(() => {
      if (reloadSessionsInFlightRef.current.get(pid) === request) {
        reloadSessionsInFlightRef.current.delete(pid);
      }
    });
    return request;
  }, [performReloadSessions]);

  const reloadSessions = useCallback(async (pid: string) => {
    await reloadSessionsForSelection(pid);
  }, [reloadSessionsForSelection]);

  const hasProjectSnapshot = useCallback(
    (pid: string) => projectSessionSnapshotsRef.current.has(pid),
    [],
  );
  const {
    isLoadingSessions,
    retryLoadSessions,
    sessionLoadError,
  } = useConversationSessionLoader({
    hasProjectSnapshot,
    isActive,
    loadSessions: reloadSessionsForSelection,
    projectId,
  });

  useEffect(() => {
    if (!isCurrentProjectLoaded || !projectId || !activeSessionId) return;
    rememberPendingDraft(projectId, activeSessionId, draft);
    setSessionStates((prev) => ({
      ...prev,
      [activeSessionId]: {
        runtime_status: prev[activeSessionId]?.runtime_status ?? "idle",
        draft,
        references: prev[activeSessionId]?.references ?? emptyConversationDraftReferences(),
        updated_at: new Date().toISOString(),
      },
    }));
    const timer = window.setTimeout(() => {
      const current = latestDraftRef.current;
      if (
        current.projectId !== projectId ||
        current.activeSessionId !== activeSessionId ||
        current.draft !== draft
      ) {
        return;
      }
      persistSessionState(projectId, activeSessionId, { draft });
      publishSettledDraft(projectId, activeSessionId, draft);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [
    activeSessionId,
    draft,
    isCurrentProjectLoaded,
    persistSessionState,
    projectId,
    publishSettledDraft,
    rememberPendingDraft,
  ]);

  useEffect(() => {
    if (!isCurrentProjectLoaded || !projectId || !activeSessionId) return;
    return () => {
      const current = latestDraftRef.current;
      if (current.projectId === projectId && current.activeSessionId === activeSessionId) {
        persistSessionState(projectId, activeSessionId, { draft: current.draft });
      }
    };
  }, [activeSessionId, isCurrentProjectLoaded, persistSessionState, projectId]);

  useEffect(() => {
    if (!isActive || !isCurrentProjectLoaded || !projectId || !hasRunningSession) return undefined;
    const timer = window.setInterval(() => {
      void reloadSessions(projectId);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [hasRunningSession, isActive, isCurrentProjectLoaded, projectId, reloadSessions]);

  const applyForkResult = useCallback((response: ConversationForkResponse) => {
    if (!projectId) return;
    setSessions((previous) => [
      response.session,
      ...previous.filter((session) => session.session_id !== response.session.session_id),
    ]);
    setBranchNodes(response.branch_nodes);
    setMessageVariants(response.message_variants);
    setSessionStates((previous) => ({
      ...previous,
      [response.session.session_id]: response.state,
    }));
    setActiveSessionId(response.session.session_id);
    activeSessionIdRef.current = response.session.session_id;
    setDraft(response.state.draft);
    showChatView();
    dispatchProjectConversationUpdated({
      kind: "structure",
      projectId,
      sessionId: response.session.session_id,
    });
  }, [activeSessionIdRef, projectId, showChatView]);

  return {
    activateSession,
    applyForkResult,
    activeProjectIdRef,
    activeSessionId: presentedActiveSessionId,
    activeSessionIdRef,
    branchNodes: presentedBranchNodes,
    draft: presentedDraft,
    isLoadingSessions,
    isSessionStreaming,
    markConversationProjectUnavailable,
    markSessionStreaming,
    publishCurrentDraftSnapshot,
    reloadSessions,
    reloadSessionsForSelection,
    retryLoadSessions,
    saveConversationState,
    saveSessionState,
    settledDraft: presentedSettledDraft,
    sessionStates: presentedSessionStates,
    sessionLoadError,
    sessions: presentedSessions,
    messageVariants: presentedMessageVariants,
    setActiveSessionId,
    setDraft,
    setSessionStates,
    setSessions,
    setSessionRuntimeStatus,
    streamingSessionKeys,
    unmarkSessionStreaming,
    unavailableProjectIdRef,
  };
}

function mergeSessionStatePatch(
  previous: ConversationSessionState | undefined,
  patch: SessionStatePatch,
): ConversationSessionState {
  return {
    runtime_status: patch.runtime_status ?? previous?.runtime_status ?? "idle",
    draft: patch.draft ?? previous?.draft ?? "",
    references: patch.references ?? previous?.references ?? emptyConversationDraftReferences(),
    updated_at: new Date().toISOString(),
  };
}

function isUsableCachedConversationList(
  projectId: string,
  response: ConversationSessionListResponse,
) {
  return response.project_id === projectId && response.items.length > 0;
}

async function getProjectConversationsWithTimeout(projectId: string) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SESSION_LIST_LOAD_TIMEOUT_MS);
  try {
    return await getProjectConversations(projectId, controller.signal);
  } catch (error) {
    if (timedOut) {
      throw new Error("会话列表刷新超时，请重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
