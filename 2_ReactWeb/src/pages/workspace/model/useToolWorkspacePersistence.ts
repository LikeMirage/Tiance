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
      } catch (restoreError) {
        if (restoreRequestId !== restoreRequestIdRef.current) return;
        setError(formatToolWorkspaceError("工具标签恢复失败", restoreError));
      }
    })();

    return () => {
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
    flushPendingSave();
  }, [flushPendingSave]);

  return {
    activeWorkspaceKey,
    error,
  };
}

function formatToolWorkspaceError(prefix: string, error: unknown) {
  const message = error instanceof Error ? error.message : "未知错误";
  return `${prefix}：${message}`;
}

function isToolDashboardView(value: unknown): value is ToolDashboardView {
  return (
    value === "basics"
    || value === "examples"
    || value === "dependencies"
    || value === "callRecords"
  );
}
