import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectOverviewItem } from "../../../entities/project/model/project";
import { listenProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { getProjectOverview } from "../../../services/project/getProjectOverview";
import {
  buildOverviewSessionKey,
  chatUsageToProjectOverviewUsage,
  type LiveUsageBySessionKey,
} from "./projectOverviewUsage";

type ProjectConversationOverviewState = "loading" | "ready" | "error";

const EVENT_REFRESH_DELAY_MS = 180;
const RUNNING_SESSION_POLL_INTERVAL_MS = 10000;

export function useProjectConversationOverview(
  projectId: string | null,
  isActive: boolean,
) {
  const [error, setError] = useState<string | null>(null);
  const [liveUsageBySessionKey, setLiveUsageBySessionKey] =
    useState<LiveUsageBySessionKey>({});
  const [overview, setOverview] = useState<ProjectOverviewItem | null>(null);
  const [state, setState] = useState<ProjectConversationOverviewState>("loading");
  const abortControllerRef = useRef<AbortController | null>(null);
  const loadRunIdRef = useRef(0);
  const overviewRef = useRef<ProjectOverviewItem | null>(null);

  const loadOverview = useCallback(async () => {
    abortControllerRef.current?.abort();
    if (!projectId || !isActive) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const runId = loadRunIdRef.current + 1;
    loadRunIdRef.current = runId;
    const hasCurrentOverview =
      overviewRef.current?.project.project_id === projectId;
    if (!hasCurrentOverview) {
      overviewRef.current = null;
      setOverview(null);
    }
    setError(null);
    setState(hasCurrentOverview ? "ready" : "loading");

    try {
      const response = await getProjectOverview(projectId, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || loadRunIdRef.current !== runId) return;
      overviewRef.current = response;
      setOverview(response);
      setState("ready");
    } catch (loadError) {
      if (
        controller.signal.aborted
        || loadRunIdRef.current !== runId
        || isAbortError(loadError)
      ) {
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "项目会话总览加载失败。");
      setState(overviewRef.current ? "ready" : "error");
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }, [isActive, projectId]);

  useEffect(() => {
    if (!projectId) {
      overviewRef.current = null;
      setOverview(null);
      setLiveUsageBySessionKey({});
      setState("loading");
      return;
    }
    if (!isActive) return;
    if (overviewRef.current?.project.project_id !== projectId) {
      setLiveUsageBySessionKey({});
    }
    void loadOverview();
  }, [isActive, loadOverview, projectId]);

  useEffect(() => {
    if (!projectId || !isActive) return undefined;
    let disposed = false;
    let dirty = false;
    let running = false;
    let timer: number | null = null;
    const runRefresh = async () => {
      timer = null;
      if (disposed) return;
      if (abortControllerRef.current || running) {
        dirty = true;
        timer = window.setTimeout(runRefresh, EVENT_REFRESH_DELAY_MS);
        return;
      }
      dirty = false;
      running = true;
      try {
        await loadOverview();
      } finally {
        running = false;
        if (dirty && !disposed && timer === null) {
          timer = window.setTimeout(runRefresh, EVENT_REFRESH_DELAY_MS);
        }
      }
    };
    const scheduleRefresh = () => {
      dirty = true;
      if (timer !== null || running) return;
      timer = window.setTimeout(runRefresh, EVENT_REFRESH_DELAY_MS);
    };
    const stopListening = listenProjectConversationUpdated((detail) => {
      if (detail.projectId !== projectId) return;
      const hasLiveUsage = Boolean(detail.usage && detail.sessionId);
      if (detail.usage && detail.sessionId) {
        const key = buildOverviewSessionKey(projectId, detail.sessionId);
        setLiveUsageBySessionKey((current) => ({
          ...current,
          [key]: chatUsageToProjectOverviewUsage(detail.usage!),
        }));
      }
      if (
        detail.runtimeStatus
        && detail.runtimeStatus !== "running"
        && detail.sessionId
      ) {
        const key = buildOverviewSessionKey(projectId, detail.sessionId);
        setLiveUsageBySessionKey((current) => {
          if (!current[key]) return current;
          const next = { ...current };
          delete next[key];
          return next;
        });
      }
      if (!hasLiveUsage || detail.runtimeStatus) {
        scheduleRefresh();
      }
    });
    return () => {
      disposed = true;
      stopListening();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [isActive, loadOverview, projectId]);

  useEffect(() => {
    if (!isActive || !overview || overview.active_count === 0) return undefined;
    const timer = window.setInterval(() => {
      void loadOverview();
    }, RUNNING_SESSION_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isActive, loadOverview, overview]);

  useEffect(() => () => {
    abortControllerRef.current?.abort();
  }, []);

  const updateActiveSession = useCallback((sessionId: string) => {
    setOverview((current) => {
      if (!current) return current;
      const next = { ...current, active_session_id: sessionId };
      overviewRef.current = next;
      return next;
    });
  }, []);

  return {
    error,
    liveUsageBySessionKey,
    loadOverview,
    overview: overview?.project.project_id === projectId ? overview : null,
    state,
    updateActiveSession,
  };
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
