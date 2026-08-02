import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import {
  getCachedProjectEntryWarmup,
  type ProjectEntryWarmup,
} from "../../../features/project-entry/model/projectEntryWarmup";
import { useProjectBrowser } from "../../../features/project-browser/model/useProjectBrowser";
import type { UseProjectCatalogResult } from "../../../features/project-catalog/model/useProjectCatalog";
import { getProjectWorkspaceState } from "../../../services/project/getProjectWorkspaceState";
import { patchProjectWorkspaceState } from "../../../services/project/saveProjectWorkspaceState";
import { useOverlayScrollbar } from "../../../shared/model/overlay-scrollbar/useOverlayScrollbar";

export type WorkspaceProjectPanelView = "list" | "detail";
export type WorkspaceProjectEntryKind = "file" | "folder";

const TOOLBAR_ACTION_THROTTLE_MS = 300;

export type WorkspaceProjectsPanelControllerProjectCatalog = Pick<
  UseProjectCatalogResult,
  | "createProject"
  | "createProjectFromFolder"
  | "expandedProjectId"
  | "selectedCategoryId"
  | "selectedCategoryProjects"
  | "state"
>;

type UseWorkspaceProjectsPanelControllerInput = {
  documentTabs: ReturnType<typeof useDocumentTabs>;
  projectCatalog: WorkspaceProjectsPanelControllerProjectCatalog;
};

type InitialExpandedPathsState = {
  isReady: boolean;
  paths: string[];
  projectId: string | null;
};

type CapturedProjectWarmup = {
  projectId: string;
  warmup: ProjectEntryWarmup | null;
};

type PendingExpandedPathsSave = {
  paths: string[];
  projectId: string;
  requestId: number;
};

export function useWorkspaceProjectsPanelController({
  documentTabs,
  projectCatalog,
}: UseWorkspaceProjectsPanelControllerInput) {
  const activeView: WorkspaceProjectPanelView =
    projectCatalog.expandedProjectId ? "detail" : "list";
  const [initialExpandedPathsState, setInitialExpandedPathsState] =
    useState<InitialExpandedPathsState>({ isReady: false, paths: [], projectId: null });
  const capturedWarmupRef = useRef<CapturedProjectWarmup | null>(null);
  if (!projectCatalog.expandedProjectId) {
    capturedWarmupRef.current = null;
  } else if (capturedWarmupRef.current?.projectId !== projectCatalog.expandedProjectId) {
    capturedWarmupRef.current = {
      projectId: projectCatalog.expandedProjectId,
      warmup: getCachedProjectEntryWarmup(projectCatalog.expandedProjectId),
    };
  }
  const warmedProject = capturedWarmupRef.current?.warmup ?? null;
  const warmedWorkspaceState = warmedProject?.workspaceState ?? null;
  const initialExpandedPaths =
    initialExpandedPathsState.isReady &&
    initialExpandedPathsState.projectId === projectCatalog.expandedProjectId
      ? initialExpandedPathsState.paths
      : warmedWorkspaceState?.expanded_paths ?? [];
  const isWarmedExpandedPathsReady =
    Boolean(projectCatalog.expandedProjectId && warmedWorkspaceState);
  const isStoredExpandedPathsReady =
    initialExpandedPathsState.isReady &&
    initialExpandedPathsState.projectId === projectCatalog.expandedProjectId;
  const canPersistExpandedPaths =
    isStoredExpandedPathsReady ||
    (
      isWarmedExpandedPathsReady &&
      initialExpandedPathsState.projectId === projectCatalog.expandedProjectId
    );
  const browser = useProjectBrowser(
    projectCatalog.expandedProjectId,
    {
      initialExpandedPaths,
      initialTreeData: warmedProject?.rootTree,
    },
  );
  const desktopShell = useDesktopShell();
  const handledCreatePointerRef = useRef<WorkspaceProjectEntryKind | null>(null);
  const lastCreateAtRef = useRef(0);
  const lastRefreshAtRef = useRef(0);
  const expandedPathsSaveRequestIdRef = useRef(0);
  const isSavingExpandedPathsRef = useRef(false);
  const pendingExpandedPathsSaveRef = useRef<PendingExpandedPathsSave | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const [fileSearchKeyword, setFileSearchKeyword] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [workspaceStateError, setWorkspaceStateError] = useState<string | null>(null);
  const projectScrollbar = useOverlayScrollbar(
    [
      projectCatalog.state,
      projectCatalog.selectedCategoryId ?? "",
      projectCatalog.selectedCategoryProjects.length,
      activeView,
      browser.treeData.length,
      browser.expandedNodeIds.size,
      browser.isLoadingNodeIds.size,
    ].join(":"),
  );

  useEffect(() => {
    const projectId = projectCatalog.expandedProjectId;
    let isStale = false;

    if (!projectId) {
      setInitialExpandedPathsState({ isReady: false, paths: [], projectId: null });
      setWorkspaceStateError(null);
      return () => {
        isStale = true;
      };
    }

    if (warmedWorkspaceState) {
      setWorkspaceStateError(null);
      setInitialExpandedPathsState({
        isReady: true,
        paths: warmedWorkspaceState.expanded_paths ?? [],
        projectId,
      });
      return () => {
        isStale = true;
      };
    }

    setWorkspaceStateError(null);
    setInitialExpandedPathsState({ isReady: false, paths: [], projectId });
    getProjectWorkspaceState(projectId)
      .then((state) => {
        if (!isStale) {
          setWorkspaceStateError(null);
          setInitialExpandedPathsState({
            isReady: true,
            paths: state.expanded_paths ?? [],
            projectId,
          });
        }
      })
      .catch(() => {
        if (!isStale) {
          setInitialExpandedPathsState({ isReady: true, paths: [], projectId });
          setWorkspaceStateError("项目文件树展开状态恢复失败。");
        }
      });

    return () => {
      isStale = true;
    };
  }, [projectCatalog.expandedProjectId, warmedWorkspaceState]);

  useEffect(() => {
    setSearchKeyword("");
  }, [projectCatalog.selectedCategoryId]);

  const createProjectEntry = useCallback((kind: WorkspaceProjectEntryKind) => {
    const now = Date.now();
    if (now - lastCreateAtRef.current < TOOLBAR_ACTION_THROTTLE_MS) {
      return;
    }
    lastCreateAtRef.current = now;

    if (kind === "file") {
      void browser.createFile();
      return;
    }

    void browser.createFolder();
  }, [browser]);

  const handleCreatePointerDown = useCallback((
    event: ReactPointerEvent<HTMLButtonElement>,
    kind: WorkspaceProjectEntryKind,
  ) => {
    if (event.button !== 0) {
      return;
    }

    event.preventDefault();
    handledCreatePointerRef.current = kind;
    createProjectEntry(kind);
  }, [createProjectEntry]);

  const handleCreateClick = useCallback((kind: WorkspaceProjectEntryKind) => {
    if (handledCreatePointerRef.current === kind) {
      handledCreatePointerRef.current = null;
      return;
    }

    createProjectEntry(kind);
  }, [createProjectEntry]);

  const handleRefreshTreeClick = useCallback(() => {
    const now = Date.now();
    if (now - lastRefreshAtRef.current < TOOLBAR_ACTION_THROTTLE_MS) {
      return;
    }
    lastRefreshAtRef.current = now;
    browser.refreshTree();
  }, [browser]);

  const drainExpandedPathsSaveQueue = useCallback(async () => {
    if (isSavingExpandedPathsRef.current) {
      return;
    }

    isSavingExpandedPathsRef.current = true;
    try {
      while (pendingExpandedPathsSaveRef.current) {
        const saveRequest = pendingExpandedPathsSaveRef.current;
        pendingExpandedPathsSaveRef.current = null;
        try {
          await patchProjectWorkspaceState(saveRequest.projectId, {
            expanded_paths: saveRequest.paths,
          });
          if (
            expandedPathsSaveRequestIdRef.current === saveRequest.requestId &&
            projectCatalog.expandedProjectId === saveRequest.projectId
          ) {
            setWorkspaceStateError(null);
          }
        } catch (saveError) {
          if (
            expandedPathsSaveRequestIdRef.current === saveRequest.requestId &&
            projectCatalog.expandedProjectId === saveRequest.projectId
          ) {
            const message = saveError instanceof Error ? saveError.message : "未知错误";
            setWorkspaceStateError(
              `项目文件树展开状态保存失败：${message}`,
            );
          }
        }
      }
    } finally {
      isSavingExpandedPathsRef.current = false;
      if (pendingExpandedPathsSaveRef.current) {
        void drainExpandedPathsSaveQueue();
      }
    }
  }, [projectCatalog.expandedProjectId]);

  const saveExpandedPaths = useCallback(() => {
    const projectId = projectCatalog.expandedProjectId;
    if (!projectId || !canPersistExpandedPaths || browser.searchKeyword.trim()) {
      return;
    }

    const requestId = expandedPathsSaveRequestIdRef.current + 1;
    expandedPathsSaveRequestIdRef.current = requestId;
    pendingExpandedPathsSaveRef.current = {
      paths: Array.from(browser.userExpandedNodeIds),
      projectId,
      requestId,
    };
    void drainExpandedPathsSaveQueue();
  }, [
    browser.searchKeyword,
    browser.userExpandedNodeIds,
    canPersistExpandedPaths,
    drainExpandedPathsSaveQueue,
    projectCatalog.expandedProjectId,
  ]);

  useEffect(() => {
    if (!canPersistExpandedPaths) {
      return;
    }

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }

    saveTimerRef.current = window.setTimeout(saveExpandedPaths, 500);
    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [browser.userExpandedNodeIds, canPersistExpandedPaths, saveExpandedPaths]);

  useEffect(() => {
    if (browser.editingNodeId) {
      return;
    }

    const tab = documentTabs.activeTab;
    if (!tab) {
      browser.selectRoot();
      return;
    }

    if (
      !tab.projectFilePath ||
      tab.projectId !== projectCatalog.expandedProjectId
    ) {
      return;
    }

    void browser.revealPath(tab.projectFilePath);
  }, [
    browser.revealPath,
    browser.selectRoot,
    browser.editingNodeId,
    documentTabs.activeTab?.id,
    documentTabs.activeTab?.projectFilePath,
    documentTabs.activeTab?.projectId,
    projectCatalog.expandedProjectId,
  ]);

  const handleSearchChange = useCallback((value: string) => {
    if (activeView === "detail") {
      setFileSearchKeyword(value);
      browser.setSearchKeyword(value);
      return;
    }

    setSearchKeyword(value);
  }, [activeView, browser]);

  const handleImportFolder = useCallback(async () => {
    setIsImporting(true);
    try {
      const rootPath = await desktopShell.selectProjectFolder();
      if (!rootPath) {
        return;
      }

      await projectCatalog.createProjectFromFolder(rootPath);
    } catch {
      // Project catalog owns the surfaced error state.
    } finally {
      setIsImporting(false);
    }
  }, [desktopShell, projectCatalog]);

  const handleCreateProject = useCallback(() => {
    setSearchKeyword("");
    void projectCatalog.createProject().catch(() => undefined);
  }, [projectCatalog]);

  const searchInputValue =
    activeView === "detail" ? fileSearchKeyword : searchKeyword;
  const searchPlaceholder = activeView === "detail" ? "搜索文件" : "搜索项目";

  return {
    activeView,
    browser,
    desktopShell,
    handleCreateClick,
    handleCreatePointerDown,
    handleCreateProject,
    handleRefreshTreeClick,
    handleImportFolder,
    handleSearchChange,
    isImporting,
    projectScrollbar,
    searchInputValue,
    searchKeyword,
    searchPlaceholder,
    workspaceStateError,
  };
}
