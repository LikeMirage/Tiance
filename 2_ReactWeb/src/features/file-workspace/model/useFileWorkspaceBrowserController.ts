import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type {
  FileWorkspaceEntryKind,
  FileWorkspaceMutation,
} from "../../../entities/file-workspace/model/fileWorkspace";
import { isAbortError } from "../../../services/http/httpErrors";
import type { FileWorkspaceApi } from "./fileWorkspaceApi";
import { getFileWorkspaceTreeWithTimeout } from "./fileWorkspaceBrowserFileLoader";
import type {
  LoadFolderChildrenOptions,
  LoadRootOptions,
  PendingCreateRequest,
} from "./fileWorkspaceBrowserControllerTypes";
import {
  isCurrentWorkspaceRequest,
  sortExpandedFolderIds,
} from "./fileWorkspaceBrowserRequestUtils";
import { useFileWorkspaceBrowserSelection } from "./useFileWorkspaceBrowserSelection";
import {
  collectAllFolderIds,
  findNode,
  mapFileWorkspaceNode,
  preserveLoadedChildren,
  updateNodeChildren,
} from "./fileWorkspaceBrowserTreeModel";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";
import type { UseFileWorkspaceBrowserResult } from "./fileWorkspaceBrowserTypes";
import { useFileWorkspaceExternalSync } from "./useFileWorkspaceExternalSync";
import { useFileWorkspaceBrowserFileActions } from "./useFileWorkspaceBrowserFileActions";

type FileWorkspaceWatchHandlers = {
  onChanged: (paths: string[]) => void;
  onOverflow?: () => void;
  onStatusChanged?: (available: boolean) => void;
};

type UseFileWorkspaceBrowserControllerOptions = {
  fileWorkspaceApi: FileWorkspaceApi | null;
  initialExpandedPaths?: string[];
  initialTreeData?: FileWorkspaceBrowserNode[];
  publishMutation?: (mutation: FileWorkspaceMutation) => void;
  subscribeMutations?: (handler: (mutation: FileWorkspaceMutation) => void) => () => void;
  watchFileEvents?: (handlers: FileWorkspaceWatchHandlers) => () => void;
};

export function useFileWorkspaceBrowserController({
  fileWorkspaceApi,
  initialExpandedPaths,
  initialTreeData,
  publishMutation,
  subscribeMutations,
  watchFileEvents,
}: UseFileWorkspaceBrowserControllerOptions): UseFileWorkspaceBrowserResult {
  const workspaceKey = fileWorkspaceApi?.workspaceKey ?? null;
  const [treeData, setTreeData] = useState<FileWorkspaceBrowserNode[]>(initialTreeData ?? []);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [watchErrorMessage, setWatchErrorMessage] = useState<string | null>(null);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const {
    commitSelection,
    resetSelection,
    selectedNodeId,
    selectedNodeIds,
    selectedNodeIdsRef,
    selectNode,
    selectRoot,
  } = useFileWorkspaceBrowserSelection();

  const treeDataRef = useRef<FileWorkspaceBrowserNode[]>([]);
  const activeWorkspaceKeyRef = useRef(workspaceKey);
  const searchKeywordRef = useRef(searchKeyword);
  const expandedNodeIdsRef = useRef<Set<string>>(new Set(initialExpandedPaths ?? []));
  const userExpandedNodeIdsRef = useRef<Set<string>>(new Set(initialExpandedPaths ?? []));
  const loadingNodeIdsRef = useRef<Set<string>>(new Set());
  const requestIdRef = useRef(0);
  const revealRequestIdRef = useRef(0);
  const expandedRestoreRequestIdRef = useRef(0);
  const editingNodeIdRef = useRef<string | null>(null);
  const mutationSourceIdRef = useRef(`file_workspace_browser_${crypto.randomUUID()}`);
  const createEntryRef = useRef<(
    kind: FileWorkspaceEntryKind,
    parentNodeId?: string,
  ) => Promise<void>>(async () => undefined);
  const pendingCreateRef = useRef<PendingCreateRequest | null>(null);
  const loadRootRef = useRef<(options?: LoadRootOptions) => Promise<void>>(async () => undefined);
  const rootAbortControllerRef = useRef<AbortController | null>(null);
  const isRootLoadingRef = useRef(false);
  const hasHydratedWorkspaceRef = useRef(false);
  const skipNextRootLoadRef = useRef(initialTreeData !== undefined);
  const pendingRootRefreshRef = useRef(false);
  const pendingWatchPathsRef = useRef<Set<string>>(new Set());
  const pendingWatchRefreshRef = useRef(false);
  const pendingWatchOverflowRef = useRef(false);
  const watchRefreshTimerRef = useRef<number | null>(null);

  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(expandedNodeIdsRef.current);
  const [userExpandedNodeIds, setUserExpandedNodeIds] = useState<Set<string>>(userExpandedNodeIdsRef.current);
  const [isLoadingNodeIds, setIsLoadingNodeIds] = useState<Set<string>>(loadingNodeIdsRef.current);
  const initialExpandedPathsKey = (initialExpandedPaths ?? []).join("\n");

  useEffect(() => {
    editingNodeIdRef.current = editingNodeId;
  }, [editingNodeId]);

  useEffect(() => {
    treeDataRef.current = treeData;
  }, [treeData]);

  useEffect(() => {
    searchKeywordRef.current = searchKeyword;
  }, [searchKeyword]);

  useLayoutEffect(() => {
    const isSameWorkspace =
      hasHydratedWorkspaceRef.current && activeWorkspaceKeyRef.current === workspaceKey;
    const hasInitialTreeData = Boolean(workspaceKey && initialTreeData !== undefined);
    if (isSameWorkspace && !hasInitialTreeData) {
      return;
    }

    hasHydratedWorkspaceRef.current = true;
    activeWorkspaceKeyRef.current = workspaceKey;
    requestIdRef.current += 1;
    revealRequestIdRef.current += 1;
    expandedRestoreRequestIdRef.current += 1;
    rootAbortControllerRef.current?.abort();
    rootAbortControllerRef.current = null;
    isRootLoadingRef.current = false;
    pendingRootRefreshRef.current = false;
    pendingWatchPathsRef.current.clear();
    pendingWatchRefreshRef.current = false;
    pendingWatchOverflowRef.current = false;
    if (watchRefreshTimerRef.current) {
      window.clearTimeout(watchRefreshTimerRef.current);
      watchRefreshTimerRef.current = null;
    }
    loadingNodeIdsRef.current = new Set();
    const hydratedTreeData = initialTreeData ?? [];
    skipNextRootLoadRef.current = hasInitialTreeData;
    setIsLoading(Boolean(workspaceKey) && !hasInitialTreeData);
    setIsLoadingNodeIds(new Set());
    setErrorMessage(null);
    resetSelection();
    setTreeData(hydratedTreeData);
    treeDataRef.current = hydratedTreeData;
  }, [initialTreeData, resetSelection, workspaceKey]);

  const commitTreeData = useCallback((nextTreeData: FileWorkspaceBrowserNode[]) => {
    treeDataRef.current = nextTreeData;
    setTreeData(nextTreeData);
  }, []);

  const updateTreeData = useCallback((
    updater: (currentTreeData: FileWorkspaceBrowserNode[]) => FileWorkspaceBrowserNode[],
  ) => {
    setTreeData((currentTreeData) => {
      const nextTreeData = updater(currentTreeData);
      treeDataRef.current = nextTreeData;
      return nextTreeData;
    });
  }, []);

  const commitExpandedNodeIds = useCallback((
    nextExpandedNodeIds: Set<string>,
    options: { persistAsUser?: boolean } = {},
  ) => {
    expandedNodeIdsRef.current = nextExpandedNodeIds;
    setExpandedNodeIds(new Set(nextExpandedNodeIds));
    const shouldPersistAsUser =
      options.persistAsUser ?? !searchKeywordRef.current.trim();
    if (shouldPersistAsUser) {
      userExpandedNodeIdsRef.current = new Set(nextExpandedNodeIds);
      setUserExpandedNodeIds(new Set(nextExpandedNodeIds));
    }
  }, []);

  const publishLocalMutation = useCallback((mutation: FileWorkspaceMutation) => {
    publishMutation?.({
      ...mutation,
      sourceId: mutation.sourceId ?? mutationSourceIdRef.current,
    });
  }, [publishMutation]);

  const prepareInlineCreate = useCallback(() => {
    requestIdRef.current += 1;
    revealRequestIdRef.current += 1;
    expandedRestoreRequestIdRef.current += 1;
    rootAbortControllerRef.current?.abort();
    rootAbortControllerRef.current = null;
    isRootLoadingRef.current = false;
    setIsLoading(false);
  }, []);

  const addExpandedNodeId = useCallback((nodeId: string) => {
    const nextExpandedNodeIds = new Set(expandedNodeIdsRef.current);
    nextExpandedNodeIds.add(nodeId);
    commitExpandedNodeIds(nextExpandedNodeIds);
  }, [commitExpandedNodeIds]);

  const setNodeLoading = useCallback((nodeId: string, nextIsLoading: boolean) => {
    const next = new Set(loadingNodeIdsRef.current);
    if (nextIsLoading) {
      next.add(nodeId);
    } else {
      next.delete(nodeId);
    }
    loadingNodeIdsRef.current = next;
    setIsLoadingNodeIds(new Set(next));
  }, []);

  const loadFolderChildrenNode = useCallback(async (
    node: FileWorkspaceBrowserNode,
    loadOptions: LoadFolderChildrenOptions = {},
  ): Promise<FileWorkspaceBrowserNode[] | null> => {
    if (!fileWorkspaceApi || !workspaceKey || node.kind !== "folder") return null;

    if (!loadOptions.silent) {
      setNodeLoading(node.id, true);
    }

    try {
      const response = await getFileWorkspaceTreeWithTimeout(
        fileWorkspaceApi,
        { parentPath: node.path },
      );
      if (activeWorkspaceKeyRef.current !== workspaceKey) return null;
      if (loadOptions.shouldApply && !loadOptions.shouldApply()) return null;
      if (hasPendingCreateNode(treeDataRef.current)) {
        pendingRootRefreshRef.current = true;
        return null;
      }
      const children = response.items.map(mapFileWorkspaceNode);
      const nextTreeData = updateNodeChildren(
        loadOptions.sourceNodes ?? treeDataRef.current,
        node.id,
        children,
        true,
      );
      commitTreeData(nextTreeData);
      setErrorMessage(null);
      return nextTreeData;
    } catch (err) {
      if (activeWorkspaceKeyRef.current === workspaceKey) {
        setErrorMessage(
          err instanceof Error
            ? err.message
            : loadOptions.errorMessage ?? "文件夹加载失败。",
        );
      }
      return null;
    } finally {
      if (!loadOptions.silent && activeWorkspaceKeyRef.current === workspaceKey) {
        setNodeLoading(node.id, false);
      }
    }
  }, [commitTreeData, fileWorkspaceApi, setNodeLoading, workspaceKey]);

  const restoreExpandedFolders = useCallback(async (
    sourceNodes?: FileWorkspaceBrowserNode[],
  ) => {
    if (!workspaceKey || searchKeywordRef.current.trim()) return;

    const restoreRequestId = ++expandedRestoreRequestIdRef.current;
    let nodes = sourceNodes ?? treeDataRef.current;
    const expandedFolderIds = sortExpandedFolderIds(expandedNodeIdsRef.current);

    for (const nodeId of expandedFolderIds) {
      if (
        restoreRequestId !== expandedRestoreRequestIdRef.current ||
        activeWorkspaceKeyRef.current !== workspaceKey
      ) {
        return;
      }

      const node = findNode(nodes, nodeId);
      if (!node || node.kind !== "folder" || node.isChildrenLoaded) {
        continue;
      }

      const loadedNodes = await loadFolderChildrenNode(node, {
        errorMessage: "展开状态恢复失败。",
        shouldApply: () =>
          restoreRequestId === expandedRestoreRequestIdRef.current &&
          activeWorkspaceKeyRef.current === workspaceKey,
        sourceNodes: nodes,
      });
      if (!loadedNodes) {
        return;
      }
      nodes = loadedNodes;
    }
  }, [loadFolderChildrenNode, workspaceKey]);

  // 加载根层
  const loadRoot = useCallback(async (options: LoadRootOptions = {}) => {
    if (!fileWorkspaceApi || !workspaceKey) return;
    const shouldReloadExpandedChildren = options.reloadExpandedChildren ?? true;
    if (isRootLoadingRef.current) {
      if (!options.restart) {
        pendingRootRefreshRef.current = true;
        return;
      }
      rootAbortControllerRef.current?.abort();
    }
    isRootLoadingRef.current = true;
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    rootAbortControllerRef.current = controller;
    setIsLoading(true);
    setErrorMessage(null);

    try {
      const response = await getFileWorkspaceTreeWithTimeout(
        fileWorkspaceApi,
        { query: searchKeyword || undefined },
        { signal: controller.signal },
      );
      if (!isCurrentWorkspaceRequest(workspaceKey, activeWorkspaceKeyRef, requestId, requestIdRef)) return;
      if (rootAbortControllerRef.current !== controller) return;
      if (hasPendingCreateNode(treeDataRef.current)) {
        pendingRootRefreshRef.current = true;
        return;
      }

      const nodes = response.items.map(mapFileWorkspaceNode);
      const loadedNodes = shouldReloadExpandedChildren
        ? nodes
        : preserveLoadedChildren(nodes, treeDataRef.current);
      commitTreeData(loadedNodes);

      if (searchKeyword) {
        const allFolderIds = new Set<string>();
        collectAllFolderIds(loadedNodes, allFolderIds);
        commitExpandedNodeIds(allFolderIds, { persistAsUser: false });
      } else if (shouldReloadExpandedChildren) {
        commitExpandedNodeIds(new Set(userExpandedNodeIdsRef.current), {
          persistAsUser: false,
        });
        await restoreExpandedFolders(loadedNodes);
      }
    } catch (err) {
      if (!isCurrentWorkspaceRequest(workspaceKey, activeWorkspaceKeyRef, requestId, requestIdRef)) return;
      if (isAbortError(err)) return;
      setErrorMessage(err instanceof Error ? err.message : "文件列表加载失败。");
    } finally {
      if (rootAbortControllerRef.current !== controller) return;
      rootAbortControllerRef.current = null;
      isRootLoadingRef.current = false;
      if (isCurrentWorkspaceRequest(workspaceKey, activeWorkspaceKeyRef, requestId, requestIdRef)) {
        setIsLoading(false);
      }
      if (
        pendingRootRefreshRef.current &&
        activeWorkspaceKeyRef.current === workspaceKey &&
        !editingNodeIdRef.current
      ) {
        pendingRootRefreshRef.current = false;
        window.setTimeout(() => {
          void loadRootRef.current({ reloadExpandedChildren: false });
        }, 0);
      }
    }
  }, [
    commitExpandedNodeIds,
    commitTreeData,
    fileWorkspaceApi,
    restoreExpandedFolders,
    searchKeyword,
    workspaceKey,
  ]);

  useEffect(() => {
    loadRootRef.current = loadRoot;
  }, [loadRoot]);

  useEffect(() => {
    const nextExpandedNodeIds = new Set(initialExpandedPaths ?? []);
    userExpandedNodeIdsRef.current = new Set(nextExpandedNodeIds);
    expandedNodeIdsRef.current = nextExpandedNodeIds;
    setUserExpandedNodeIds(new Set(nextExpandedNodeIds));
    setExpandedNodeIds(new Set(nextExpandedNodeIds));
    void restoreExpandedFolders();
  }, [initialExpandedPathsKey, restoreExpandedFolders, workspaceKey]);

  useEffect(() => {
    if (skipNextRootLoadRef.current) {
      skipNextRootLoadRef.current = false;
      return;
    }
    void loadRoot({ restart: true });
  }, [loadRoot]);

  const { refreshLoadedTree } = useFileWorkspaceExternalSync({
    activeWorkspaceKeyRef,
    editingNodeId,
    editingNodeIdRef,
    expandedNodeIdsRef,
    loadFolderChildrenNode,
    loadRoot,
    loadRootRef,
    mutationSourceIdRef,
    pendingWatchPathsRef,
    pendingWatchOverflowRef,
    pendingWatchRefreshRef,
    searchKeywordRef,
    setErrorMessage,
    setWatchErrorMessage,
    subscribeMutations,
    treeDataRef,
    updateTreeData,
    watchFileEvents,
    watchRefreshTimerRef,
    workspaceKey,
  });
  useEffect(() => {
    return () => {
      if (watchRefreshTimerRef.current) {
        window.clearTimeout(watchRefreshTimerRef.current);
      }
      rootAbortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (editingNodeId || !pendingRootRefreshRef.current) return;
    pendingRootRefreshRef.current = false;
    void loadRootRef.current({ reloadExpandedChildren: false });
  }, [editingNodeId]);

  const browserFileActions = useFileWorkspaceBrowserFileActions({
    activeWorkspaceKeyRef,
    addExpandedNodeId,
    commitExpandedNodeIds,
    commitSelection,
    commitTreeData,
    createEntryRef,
    editingNodeIdRef,
    expandedNodeIdsRef,
    loadFolderChildrenNode,
    pendingCreateRef,
    fileWorkspaceApi,
    prepareInlineCreate,
    publishMutation: publishLocalMutation,
    revealRequestIdRef,
    searchKeyword,
    selectedNodeId,
    selectedNodeIdsRef,
    setEditingNodeId,
    setErrorMessage,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  });
  const refreshTree = useCallback(() => {
    void refreshLoadedTree();
  }, [refreshLoadedTree]);
  const restoreExpandedPaths = useCallback((paths: string[]) => {
    const nextExpandedNodeIds = new Set(paths);
    commitExpandedNodeIds(nextExpandedNodeIds, { persistAsUser: true });
    void restoreExpandedFolders();
  }, [commitExpandedNodeIds, restoreExpandedFolders]);

  // This browser object is passed through the recursive file tree. When adding
  // a returned field, keep the dependency list in sync so unchanged nodes stay memoized.
  return useMemo(() => ({
    cancelInlineEdit: browserFileActions.cancelInlineEdit,
    copyNode: browserFileActions.copyNode,
    createFile: browserFileActions.createFile,
    createFolder: browserFileActions.createFolder,
    deleteNode: browserFileActions.deleteNode,
    editingNodeId,
    errorMessage: errorMessage ?? watchErrorMessage,
    expandedNodeIds,
    isLoading,
    isLoadingNodeIds,
    loadFolderChildren: browserFileActions.loadFolderChildren,
    moveNode: browserFileActions.moveNode,
    revealNode: browserFileActions.revealNode,
    revealPath: browserFileActions.revealPath,
    refreshTree,
    renameNode: browserFileActions.renameNode,
    restoreExpandedPaths,
    searchKeyword,
    selectNode,
    selectRoot,
    selectedNodeId,
    selectedNodeIds,
    setSearchKeyword,
    startInlineEdit: browserFileActions.startInlineEdit,
    toggleNode: browserFileActions.toggleNode,
    treeData,
    userExpandedNodeIds,
  }), [
    browserFileActions.cancelInlineEdit,
    browserFileActions.copyNode,
    browserFileActions.createFile,
    browserFileActions.createFolder,
    browserFileActions.deleteNode,
    browserFileActions.moveNode,
    browserFileActions.revealNode,
    browserFileActions.revealPath,
    browserFileActions.renameNode,
    browserFileActions.startInlineEdit,
    browserFileActions.toggleNode,
    editingNodeId,
    errorMessage,
    watchErrorMessage,
    expandedNodeIds,
    isLoading,
    isLoadingNodeIds,
    browserFileActions.loadFolderChildren,
    refreshTree,
    restoreExpandedPaths,
    searchKeyword,
    selectNode,
    selectRoot,
    selectedNodeId,
    selectedNodeIds,
    setSearchKeyword,
    treeData,
    userExpandedNodeIds,
  ]);
}

function hasPendingCreateNode(nodes: FileWorkspaceBrowserNode[]): boolean {
  for (const node of nodes) {
    if (node.isPendingCreate) return true;
    if (node.children.length > 0 && hasPendingCreateNode(node.children)) {
      return true;
    }
  }
  return false;
}
