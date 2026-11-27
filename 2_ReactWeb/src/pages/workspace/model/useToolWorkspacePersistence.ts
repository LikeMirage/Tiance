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
import { getProjectDashboardName } from "../../../features/document-tabs/model/documentTabUtils";
import type { WorkspaceStateResponse } from "../../../services/project/getProjectWorkspaceState";
import { patchProjectWorkspaceState, readWorkspaceAfterWrites } from "../../../services/project/saveProjectWorkspaceState";
import { snapshotWorkspaceTabs } from "../../../features/document-tabs/model/workspaceTabEntries";

type ToolWorkspacePersistenceOptions = {
  activeToolFolder: ToolFolder | null;
  folderExpanded?: boolean;
  activeToolsetId: string | null;
  browser: UseToolFolderBrowserResult;
  documentTabs: ReturnType<typeof useDocumentTabs>;
};

export function useToolWorkspacePersistence({
  activeToolFolder,
  folderExpanded = true,
  activeToolsetId,
  browser,
  documentTabs,
}: ToolWorkspacePersistenceOptions) {
  const [error, setError] = useState<string | null>(null);
  const hydratedWorkspaceKeyRef = useRef<string | null>(null);
  const restoreFailureRef = useRef<{ key: string; error: Error } | null>(null);
  const restoreWaitersRef = useRef(new Map<string, Set<(error?: Error, ready?: boolean) => void>>());
  const restoreRequestIdRef = useRef(0);
  const [readyKey, setReadyKey] = useState<string | null>(null);
  const lastSaved = useRef("");
  const lastWorkspaceState = useRef<WorkspaceStateResponse | null>(null);
  const activeToolFolderId = activeToolFolder?.project_id ?? null;
  const activeProjectId = activeToolFolder?.project_id ?? null;
  const activeToolFolderName = activeToolFolder?.name ?? "";
  const activeWorkspaceKey = useMemo(
    () => activeToolsetId && activeToolFolderId
      ? getToolFolderWorkspaceKey(activeToolsetId, activeToolFolderId)
      : null,
    [activeToolFolderId, activeToolsetId],
  );
  const hydrationKey = folderExpanded ? activeWorkspaceKey : `overview:${activeWorkspaceKey}`;

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

  useEffect(() => {
    const restoreRequestId = ++restoreRequestIdRef.current;
    hydratedWorkspaceKeyRef.current = null;
    restoreFailureRef.current = null;
    setReadyKey(null);
    lastSaved.current = "";
    setError(null);

    if (!activeWorkspaceKey || !activeToolsetId || !activeToolFolderId || !activeProjectId) {
      documentTabs.resetWorkspaceFiles();
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
      let loaded = true;
      try {
        state = await readWorkspaceAfterWrites(activeProjectId);
      } catch (restoreError) {
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        setError(formatToolWorkspaceError("工具工作区状态恢复失败", restoreError));
        loaded = false;
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
        if (folderExpanded) browser.restoreExpandedPaths(state.expanded_paths);
        const activeWebId = await documentTabs.restoreWorkspaceTabs(
          sourceRuntime,
          state.open_file_paths,
          state.active_file_path,
          { entries: state.open_tabs, overviewOnly: !folderExpanded },
        );
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        const isConversationOverviewActive = state.active_dashboard === "conversation_overview";
        const isMemoryActive = state.active_dashboard === "project_memory";
        const activeView: ToolDashboardView | null = activeWebId || state.active_file_path || isMemoryActive || isConversationOverviewActive
          ? null
          : isToolDashboardView(state.active_dashboard)
            ? state.active_dashboard
            : "basics";
        if (folderExpanded) {
          await documentTabs.openToolDashboard(sourceRuntime, {
            activeView,
            title: activeToolFolderName,
          });
          if (restoreRequestId !== restoreRequestIdRef.current) return;
          documentTabs.ensureProjectConversationOverview(activeProjectId, {
            activate: !activeWebId && isConversationOverviewActive,
          });
          documentTabs.ensureProjectMemoryDashboard(activeProjectId, !activeWebId && isMemoryActive);
        }
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        hydratedWorkspaceKeyRef.current = hydrationKey;
        lastWorkspaceState.current = state;
        if (loaded) setReadyKey(hydrationKey);
        if (folderExpanded) finishWorkspaceWaiters(activeWorkspaceKey, undefined, true);
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
      if (folderExpanded) finishWorkspaceWaiters(activeWorkspaceKey);
    };
  }, [
    activeToolFolderId,
    activeToolFolderName,
    activeProjectId,
    activeToolsetId,
    activeWorkspaceKey,
    folderExpanded,
    hydrationKey,
    browser.restoreExpandedPaths,
    documentTabs.resetWorkspaceFiles,
    documentTabs.ensureProjectConversationOverview,
    documentTabs.ensureProjectMemoryDashboard,
    documentTabs.openToolDashboard,
    documentTabs.restoreWorkspaceTabs,
    finishWorkspaceWaiters,
  ]);

  useEffect(() => {
    if (
      !activeWorkspaceKey ||
      !activeToolsetId ||
      !activeToolFolderId ||
      !activeProjectId ||
      readyKey !== hydrationKey || hydratedWorkspaceKeyRef.current !== hydrationKey
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
    const activeDashboard = activeTabBelongsToWorkspace && documentTabs.activeTab?.fileSource?.kind === "tool-dashboard"
      ? getToolDashboardViewFromTab(documentTabs.activeTab)
      : getProjectDashboardName(documentTabs.activeTab?.projectId === activeProjectId ? documentTabs.activeTab : null);

    const hiddenSelection = !folderExpanded && !documentTabs.activeTab ? lastWorkspaceState.current : null;
    const payload = {
      active_dashboard: hiddenSelection?.active_dashboard ?? activeDashboard,
      active_file_path: hiddenSelection?.active_file_path ?? activeFilePath,
      ...(folderExpanded ? { expanded_paths: Array.from(browser.userExpandedNodeIds) } : {}),
      open_file_paths: openFilePaths,
      open_tabs: snapshotWorkspaceTabs(documentTabs.tabs, documentTabs.activeTab?.id ?? null, activeProjectId,
        tab => tab.fileSource?.key === activeWorkspaceKey ? tab.filePath : null),
    };
    const key = JSON.stringify(payload);
    if (lastSaved.current === key) return;
    lastSaved.current = key;
    void patchProjectWorkspaceState(activeProjectId, payload).catch(error => {
      if (hydratedWorkspaceKeyRef.current === hydrationKey && lastSaved.current === key) {
        lastSaved.current = "";
        setError(formatToolWorkspaceError("工具工作区状态保存失败", error));
      }
    });
  }, [
    activeToolFolderId,
    activeProjectId,
    activeToolsetId,
    activeWorkspaceKey,
    folderExpanded,
    hydrationKey,
    readyKey,
    browser.userExpandedNodeIds,
    documentTabs.activeTab,
    documentTabs.tabs,
  ]);

  useEffect(() => () => {
    for (const key of restoreWaitersRef.current.keys()) finishWorkspaceWaiters(key);
  }, [finishWorkspaceWaiters]);

  return {
    activeWorkspaceKey: folderExpanded ? activeWorkspaceKey : null,
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
