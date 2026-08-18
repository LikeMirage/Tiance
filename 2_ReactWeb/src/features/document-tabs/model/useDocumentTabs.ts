import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type {
  DocumentFileSource,
  DocumentTab,
  EditorTabId,
} from "../../../entities/editor/model/editorDocument";
import type { EditorReferenceViewerPayload } from "../../../entities/editor/model/editorReference";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";
import {
  createProjectDocumentSource,
  type DocumentFileSourceRuntime,
  getProjectDocumentSourceKey,
  isProjectFileSource,
} from "./documentFileSources";
import { buildStandaloneFileTab, buildWorkspaceFileTab, hydrateWorkspaceFileTab } from "./documentFileTabs";
import { resolveDocumentPreview } from "./documentPreviewResolver";
import {
  getPathName,
  getTabFilePath,
  getTabSourceKey,
  isPinnedDocumentTab,
  isToolDashboardTabForSource,
  isWorkspacePathAffected,
  makeStandaloneTabId,
  makeTabId,
  normalizeWorkspacePath,
  resolveRenamedTabId,
} from "./documentTabUtils";
import { HttpRequestError } from "../../../services/http/httpClient";
import {
  buildToolDashboardTab,
  doesToolDashboardViewNeedContent,
  getToolDashboardViewFromTab,
  invalidateLoadedToolDashboardTab,
  isToolCatalogMetadataPath,
  makeToolDashboardTabId,
  publishToolCatalogMetadataChange,
  readToolDashboardContent,
  saveToolDashboardContent,
  TOOL_MANIFEST_FILE,
  type ToolDashboardView,
} from "./documentToolDashboardTabs";
import { useDocumentTabFileSync } from "./useDocumentTabFileSync";
import { useDocumentTabRestore } from "./useDocumentTabRestore";
import {
  markDocumentTextContentAccessed,
  pruneDocumentTextContentCache,
} from "./documentTextContentCache";
import {
  buildVirtualConversationBranchesTab,
  buildVirtualConversationDataTab,
  buildVirtualHtmlPreviewTab,
  buildVirtualMemoryDashboardTab,
  buildVirtualProjectConversationOverviewTab,
  buildVirtualProjectRoleConfigurationTab,
  buildVirtualProjectThemeConfigurationTab,
  buildVirtualReferenceViewerTab,
} from "./documentVirtualTabs";

export function useDocumentTabs() {
  const [tabs, setTabs] = useState<DocumentTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<EditorTabId | null>(null);
  const tabsRef = useRef(tabs);
  const activeTabIdRef = useRef(activeTabId);
  const restoreRequestIdRef = useRef(0);
  const fileLoadRequestIdsRef = useRef(new Map<EditorTabId, number>());
  const loadedToolDashboardTabIdsRef = useRef(new Set<EditorTabId>());

  useLayoutEffect(() => {
    tabsRef.current = tabs;
  }, [tabs]);

  useLayoutEffect(() => {
    activeTabIdRef.current = activeTabId;
  }, [activeTabId]);

  const getSnapshot = useCallback(() => ({
    activeTabId: activeTabIdRef.current,
    tabs: tabsRef.current,
  }), []);

  const {
    refreshTabContent,
    registerFileSource,
    renameWorkspacePath,
    resolveFileSourceRuntime,
  } = useDocumentTabFileSync({
    activeTabIdRef,
    fileLoadRequestIdsRef,
    setActiveTabId,
    setTabs,
    tabs,
    tabsRef,
  });

  const {
    restoreTabs,
    restoreWorkspaceTabs,
  } = useDocumentTabRestore({
    registerFileSource,
    restoreRequestIdRef,
    setActiveTabId,
    setTabs,
  });
  const openWorkspaceFile = useCallback(async (
    node: ExplorerNode,
    sourceRuntime: DocumentFileSourceRuntime,
    options?: { filePath?: string | null },
  ) => {
    const preview = resolveDocumentPreview(node);

    const runtime = registerFileSource(sourceRuntime);
    const filePath = normalizeWorkspacePath(options?.filePath ?? node.path);
    if (!filePath) return;

    const tabId = makeTabId(runtime.source.key, filePath);
    const existing = tabsRef.current.find((tab) => tab.id === tabId);
    if (existing) {
      activeTabIdRef.current = tabId;
      setActiveTabId(tabId);
      const nextTabs = tabsRef.current.map((tab) =>
        tab.id === tabId ? markDocumentTextContentAccessed(tab) : tab,
      );
      tabsRef.current = nextTabs;
      setTabs(nextTabs);
      if (existing.kind === "text" && existing.saveState !== "saving") {
        void refreshTabContent(tabId, runtime, filePath);
      }
      return;
    }

    const newTab = buildWorkspaceFileTab(node, runtime.source, filePath, preview);
    const nextTabs = [...tabsRef.current, newTab];
    tabsRef.current = nextTabs;
    activeTabIdRef.current = tabId;
    setTabs(nextTabs);
    setActiveTabId(tabId);

    if (preview.kind === "text") {
      await refreshTabContent(tabId, runtime, filePath);
    }
  }, [refreshTabContent, registerFileSource]);

  const openNode = useCallback(async (
    node: ExplorerNode,
    options?: {
      filePath?: string | null;
      fileSource?: DocumentFileSourceRuntime | null;
      projectId?: string | null;
      projectFilePath?: string | null;
    },
  ) => {
    if (options?.fileSource) {
      await openWorkspaceFile(node, options.fileSource, {
        filePath: options.filePath ?? options.projectFilePath ?? node.path,
      });
      return;
    }

    const projectId = options?.projectId ?? null;
    if (projectId) {
      await openWorkspaceFile(node, createProjectDocumentSource(projectId), {
        filePath: options?.projectFilePath ?? options?.filePath ?? node.path,
      });
      return;
    }

    const preview = resolveDocumentPreview(node);
    if (preview.kind !== "text") return;
    const filePath = normalizeWorkspacePath(options?.filePath ?? node.path);
    if (!filePath) return;
    const tabId = makeStandaloneTabId(filePath);
    const existing = tabsRef.current.find((tab) => tab.id === tabId);
    if (existing) {
      activeTabIdRef.current = tabId;
      setActiveTabId(tabId);
      const nextTabs = tabsRef.current.map((tab) =>
        tab.id === tabId ? markDocumentTextContentAccessed(tab) : tab,
      );
      tabsRef.current = nextTabs;
      setTabs(nextTabs);
      return;
    }
    const newTab = buildStandaloneFileTab(node, filePath, preview);
    const nextTabs = [...tabsRef.current, newTab];
    tabsRef.current = nextTabs;
    activeTabIdRef.current = tabId;
    setTabs(nextTabs);
    setActiveTabId(tabId);
  }, [openWorkspaceFile]);

  const closeTab = useCallback((tabId: EditorTabId) => {
    const currentTabs = tabsRef.current;
    const idx = currentTabs.findIndex((tab) => tab.id === tabId);
    if (idx < 0 || isPinnedDocumentTab(currentTabs[idx])) return;
    const nextTabs = currentTabs.filter((tab) => tab.id !== tabId);
    fileLoadRequestIdsRef.current.delete(tabId);
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    if (activeTabIdRef.current === tabId) {
      const nextActive = nextTabs[Math.min(idx, nextTabs.length - 1)]?.id ?? null;
      activeTabIdRef.current = nextActive;
      setActiveTabId(nextActive);
    }
  }, []);

  const closeOtherTabs = useCallback((tabId: EditorTabId) => {
    setTabs((prev) => {
      const keep = prev.find((tab) => tab.id === tabId);
      if (!keep) return prev;
      for (const tab of prev) {
        if (tab.id !== tabId && !isPinnedDocumentTab(tab)) {
          fileLoadRequestIdsRef.current.delete(tab.id);
        }
      }
      setActiveTabId(tabId);
      return prev.filter((tab) => tab.id === tabId || isPinnedDocumentTab(tab));
    });
  }, []);

  const closeAllTabs = useCallback((options?: { preservePinned?: boolean }) => {
    restoreRequestIdRef.current += 1;
    if (!options?.preservePinned) {
      fileLoadRequestIdsRef.current.clear();
      setTabs([]);
      setActiveTabId(null);
      return;
    }

    setTabs((prev) => {
      const pinnedTabs = prev.filter(isPinnedDocumentTab);
      const pinnedIds = new Set(pinnedTabs.map((tab) => tab.id));
      for (const tab of prev) {
        if (!pinnedIds.has(tab.id)) {
          fileLoadRequestIdsRef.current.delete(tab.id);
        }
      }
      const nextActive = activeTabIdRef.current && pinnedIds.has(activeTabIdRef.current)
        ? activeTabIdRef.current
        : pinnedTabs[0]?.id ?? null;
      setActiveTabId(nextActive);
      return pinnedTabs;
    });
  }, []);

  const loadToolDashboardTabContent = useCallback(async (
    runtime: DocumentFileSourceRuntime,
    tabId: EditorTabId,
    view: ToolDashboardView,
    options: { force?: boolean } = {},
  ) => {
    if (!doesToolDashboardViewNeedContent(view)) return;
    const current = tabsRef.current.find((tab) => tab.id === tabId);
    if (current?.isDirty) return;
    if (!current && !options.force) return;
    if (!options.force && loadedToolDashboardTabIdsRef.current.has(tabId)) return;

    const requestId = (fileLoadRequestIdsRef.current.get(tabId) ?? 0) + 1;
    fileLoadRequestIdsRef.current.set(tabId, requestId);
    setTabs((prev) =>
      prev.map((tab) =>
        tab.id === tabId
          ? { ...tab, saveState: "saving" as const, saveError: null }
          : tab,
      ),
    );

    try {
      const content = await readToolDashboardContent(runtime, view);
      if (fileLoadRequestIdsRef.current.get(tabId) !== requestId) return;
      loadedToolDashboardTabIdsRef.current.add(tabId);
      setTabs((prev) =>
        prev.map((tab) =>
          tab.id === tabId
            ? {
              ...tab,
              content,
              savedContent: content,
              textContentAccessedAt: Date.now(),
              textContentLoaded: true,
              isDirty: false,
              isMissing: false,
              mtimeMs: null,
              saveState: "idle" as const,
              saveError: null,
            }
            : tab,
        ),
      );
    } catch (err) {
      if (fileLoadRequestIdsRef.current.get(tabId) !== requestId) return;
      loadedToolDashboardTabIdsRef.current.delete(tabId);
      setTabs((prev) =>
        prev.map((tab) =>
          tab.id === tabId
            ? {
              ...tab,
              saveState: "error" as const,
              saveError: err instanceof Error ? err.message : "读取工具看板失败。",
            }
            : tab,
        ),
      );
    }
  }, []);

  const selectTab = useCallback((tabId: EditorTabId) => {
    const tab = tabsRef.current.find((item) => item.id === tabId);
    if (!tab) return;
    activeTabIdRef.current = tabId;
    setActiveTabId(tabId);
    const nextTabs = tabsRef.current.map((item) =>
      item.id === tabId ? markDocumentTextContentAccessed(item) : item,
    );
    tabsRef.current = nextTabs;
    setTabs(nextTabs);
    if (!isPinnedDocumentTab(tab)) return;
    const runtime = resolveFileSourceRuntime(tab.fileSource);
    if (!runtime) return;
    void loadToolDashboardTabContent(runtime, tabId, getToolDashboardViewFromTab(tab));
  }, [loadToolDashboardTabContent, resolveFileSourceRuntime]);

  const renameProjectPath = useCallback((
    projectId: string,
    previousPath: string,
    nextPath: string,
  ) => {
    renameWorkspacePath(getProjectDocumentSourceKey(projectId), previousPath, nextPath);
  }, [renameWorkspacePath]);

  const openVirtualHtmlPreview = useCallback((html: string, options?: { projectId?: string | null }) => {
    const newTab = buildVirtualHtmlPreviewTab(html, {
      projectId: options?.projectId ?? null,
    });
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const openVirtualMemoryDashboard = useCallback((
    scope: "global" | "project",
    options?: { projectId?: string | null },
  ) => {
    const newTab = buildVirtualMemoryDashboardTab({
      projectId: options?.projectId ?? null,
      scope,
    });
    const existing = tabsRef.current.find((tab) => tab.id === newTab.id);
    if (existing) {
      setActiveTabId(existing.id);
      return;
    }
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const openVirtualConversationBranches = useCallback((projectId: string) => {
    const newTab = buildVirtualConversationBranchesTab({ projectId });
    const existing = tabsRef.current.find((tab) => tab.id === newTab.id);
    if (existing) {
      setActiveTabId(existing.id);
      return;
    }
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const openVirtualConversationData = useCallback((options: {
    content: string;
    fileName: string;
    projectId: string;
    revisionMs: number;
    sessionId: string | null;
    totalCount?: number | null;
    page?: number | null;
    pageSize?: number | null;
    totalPages?: number | null;
    hasPrevious?: boolean;
    hasNext?: boolean;
  }) => {
    const newTab = buildVirtualConversationDataTab(options);
    const existing = tabsRef.current.find((tab) => tab.id === newTab.id);
    if (existing) {
      setTabs((current) => current.map((tab) => (
        tab.id === newTab.id ? newTab : tab
      )));
      setActiveTabId(existing.id);
      return;
    }
    setTabs((current) => [...current, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const ensureProjectConversationOverview = useCallback((
    projectId: string,
    options: { activate?: boolean } = {},
  ) => {
    const overviewTab = buildVirtualProjectConversationOverviewTab(projectId);
    setTabs((prev) => [
      overviewTab,
      ...prev.filter((tab) => tab.id !== overviewTab.id),
    ]);
    if (options.activate) {
      setActiveTabId(overviewTab.id);
    }
  }, []);

  const ensureProjectRoleConfiguration = useCallback((
    projectId: string,
    options: { activate?: boolean } = {},
  ) => {
    const configurationTab = buildVirtualProjectRoleConfigurationTab(projectId);
    setTabs((prev) => [
      configurationTab,
      ...prev.filter((tab) => tab.id !== configurationTab.id),
    ]);
    if (options.activate) {
      setActiveTabId(configurationTab.id);
    }
  }, []);

  const ensureProjectThemeConfiguration = useCallback((
    projectId: string,
    options: { activate?: boolean } = {},
  ) => {
    const configurationTab = buildVirtualProjectThemeConfigurationTab(projectId);
    setTabs((prev) => [
      configurationTab,
      ...prev.filter((tab) => tab.id !== configurationTab.id),
    ]);
    if (options.activate) {
      setActiveTabId(configurationTab.id);
    }
  }, []);

  const openVirtualReferenceViewer = useCallback((
    payload: EditorReferenceViewerPayload,
    options?: { projectId?: string | null },
  ) => {
    const newTab = buildVirtualReferenceViewerTab(payload, {
      projectId: options?.projectId ?? null,
    });
    const existing = tabsRef.current.find((tab) => tab.id === newTab.id);
    if (existing) {
      setActiveTabId(existing.id);
      return;
    }
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const openToolDashboard = useCallback(async (
    sourceRuntime: DocumentFileSourceRuntime,
    options?: {
      activeView?: ToolDashboardView | null;
      title?: string | null;
    },
  ) => {
    const runtime = registerFileSource(sourceRuntime);
    const basicsTabId = makeToolDashboardTabId(runtime.source.key, "basics");
    const examplesTabId = makeToolDashboardTabId(runtime.source.key, "examples");
    const dependenciesTabId = makeToolDashboardTabId(runtime.source.key, "dependencies");
    const callRecordsTabId = makeToolDashboardTabId(runtime.source.key, "callRecords");
    const obsoleteInjectionTabId = `${runtime.source.key}:__tool_dashboard_injection__` as EditorTabId;
    const obsoleteReturnsTabId = `${runtime.source.key}:__tool_dashboard_returns__` as EditorTabId;
    const title = options?.title ?? runtime.source.label ?? "工具";

    setTabs((prev) => {
      const existingBasics = prev.find((tab) => tab.id === basicsTabId);
      const existingExamples = prev.find((tab) => tab.id === examplesTabId);
      const existingDependencies = prev.find((tab) => tab.id === dependenciesTabId);
      const existingCallRecords = prev.find((tab) => tab.id === callRecordsTabId);
      const basicsTab = buildToolDashboardTab(runtime.source, title, "basics", existingBasics);
      const examplesTab = buildToolDashboardTab(runtime.source, title, "examples", existingExamples);
      const dependenciesTab = buildToolDashboardTab(runtime.source, title, "dependencies", existingDependencies);
      const callRecordsTab = buildToolDashboardTab(runtime.source, title, "callRecords", existingCallRecords);
      const remaining = prev.filter((tab) =>
        tab.id !== basicsTabId &&
        tab.id !== examplesTabId &&
        tab.id !== dependenciesTabId &&
        tab.id !== callRecordsTabId &&
        tab.id !== obsoleteInjectionTabId &&
        tab.id !== obsoleteReturnsTabId
      );
      const sourceIndex = remaining.findIndex((tab) => tab.fileSource?.key === runtime.source.key);
      if (sourceIndex < 0) {
        return [basicsTab, examplesTab, dependenciesTab, callRecordsTab, ...remaining];
      }
      return [
        ...remaining.slice(0, sourceIndex),
        basicsTab,
        examplesTab,
        dependenciesTab,
        callRecordsTab,
        ...remaining.slice(sourceIndex),
      ];
    });
    const activeView = options?.activeView === undefined ? "basics" : options.activeView;
    if (activeView) {
      const activeTabId = makeToolDashboardTabId(runtime.source.key, activeView);
      setActiveTabId(activeTabId);
      void loadToolDashboardTabContent(runtime, activeTabId, activeView, { force: true });
    }
  }, [loadToolDashboardTabContent, registerFileSource]);

  const updateTabContent = useCallback((tabId: EditorTabId, content: string) => {
    setTabs((prev) =>
      prev.map((tab) =>
        tab.id === tabId
          ? {
            ...tab,
            content,
            isDirty: content !== tab.savedContent,
            saveState: "idle" as const,
            saveError: null,
            textContentAccessedAt: Date.now(),
            textContentLoaded: true,
          }
          : tab,
      ),
    );
  }, []);

  const markTabDirty = useCallback((tabId: EditorTabId) => {
    setTabs((prev) =>
      prev.map((tab) =>
        tab.id === tabId && !tab.isDirty
          ? { ...tab, isDirty: true, saveState: "idle" as const, saveError: null }
          : tab,
      ),
    );
  }, []);

  const discardTabChanges = useCallback(async (tabId: EditorTabId) => {
    const current = tabsRef.current.find((tab) => tab.id === tabId);
    if (!current || !current.isDirty) return true;

    const nextTabs = tabsRef.current.map((tab) =>
      tab.id === tabId
        ? {
            ...tab,
            content: tab.savedContent,
            isDirty: false,
            externalChange: null,
            saveState: "idle" as const,
            saveError: null,
          }
        : tab,
    );
    tabsRef.current = nextTabs;
    setTabs(nextTabs);

    const runtime = resolveFileSourceRuntime(current.fileSource);
    const filePath = normalizeWorkspacePath(getTabFilePath(current) ?? "");
    if (current.kind === "text" && !isPinnedDocumentTab(current) && runtime && filePath) {
      await refreshTabContent(tabId, runtime, filePath);
    }
    return true;
  }, [refreshTabContent, resolveFileSourceRuntime]);

  const markTabMissing = useCallback((tabId: EditorTabId) => {
    setTabs((prev) =>
      prev.map((tab) =>
        tab.id === tabId
          ? {
            ...tab,
            isMissing: true,
            saveState: tab.saveState === "saving" ? "saving" : "error",
            saveError: "文件已被删除。",
          }
          : tab,
      ),
    );
  }, []);

  const saveTab = useCallback(async (tabId: EditorTabId, contentSnapshot?: string) => {
    const tab = tabsRef.current.find((item) => item.id === tabId);
    const runtime = tab ? resolveFileSourceRuntime(tab.fileSource) : null;
    const isPinned = isPinnedDocumentTab(tab);
    const sourceKey = isPinned ? getTabSourceKey(tab) : null;
    const filePath = normalizeWorkspacePath(
      getTabFilePath(tab) ?? (isPinned ? TOOL_MANIFEST_FILE : ""),
    );
    if (!tab || tab.kind !== "text" || !runtime || !filePath) return false;
    if (!tab.textContentLoaded) {
      void refreshTabContent(tab.id, runtime, filePath);
      return false;
    }
    const savedSnapshot = contentSnapshot ?? tab.content;

    setTabs((prev) =>
      prev.map((item) =>
        item.id === tabId
          ? {
            ...item,
            content: savedSnapshot,
            isDirty: savedSnapshot !== item.savedContent,
            saveState: "saving" as const,
            saveError: null,
            textContentAccessedAt: Date.now(),
            textContentLoaded: true,
          }
          : item,
      ),
    );

    try {
      const api = runtime.getApi();
      const savedNodes = isPinned
        ? await saveToolDashboardContent(runtime, savedSnapshot, getToolDashboardViewFromTab(tab))
        : [await api.saveTextFile(filePath, savedSnapshot, { expectedMtimeMs: tab.mtimeMs })];
      for (const node of savedNodes) {
        runtime.publishSavedNode?.(node);
      }
      const primaryNode = savedNodes.find((item) => normalizeWorkspacePath(item.path) === filePath) ?? savedNodes[0];
      const savedFilePath = normalizeWorkspacePath(primaryNode.path || filePath);
      const savedMtimeMs = typeof primaryNode.mtime_ms === "number" ? primaryNode.mtime_ms : null;
      if (isPinned) {
        loadedToolDashboardTabIdsRef.current.add(tabId);
      }
      if (isPinned || isToolCatalogMetadataPath(filePath)) {
        publishToolCatalogMetadataChange(runtime.source);
      }
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? {
              ...item,
              content: item.content === savedSnapshot ? savedSnapshot : item.content,
              displayPath: isPinnedDocumentTab(item) ? item.displayPath : savedFilePath,
              filePath: isPinnedDocumentTab(item) ? item.filePath : savedFilePath,
              projectFilePath: isProjectFileSource(item.fileSource, item.projectId)
                ? savedFilePath
                : item.projectFilePath,
              savedContent: savedSnapshot,
              textContentAccessedAt: Date.now(),
              textContentLoaded: true,
              assetVersion: null,
              mtimeMs: savedMtimeMs,
              isDirty: item.content !== savedSnapshot,
              isMissing: false,
              externalChange: null,
              saveState: item.content === savedSnapshot ? "saved" as const : "idle" as const,
              saveError: null,
            }
            : sourceKey && isPinned && isToolDashboardTabForSource(item, sourceKey) && !item.isDirty
              ? invalidateLoadedToolDashboardTab(item, loadedToolDashboardTabIdsRef.current)
            : item,
        ),
      );
      return true;
    } catch (err) {
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? { ...item, saveState: "error" as const, saveError: err instanceof Error ? err.message : "保存失败" }
            : item,
        ),
      );
      return false;
    }
  }, [refreshTabContent, resolveFileSourceRuntime]);

  const overwriteExternalChange = useCallback(async (tabId: EditorTabId) => {
    const tab = tabsRef.current.find((item) => item.id === tabId);
    const runtime = tab ? resolveFileSourceRuntime(tab.fileSource) : null;
    const filePath = normalizeWorkspacePath(getTabFilePath(tab) ?? "");
    if (!tab || tab.kind !== "text" || !runtime || !filePath || !tab.externalChange) return false;

    const contentSnapshot = tab.content;
    setTabs((prev) =>
      prev.map((item) =>
        item.id === tabId
          ? { ...item, saveState: "saving" as const, saveError: null }
          : item,
      ),
    );

    try {
      const savedNode = await runtime.getApi().saveTextFile(filePath, contentSnapshot, {
        expectedMtimeMs: tab.externalChange.mtimeMs,
      });
      runtime.publishSavedNode?.(savedNode);
      const savedFilePath = normalizeWorkspacePath(savedNode.path || filePath);
      const savedMtimeMs = typeof savedNode.mtime_ms === "number" ? savedNode.mtime_ms : null;
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? {
              ...item,
              content: item.content === contentSnapshot ? contentSnapshot : item.content,
              displayPath: savedFilePath,
              filePath: savedFilePath,
              projectFilePath: isProjectFileSource(item.fileSource, item.projectId)
                ? savedFilePath
                : item.projectFilePath,
              savedContent: contentSnapshot,
              textContentAccessedAt: Date.now(),
              textContentLoaded: true,
              assetVersion: null,
              mtimeMs: savedMtimeMs,
              isDirty: item.content !== contentSnapshot,
              isMissing: false,
              externalChange: null,
              saveState: item.content === contentSnapshot ? "saved" as const : "idle" as const,
              saveError: null,
            }
            : item,
        ),
      );
      return true;
    } catch (err) {
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? {
              ...item,
              saveState: "error" as const,
              saveError: err instanceof Error ? err.message : "覆盖保存失败",
            }
            : item,
        ),
      );
      return false;
    }
  }, [resolveFileSourceRuntime]);

  const saveTabAs = useCallback(async (tabId: EditorTabId, targetPathInput: string) => {
    const tab = tabsRef.current.find((item) => item.id === tabId);
    const runtime = tab ? resolveFileSourceRuntime(tab.fileSource) : null;
    const targetPath = normalizeWorkspacePath(targetPathInput);
    if (!tab || tab.kind !== "text" || !runtime || !targetPath) return false;
    if (!tab.textContentLoaded) {
      const filePath = normalizeWorkspacePath(getTabFilePath(tab) ?? "");
      if (filePath) {
        void refreshTabContent(tab.id, runtime, filePath);
      }
      return false;
    }

    setTabs((prev) =>
      prev.map((item) =>
        item.id === tabId
          ? { ...item, saveState: "saving" as const, saveError: null }
          : item,
      ),
    );

    try {
      try {
        await runtime.getApi().readTextFile(targetPath);
        throw new Error("目标文件已存在，请换一个另存路径。");
      } catch (err) {
        if (!(err instanceof HttpRequestError && err.status === 404)) {
          throw err;
        }
      }

      const contentSnapshot = tab.content;
      const savedNode = await runtime.getApi().saveTextFile(targetPath, contentSnapshot);
      runtime.publishSavedNode?.(savedNode);
      const savedFilePath = normalizeWorkspacePath(savedNode.path || targetPath);
      const savedMtimeMs = typeof savedNode.mtime_ms === "number" ? savedNode.mtime_ms : null;
      const nextTabId = makeTabId(runtime.source.key, savedFilePath);
      fileLoadRequestIdsRef.current.delete(tabId);
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? {
              ...item,
              id: nextTabId,
              title: getPathName(savedFilePath),
              displayPath: savedFilePath,
              filePath: savedFilePath,
              projectFilePath: isProjectFileSource(item.fileSource, item.projectId)
                ? savedFilePath
                : item.projectFilePath,
              content: item.content === contentSnapshot ? contentSnapshot : item.content,
              savedContent: contentSnapshot,
              textContentAccessedAt: Date.now(),
              textContentLoaded: true,
              assetVersion: null,
              mtimeMs: savedMtimeMs,
              isDirty: item.content !== contentSnapshot,
              isMissing: false,
              externalChange: null,
              saveState: item.content === contentSnapshot ? "saved" as const : "idle" as const,
              saveError: null,
            }
            : item,
        ),
      );
      if (activeTabIdRef.current === tabId) {
        activeTabIdRef.current = nextTabId;
        setActiveTabId(nextTabId);
      }
      return true;
    } catch (err) {
      setTabs((prev) =>
        prev.map((item) =>
          item.id === tabId
            ? {
              ...item,
              saveState: "error" as const,
              saveError: err instanceof Error ? err.message : "另存失败",
            }
            : item,
        ),
      );
      return false;
    }
  }, [activeTabIdRef, fileLoadRequestIdsRef, refreshTabContent, resolveFileSourceRuntime]);

  const saveActiveTab = useCallback(async () => {
    const id = activeTabIdRef.current;
    if (!id) return false;
    return saveTab(id);
  }, [saveTab]);

  const activeTab = useMemo(
    () => tabs.find((tab) => tab.id === activeTabId) ?? null,
    [activeTabId, tabs],
  );

  useEffect(() => {
    if (!activeTab || activeTab.kind !== "text" || activeTab.textContentLoaded) return;
    if (activeTab.isDirty || activeTab.saveState === "saving") return;

    const runtime = resolveFileSourceRuntime(activeTab.fileSource);
    const filePath = normalizeWorkspacePath(getTabFilePath(activeTab) ?? "");
    if (!runtime || !filePath) return;
    void refreshTabContent(activeTab.id, runtime, filePath);
  }, [
    activeTab?.filePath,
    activeTab?.fileSource,
    activeTab?.id,
    activeTab?.isDirty,
    activeTab?.kind,
    activeTab?.projectFilePath,
    activeTab?.saveState,
    activeTab?.textContentLoaded,
    refreshTabContent,
    resolveFileSourceRuntime,
  ]);

  useEffect(() => {
    setTabs((prev) => pruneDocumentTextContentCache(prev, activeTabId));
  }, [activeTabId, tabs]);

  return useMemo(() => ({
    activeTab,
    activeTabId,
    closeAllTabs,
    closeOtherTabs,
    closeTab,
    discardTabChanges,
    ensureProjectConversationOverview,
    ensureProjectRoleConfiguration,
    ensureProjectThemeConfiguration,
    getSnapshot,
    markTabDirty,
    markTabMissing,
    openNode,
    openToolDashboard,
    openVirtualConversationBranches,
    openVirtualConversationData,
    openVirtualHtmlPreview,
    openVirtualMemoryDashboard,
    openVirtualReferenceViewer,
    openWorkspaceFile,
    renameProjectPath,
    renameWorkspacePath,
    restoreTabs,
    restoreWorkspaceTabs,
    saveActiveTab,
    saveTab,
    saveTabAs,
    selectTab,
    overwriteExternalChange,
    tabs,
    updateTabContent,
  }), [
    activeTab,
    activeTabId,
    closeAllTabs,
    closeOtherTabs,
    closeTab,
    discardTabChanges,
    ensureProjectConversationOverview,
    ensureProjectRoleConfiguration,
    ensureProjectThemeConfiguration,
    getSnapshot,
    markTabDirty,
    markTabMissing,
    openNode,
    openToolDashboard,
    openVirtualConversationBranches,
    openVirtualConversationData,
    openVirtualHtmlPreview,
    openVirtualMemoryDashboard,
    openVirtualReferenceViewer,
    openWorkspaceFile,
    renameProjectPath,
    renameWorkspacePath,
    restoreTabs,
    restoreWorkspaceTabs,
    saveActiveTab,
    saveTab,
    saveTabAs,
    selectTab,
    overwriteExternalChange,
    tabs,
    updateTabContent,
  ]);
}
