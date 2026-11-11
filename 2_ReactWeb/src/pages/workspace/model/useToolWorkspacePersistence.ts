import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ToolFolder } from "../../../entities/tool/model/toolset";
import { getToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";
import type { UseToolFolderBrowserResult } from "../../../features/tool-browser/model/toolBrowserTypes";
import { createToolFolderDocumentSource } from "../../../features/document-tabs/model/documentFileSources";
import {
  getToolDashboardViewFromTab,
  type ToolDashboardView,
} from "../../../features/document-tabs/model/documentToolDashboardTabs";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import { isProjectConversationOverviewTab } from "../../../features/document-tabs/model/documentTabUtils";
import {
  getProjectWorkspaceState,
  type WorkspaceStateResponse,
} from "../../../services/project/getProjectWorkspaceState";
import { saveProjectWorkspaceState } from "../../../services/project/saveProjectWorkspaceState";

type ToolWorkspacePersistenceOptions = {
  activeToolFolder: ToolFolder | null;
  activeToolsetId: string | null;
  browser: UseToolFolderBrowserResult;
  documentTabs: ReturnType<typeof useDocumentTabs>;
};

type PendingSave = {
  projectId: string;
  payload: Omit<WorkspaceStateResponse, "project_id">;
};

export function useToolWorkspacePersistence({
  activeToolFolder,
  activeToolsetId,
  browser,
  documentTabs,
}: ToolWorkspacePersistenceOptions) {
  const [error, setError] = useState<string | null>(null);
  const hydratedWorkspaceKeyRef = useRef<string | null>(null);
  const restoreFailureRef = useRef<{ key: string; error: Error } | null>(null);
  const restoreWaitersRef = useRef(new Map<string, Set<(error?: Error, ready?: boolean) => void>>());
  const pendingSaveRef = useRef<PendingSave | null>(null);
  const restoreRequestIdRef = useRef(0);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const saveTimerRef = useRef<number | null>(null);
  const activeToolFolderId = activeToolFolder?.project_id ?? null;
  const activeProjectId = activeToolFolder?.project_id ?? null;
  const activeToolFolderName = activeToolFolder?.name ?? "";
  const activeWorkspaceKey = useMemo(
    () => activeToolsetId && activeToolFolderId
      ? getToolFolderWorkspaceKey(activeToolsetId, activeToolFolderId)
      : null,
    [activeToolFolderId, activeToolsetId],
  );

  // File opens from the outer dashboard must follow restoration, never race it.
  const waitForWorkspaceReady = useCallback((key: string, signal: AbortSignal): Promise<boolean> => {
    if (signal.aborted) return Promise.resolve(false);
    if (hydratedWorkspaceKeyRef.current === key) return Promise.resolve(true);
    if (restoreFailureRef.current?.key === key) return Promise.reject(restoreFailureRef.current.error);
    return new Promise((resolve, reject) => {
      const waiters = restoreWaitersRef.current.get(key) ?? new Set();
      const finish = (error?: Error, ready = false) => {
        signal.removeEventListener("abort", abort);
        waiters.delete(finish);
        if (!waiters.size && restoreWaitersRef.current.get(key) === waiters) restoreWaitersRef.current.delete(key);
        if (error) reject(error); else resolve(ready);
      };
      const abort = () => finish();
      waiters.add(finish);
      restoreWaitersRef.current.set(key, waiters);
      signal.addEventListener("abort", abort, { once: true });
    });
  }, []);
  const finishWorkspaceWaiters = useCallback((key: string, error?: Error, ready = false) => {
    for (const finish of restoreWaitersRef.current.get(key) ?? []) finish(error, ready);
  }, []);

  const flushPendingSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const pendingSave = pendingSaveRef.current;
    pendingSaveRef.current = null;
    if (!pendingSave) return;
    saveQueueRef.current = saveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        await saveProjectWorkspaceState(pendingSave.projectId, pendingSave.payload);
      })
      .catch((saveError: unknown) => {
        setError(formatToolWorkspaceError("工具工作区状态保存失败", saveError));
      });
  }, []);

  useEffect(() => {
    const restoreRequestId = ++restoreRequestIdRef.current;
    hydratedWorkspaceKeyRef.current = null;
    restoreFailureRef.current = null;
    setError(null);

    if (!activeWorkspaceKey || !activeToolsetId || !activeToolFolderId || !activeProjectId) {
      documentTabs.closeAllTabs();
      return;
    }

    const sourceRuntime = createToolFolderDocumentSource(
      activeToolsetId,
      activeToolFolderId,
      activeToolFolderName,
      activeProjectId,
    );

    void (async () => {
      let state: WorkspaceStateResponse;
      try {
        state = await getProjectWorkspaceState(activeProjectId);
      } catch (restoreError) {
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        setError(formatToolWorkspaceError("工具工作区状态恢复失败", restoreError));
        state = {
          active_dashboard: "basics",
          active_file_path: null,
          expanded_paths: [],
          project_id: activeProjectId,
          open_file_paths: [],
        };
      }

      try {
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        browser.restoreExpandedPaths(state.expanded_paths);
        await documentTabs.restoreWorkspaceTabs(
          sourceRuntime,
          state.open_file_paths,
          state.active_file_path,
        );
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        const isConversationOverviewActive = state.active_dashboard === "conversation_overview";
        const activeView: ToolDashboardView | null = state.active_file_path
          ? null
          : isConversationOverviewActive
            ? null
          : isToolDashboardView(state.active_dashboard)
            ? state.active_dashboard
            : "basics";
        await documentTabs.openToolDashboard(sourceRuntime, {
          activeView,
          title: activeToolFolderName,
        });
        documentTabs.ensureProjectConversationOverview(activeProjectId, {
          activate: isConversationOverviewActive,
        });
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        hydratedWorkspaceKeyRef.current = activeWorkspaceKey;
        finishWorkspaceWaiters(activeWorkspaceKey, undefined, true);
      } catch (restoreError) {
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        const message = formatToolWorkspaceError("工具标签恢复失败", restoreError);
        setError(message);
        restoreFailureRef.current = { key: activeWorkspaceKey, error: new Error(message) };
        finishWorkspaceWaiters(activeWorkspaceKey, restoreFailureRef.current.error);
      }
    })();

    return () => {
      ++restoreRequestIdRef.current;
      hydratedWorkspaceKeyRef.current = null;
      finishWorkspaceWaiters(activeWorkspaceKey);
      flushPendingSave();
    };
  }, [
    activeToolFolderId,
    activeToolFolderName,
    activeProjectId,
    activeToolsetId,
    activeWorkspaceKey,
    browser.restoreExpandedPaths,
    documentTabs.closeAllTabs,
    documentTabs.ensureProjectConversationOverview,
    documentTabs.openToolDashboard,
    documentTabs.restoreWorkspaceTabs,
    flushPendingSave,
    finishWorkspaceWaiters,
  ]);

  useEffect(() => {
    if (
      !activeWorkspaceKey ||
      !activeToolsetId ||
      !activeToolFolderId ||
      !activeProjectId ||
      hydratedWorkspaceKeyRef.current !== activeWorkspaceKey
    ) {
      return;
    }

    const openFilePaths = documentTabs.tabs
      .filter((tab) => tab.fileSource?.key === activeWorkspaceKey && tab.filePath)
      .map((tab) => tab.filePath!);
    const activeTabBelongsToWorkspace =
      documentTabs.activeTab?.fileSource?.key === activeWorkspaceKey;
    const activeFilePath = activeTabBelongsToWorkspace
      ? documentTabs.activeTab?.filePath ?? null
      : null;
    const activeDashboard = isProjectConversationOverviewTab(documentTabs.activeTab)
      && documentTabs.activeTab?.projectId === activeProjectId
      ? "conversation_overview"
      : activeTabBelongsToWorkspace && documentTabs.activeTab?.fileSource?.kind === "tool-dashboard"
        ? getToolDashboardViewFromTab(documentTabs.activeTab)
        : null;

    pendingSaveRef.current = {
      projectId: activeProjectId,
      payload: {
        active_dashboard: activeDashboard,
        active_file_path: activeFilePath,
        expanded_paths: Array.from(browser.userExpandedNodeIds),
        open_file_paths: openFilePaths,
      },
    };
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(flushPendingSave, 250);
  }, [
    activeToolFolderId,
    activeProjectId,
    activeToolsetId,
    activeWorkspaceKey,
    browser.userExpandedNodeIds,
    documentTabs.activeTab,
    documentTabs.tabs,
    flushPendingSave,
  ]);

  useEffect(() => () => {
    for (const key of restoreWaitersRef.current.keys()) finishWorkspaceWaiters(key);
    flushPendingSave();
  }, [finishWorkspaceWaiters, flushPendingSave]);

  return {
    activeWorkspaceKey,
    error,
    waitForWorkspaceReady,
  };
}

function formatToolWorkspaceError(prefix: string, error: unknown) {
  const message = error instanceof Error ? error.message : "未知错误";
  return `${prefix}：${message}`;
}

function isToolDashboardView(value: unknown): value is ToolDashboardView {
  return (
    value === "basics"
    || value === "permissions"
    || value === "examples"
    || value === "dependencies"
    || value === "callRecords"
  );
}
