import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

import type {
  DocumentFileSource,
  DocumentTab,
  EditorTabId,
} from "../../../entities/editor/model/editorDocument";
import type { FileWorkspaceMutation } from "../../../entities/file-workspace/model/fileWorkspace";
import { HttpRequestError } from "../../../services/http/httpClient";

import {
  createProjectDocumentSource,
  type DocumentFileSourceRuntime,
  isProjectFileSource,
} from "./documentFileSources";
import {
  getPathName,
  getTabFilePath,
  getTabSourceKey,
  isWorkspacePathAffected,
  makeTabId,
  normalizeWorkspacePath,
  resolveRenamedTabId,
} from "./documentTabUtils";
import { decideAssetRefresh } from "./assetRefreshPolicy";

type UseDocumentTabFileSyncOptions = {
  activeTabIdRef: MutableRefObject<EditorTabId | null>;
  fileLoadRequestIdsRef: MutableRefObject<Map<EditorTabId, number>>;
  setActiveTabId: Dispatch<SetStateAction<EditorTabId | null>>;
  setTabs: Dispatch<SetStateAction<DocumentTab[]>>;
  tabs: DocumentTab[];
  tabsRef: MutableRefObject<DocumentTab[]>;
};

export function useDocumentTabFileSync({
  activeTabIdRef,
  fileLoadRequestIdsRef,
  setActiveTabId,
  setTabs,
  tabs,
  tabsRef,
}: UseDocumentTabFileSyncOptions) {
  const fileSourceRuntimesRef = useRef(new Map<string, DocumentFileSourceRuntime>());

  const registerFileSource = useCallback((runtime: DocumentFileSourceRuntime) => {
    fileSourceRuntimesRef.current.set(runtime.source.key, runtime);
    return runtime;
  }, []);

  const resolveFileSourceRuntime = useCallback((source: DocumentFileSource | null) => {
    if (!source) return null;
    const registered = fileSourceRuntimesRef.current.get(source.key);
    if (registered) return registered;
    if (source.kind === "project") {
      return registerFileSource(createProjectDocumentSource(source.id));
    }
    return null;
  }, [registerFileSource]);

  const markDeletedWorkspacePath = useCallback((sourceKey: string, deletedPath: string) => {
    const normalizedDeletedPath = normalizeWorkspacePath(deletedPath);
    if (!normalizedDeletedPath) return;

    setTabs((prev) =>
      prev.map((tab) => {
        if (getTabSourceKey(tab) !== sourceKey || !getTabFilePath(tab)) return tab;
        if (!isWorkspacePathAffected(getTabFilePath(tab) ?? "", [normalizedDeletedPath])) return tab;
        return {
          ...tab,
          isMissing: true,
          saveState: tab.saveState === "saving" ? "saving" : "error",
          saveError: "文件已被删除。",
        };
      }),
    );
  }, [setTabs]);

  const refreshTabContent = useCallback(async (
    tabId: EditorTabId,
    runtime: DocumentFileSourceRuntime,
    filePath: string,
  ) => {
    const normalizedFilePath = normalizeWorkspacePath(filePath);
    if (!normalizedFilePath) return;
    const currentTab = tabsRef.current.find((tab) => tab.id === tabId);
    if (currentTab && currentTab.kind !== "text") return;

    const requestId = (fileLoadRequestIdsRef.current.get(tabId) ?? 0) + 1;
    fileLoadRequestIdsRef.current.set(tabId, requestId);

    try {
      const res = await runtime.getApi().readTextFile(normalizedFilePath);
      const resolvedPath = normalizeWorkspacePath(res.path || normalizedFilePath);
      if (fileLoadRequestIdsRef.current.get(tabId) !== requestId) return;
      setTabs((prev) =>
        prev.map((tab) => {
          if (tab.id !== tabId) return tab;
          if (
            getTabSourceKey(tab) !== runtime.source.key ||
            normalizeWorkspacePath(getTabFilePath(tab) ?? "") !== normalizedFilePath
          ) {
            return tab;
          }
          if (tab.isDirty && res.content === tab.savedContent && res.content !== tab.content) {
            return {
              ...tab,
              displayPath: resolvedPath,
              filePath: resolvedPath,
              mtimeMs: res.mtime_ms,
              projectFilePath: isProjectFileSource(tab.fileSource, tab.projectId)
                ? resolvedPath
                : tab.projectFilePath,
              isMissing: false,
            };
          }
          if (tab.isDirty && res.content !== tab.content) {
            return {
              ...tab,
              displayPath: resolvedPath,
              filePath: resolvedPath,
              mtimeMs: res.mtime_ms,
              projectFilePath: isProjectFileSource(tab.fileSource, tab.projectId)
                ? resolvedPath
                : tab.projectFilePath,
              externalChange: {
                kind: "conflict" as const,
                detectedAt: Date.now(),
                filePath: resolvedPath,
                mtimeMs: res.mtime_ms,
              },
              isMissing: false,
              saveState: "error" as const,
              saveError: "磁盘文件已在外部发生变化，请选择覆盖原文件或另存当前内容。",
            };
          }
          return {
            ...tab,
            content: res.content,
            displayPath: resolvedPath,
            filePath: resolvedPath,
            mtimeMs: res.mtime_ms,
            assetVersion: null,
            projectFilePath: isProjectFileSource(tab.fileSource, tab.projectId)
              ? resolvedPath
              : tab.projectFilePath,
            savedContent: res.content,
            textContentAccessedAt: Date.now(),
            textContentLoaded: true,
            isDirty: false,
            isMissing: false,
            externalChange: null,
            saveState: "idle" as const,
            saveError: null,
          };
        }),
      );
    } catch (err) {
      if (err instanceof HttpRequestError && err.status === 404) {
        markDeletedWorkspacePath(runtime.source.key, normalizedFilePath);
      }
    }
  }, [fileLoadRequestIdsRef, markDeletedWorkspacePath, setTabs]);

  const refreshChangedWorkspaceFiles = useCallback((
    sourceKey: string,
    changedPaths: string[],
  ) => {
    const runtime = fileSourceRuntimesRef.current.get(sourceKey);
    if (!runtime) return;

    const normalizedChangedPaths = changedPaths
      .map(normalizeWorkspacePath)
      .filter(Boolean);
    const hasDetailedChange = normalizedChangedPaths.length > 0;
    const candidateTabs = tabsRef.current.filter((tab) => {
      const filePath = getTabFilePath(tab);
      if (getTabSourceKey(tab) !== sourceKey || !filePath) return false;
      return isWorkspacePathAffected(filePath, normalizedChangedPaths);
    });

    const assetRefreshCandidates: Array<{
      filePath: string;
      mtimeMs: number | null;
      tabId: EditorTabId;
    }> = [];
    for (const tab of candidateTabs) {
      const filePath = getTabFilePath(tab);
      if (tab.kind === "text" && filePath) {
        if (!tab.textContentLoaded && !tab.isDirty && tab.id !== activeTabIdRef.current) {
          continue;
        }
        void refreshTabContent(tab.id, runtime, filePath);
      } else if (tab.kind !== "text" && filePath) {
        assetRefreshCandidates.push({ filePath, mtimeMs: tab.mtimeMs, tabId: tab.id });
      }
    }

    if (assetRefreshCandidates.length > 0) {
      void (async () => {
        const existingTabIds = new Set<EditorTabId>();
        const refreshedTabMtimes = new Map<EditorTabId, number>();
        const metadataOnlyTabMtimes = new Map<EditorTabId, number>();
        for (const candidate of assetRefreshCandidates) {
          const metadata = await workspaceFileMetadata(runtime, candidate.filePath);
          const decision = decideAssetRefresh({
            currentMtimeMs: candidate.mtimeMs,
            hasDetailedChange,
            metadata,
          });
          if (decision.kind === "mark-missing") {
            markDeletedWorkspacePath(runtime.source.key, candidate.filePath);
          } else if (decision.kind === "record-mtime") {
            metadataOnlyTabMtimes.set(candidate.tabId, decision.mtimeMs);
          } else if (decision.kind === "refresh") {
            existingTabIds.add(candidate.tabId);
            if (typeof decision.mtimeMs === "number") {
              refreshedTabMtimes.set(candidate.tabId, decision.mtimeMs);
            }
          }
        }
        if (existingTabIds.size === 0 && metadataOnlyTabMtimes.size === 0) return;

        const nextAssetVersion = Date.now();
        setTabs((prev) =>
          prev.map((tab) => {
            const metadataOnlyMtime = metadataOnlyTabMtimes.get(tab.id);
            if (typeof metadataOnlyMtime === "number") {
              return {
                ...tab,
                mtimeMs: metadataOnlyMtime,
              };
            }
            return existingTabIds.has(tab.id)
              ? {
                ...tab,
                assetVersion: nextAssetVersion,
                isMissing: false,
                mtimeMs: refreshedTabMtimes.get(tab.id) ?? tab.mtimeMs,
                saveError: null,
                saveState: tab.saveState === "saving" ? tab.saveState : ("idle" as const),
              }
              : tab;
          }),
        );
      })();
    }
  }, [markDeletedWorkspacePath, refreshTabContent, setTabs, tabsRef]);

  const renameWorkspacePath = useCallback((
    sourceKey: string,
    previousPath: string,
    nextPath: string,
  ) => {
    const normalizedPreviousPath = normalizeWorkspacePath(previousPath);
    const normalizedNextPath = normalizeWorkspacePath(nextPath);
    if (!normalizedPreviousPath || !normalizedNextPath) return;

    const previousPrefix = `${normalizedPreviousPath}/`;
    const activeTab = tabsRef.current.find((tab) => tab.id === activeTabIdRef.current);
    const activeFilePath = activeTab && getTabSourceKey(activeTab) === sourceKey
      ? normalizeWorkspacePath(getTabFilePath(activeTab) ?? "")
      : null;
    const nextActiveTabId = activeFilePath
      ? resolveRenamedTabId(sourceKey, activeFilePath, normalizedPreviousPath, normalizedNextPath)
      : activeTabIdRef.current;

    const nextTabs = tabsRef.current.map((tab) => {
      if (getTabSourceKey(tab) !== sourceKey) {
        return tab;
      }

      const normalizedTabPath = normalizeWorkspacePath(getTabFilePath(tab) ?? "");
      const isExactMatch = normalizedTabPath === normalizedPreviousPath;
      const isChildMatch = normalizedTabPath.startsWith(previousPrefix);
      if (!isExactMatch && !isChildMatch) {
        return tab;
      }

      const renamedPath = isExactMatch
        ? normalizedNextPath
        : `${normalizedNextPath}/${normalizedTabPath.slice(previousPrefix.length)}`;
      const renamedId = makeTabId(sourceKey, renamedPath);

      return {
        ...tab,
        id: renamedId,
        title: getPathName(renamedPath),
        displayPath: renamedPath,
        filePath: renamedPath,
        projectFilePath: isProjectFileSource(tab.fileSource, tab.projectId)
          ? renamedPath
          : tab.projectFilePath,
      };
    });

    tabsRef.current = nextTabs;
    setTabs(nextTabs);

    if (nextActiveTabId && nextActiveTabId !== activeTabIdRef.current) {
      activeTabIdRef.current = nextActiveTabId;
      setActiveTabId(nextActiveTabId);
    }
  }, [activeTabIdRef, setActiveTabId, setTabs, tabsRef]);

  const applyWorkspaceMutation = useCallback((mutation: FileWorkspaceMutation) => {
    if (mutation.action === "delete") {
      markDeletedWorkspacePath(mutation.workspaceKey, mutation.path);
      return;
    }
    if (mutation.action === "move") {
      renameWorkspacePath(mutation.workspaceKey, mutation.previousPath, mutation.node.path);
      return;
    }
    refreshChangedWorkspaceFiles(mutation.workspaceKey, [mutation.node.path]);
  }, [markDeletedWorkspacePath, refreshChangedWorkspaceFiles, renameWorkspacePath]);

  const watchedSourceKeysKey = useMemo(() => Array.from(
    new Set(
      tabs
        .map(getTabSourceKey)
        .filter((sourceKey): sourceKey is string => Boolean(sourceKey)),
    ),
  ).sort().join("\n"), [tabs]);

  useEffect(() => {
    if (!watchedSourceKeysKey) return undefined;
    const sourceKeys = watchedSourceKeysKey.split("\n");
    const unwatchers = sourceKeys.map((sourceKey) => {
      const runtime = fileSourceRuntimesRef.current.get(sourceKey);
      return runtime?.watchFileEvents?.({
        onChanged: (changedPaths) => refreshChangedWorkspaceFiles(sourceKey, changedPaths),
        onOverflow: () => refreshChangedWorkspaceFiles(sourceKey, []),
      }) ?? (() => undefined);
    });
    return () => {
      for (const unwatch of unwatchers) {
        unwatch();
      }
    };
  }, [refreshChangedWorkspaceFiles, watchedSourceKeysKey]);

  useEffect(() => {
    if (!watchedSourceKeysKey) return undefined;
    const sourceKeys = watchedSourceKeysKey.split("\n");
    const unsubscribers = sourceKeys.map((sourceKey) => {
      const runtime = fileSourceRuntimesRef.current.get(sourceKey);
      return runtime?.subscribeMutations?.(applyWorkspaceMutation) ?? (() => undefined);
    });
    return () => {
      for (const unsubscribe of unsubscribers) {
        unsubscribe();
      }
    };
  }, [applyWorkspaceMutation, watchedSourceKeysKey]);

  return {
    refreshTabContent,
    registerFileSource,
    renameWorkspacePath,
    resolveFileSourceRuntime,
  };
}

async function workspaceFileMetadata(
  runtime: DocumentFileSourceRuntime,
  filePath: string,
): Promise<{ exists: boolean | null; mtimeMs: number | null }> {
  const normalizedPath = normalizeWorkspacePath(filePath);
  if (!normalizedPath) return { exists: false, mtimeMs: null };

  try {
    const tree = await runtime.getApi().listTree({
      parentPath: getWorkspaceParentPath(normalizedPath),
    });
    const item = tree.items.find((candidate) => normalizeWorkspacePath(candidate.path) === normalizedPath);
    return {
      exists: Boolean(item),
      mtimeMs: typeof item?.mtime_ms === "number" ? item.mtime_ms : null,
    };
  } catch (err) {
    if (err instanceof HttpRequestError && (err.status === 400 || err.status === 404)) {
      return { exists: false, mtimeMs: null };
    }
    return { exists: null, mtimeMs: null };
  }
}

function getWorkspaceParentPath(filePath: string): string | null {
  const normalizedPath = normalizeWorkspacePath(filePath);
  if (!normalizedPath) return null;
  const slashIndex = normalizedPath.lastIndexOf("/");
  return slashIndex > 0 ? normalizedPath.slice(0, slashIndex) : null;
}
