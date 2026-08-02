import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  Project,
  ProjectCategoryOverviewResponse,
} from "../../../entities/project/model/project";
import { listenProjectConversationUpdated } from "../../../entities/llm-chat/model/projectConversationEvents";
import { useI18n } from "../../../shared/i18n";
import { getProjectCategoryOverview } from "../../../services/project/getProjectCategoryOverview";
import { orderOverviewProjects } from "./projectOverviewOrdering";
import {
  buildOverviewSessionKey,
  chatUsageToProjectOverviewUsage,
  type LiveUsageBySessionKey,
} from "./projectOverviewUsage";

export type ProjectCategoryOverviewLoadState = "idle" | "loading" | "ready" | "error";

type LoadMode = "initial" | "refresh";

type UseProjectCategoryOverviewParams = {
  categoryId: string | null;
  isActive?: boolean;
  orderedProjects: Project[];
  refreshKey: string;
};

const EVENT_REFRESH_DELAY_MS = 180;
const RUNNING_SESSION_POLL_INTERVAL_MS = 10000;

export function useProjectCategoryOverview({
  categoryId,
  isActive = true,
  orderedProjects,
  refreshKey,
}: UseProjectCategoryOverviewParams) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const [liveUsageBySessionKey, setLiveUsageBySessionKey] = useState<LiveUsageBySessionKey>({});
  const [overview, setOverview] = useState<ProjectCategoryOverviewResponse | null>(null);
  const [state, setState] = useState<ProjectCategoryOverviewLoadState>("loading");
  const abortControllerRef = useRef<AbortController | null>(null);
  const loadRunIdRef = useRef(0);
  const overviewRef = useRef<ProjectCategoryOverviewResponse | null>(null);
  const previousCategoryIdRef = useRef<string | null>(null);
  const scheduledRefreshRef = useRef<number | null>(null);

  useEffect(() => {
    overviewRef.current = overview;
  }, [overview]);

  const clearScheduledRefresh = useCallback(() => {
    if (scheduledRefreshRef.current === null) return;
    window.clearTimeout(scheduledRefreshRef.current);
    scheduledRefreshRef.current = null;
  }, []);

  const loadOverview = useCallback(async (mode: LoadMode = "refresh") => {
    clearScheduledRefresh();
    abortControllerRef.current?.abort();

    if (!isActive) {
      return;
    }

    if (!categoryId) {
      loadRunIdRef.current += 1;
      setError(null);
      setLiveUsageBySessionKey({});
      setOverview(null);
      setState("idle");
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const runId = loadRunIdRef.current + 1;
    loadRunIdRef.current = runId;
    setError(null);
    setState(overviewRef.current && mode === "refresh" ? "ready" : "loading");

    try {
      const response = await getProjectCategoryOverview(categoryId, {
        signal: controller.signal,
      });
      if (loadRunIdRef.current !== runId || controller.signal.aborted) return;
      overviewRef.current = response;
      setOverview(response);
      setState("ready");
    } catch (loadError) {
      if (
        loadRunIdRef.current !== runId ||
        controller.signal.aborted ||
        isAbortError(loadError)
      ) {
        return;
      }
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("projectOverview.loadFailed"),
      );
      setState(overviewRef.current ? "ready" : "error");
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }, [categoryId, clearScheduledRefresh, isActive, t]);

  const scheduleRefresh = useCallback(() => {
    if (!categoryId || !isActive) return;
    clearScheduledRefresh();
    scheduledRefreshRef.current = window.setTimeout(() => {
      scheduledRefreshRef.current = null;
      void loadOverview("refresh");
    }, EVENT_REFRESH_DELAY_MS);
  }, [categoryId, clearScheduledRefresh, isActive, loadOverview]);

  useEffect(() => {
    if (!isActive) return;
    const mode =
      previousCategoryIdRef.current === categoryId && overviewRef.current
        ? "refresh"
        : "initial";
    if (previousCategoryIdRef.current !== categoryId) {
      setLiveUsageBySessionKey({});
    }
    previousCategoryIdRef.current = categoryId;
    void loadOverview(mode);
  }, [categoryId, isActive, loadOverview, refreshKey]);

  const projects = useMemo(
    () => orderOverviewProjects(overview?.projects ?? [], orderedProjects),
    [orderedProjects, overview?.projects],
  );
  const projectIds = useMemo(
    () => new Set((overview?.projects ?? []).map((project) => project.project.project_id)),
    [overview?.projects],
  );
  const hasRunningSession = useMemo(
    () => projects.some((project) => project.active_count > 0),
    [projects],
  );

  useEffect(() => {
    if (!isActive) return undefined;
    return listenProjectConversationUpdated((detail) => {
      if (!categoryId) return;
      if (projectIds.size > 0 && !projectIds.has(detail.projectId)) return;
      const sessionId = detail.sessionId;
      const usage = detail.usage;
      const hasLiveUsage = Boolean(usage && sessionId);
      if (usage && sessionId) {
        const key = buildOverviewSessionKey(detail.projectId, sessionId);
        const liveUsage = chatUsageToProjectOverviewUsage(usage);
        setLiveUsageBySessionKey((current) => ({
          ...current,
          [key]: liveUsage,
        }));
      }
      if (detail.runtimeStatus && detail.runtimeStatus !== "running" && sessionId) {
        const key = buildOverviewSessionKey(detail.projectId, sessionId);
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
  }, [categoryId, isActive, projectIds, scheduleRefresh]);

  useEffect(() => {
    if (!isActive || !categoryId || !hasRunningSession) return undefined;
    const timer = window.setInterval(() => {
      void loadOverview("refresh");
    }, RUNNING_SESSION_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [categoryId, hasRunningSession, isActive, loadOverview]);

  useEffect(() => {
    if (!isActive) return undefined;
    const handleFocus = () => {
      scheduleRefresh();
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [isActive, scheduleRefresh]);

  useEffect(() => {
    return () => {
      clearScheduledRefresh();
      abortControllerRef.current?.abort();
    };
  }, [clearScheduledRefresh]);

  const updateActiveSession = useCallback((projectId: string, sessionId: string) => {
    setOverview((current) => {
      if (!current) return current;
      const next = {
        ...current,
        projects: current.projects.map((project) =>
          project.project.project_id === projectId
            ? { ...project, active_session_id: sessionId }
            : project,
        ),
      };
      overviewRef.current = next;
      return next;
    });
  }, []);

  return {
    error,
    liveUsageBySessionKey,
    loadOverview,
    overview,
    projects,
    state,
    updateActiveSession,
  };
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
