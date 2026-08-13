import { useCallback, useEffect, type Dispatch, type RefObject, type SetStateAction } from "react";

import type { FileWorkspaceMutation } from "../../../entities/file-workspace/model/fileWorkspace";
import {
  findNode,
  getParentWorkspacePath,
  mapFileWorkspaceNode,
  removeNode,
  upsertNode,
} from "./fileWorkspaceBrowserTreeModel";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";
import type { LoadFolderChildrenOptions, LoadRootOptions } from "./fileWorkspaceBrowserControllerTypes";
import { sortExpandedFolderIds } from "./fileWorkspaceBrowserRequestUtils";

type FileWorkspaceWatchHandlers = {
  onChanged: (paths: string[]) => void;
  onOverflow?: () => void;
  onStatusChanged?: (available: boolean) => void;
};

type UseFileWorkspaceExternalSyncInput = {
  activeWorkspaceKeyRef: RefObject<string | null>;
  editingNodeId: string | null;
  editingNodeIdRef: RefObject<string | null>;
  expandedNodeIdsRef: RefObject<Set<string>>;
  loadFolderChildrenNode: (
    node: FileWorkspaceBrowserNode,
    options?: LoadFolderChildrenOptions,
  ) => Promise<FileWorkspaceBrowserNode[] | null>;
  loadRoot: (options?: LoadRootOptions) => Promise<void>;
  loadRootRef: RefObject<(options?: LoadRootOptions) => Promise<void>>;
  mutationSourceIdRef: RefObject<string>;
  pendingWatchPathsRef: RefObject<Set<string>>;
  pendingWatchOverflowRef: RefObject<boolean>;
  pendingWatchRefreshRef: RefObject<boolean>;
  searchKeywordRef: RefObject<string>;
  setErrorMessage: (message: string | null) => void;
  setWatchErrorMessage: Dispatch<SetStateAction<string | null>>;
  subscribeMutations?: (handler: (mutation: FileWorkspaceMutation) => void) => () => void;
  treeDataRef: RefObject<FileWorkspaceBrowserNode[]>;
  updateTreeData: (
    updater: (currentTreeData: FileWorkspaceBrowserNode[]) => FileWorkspaceBrowserNode[],
  ) => void;
  watchFileEvents?: (handlers: FileWorkspaceWatchHandlers) => () => void;
  watchRefreshTimerRef: RefObject<number | null>;
  workspaceKey: string | null;
};

export function useFileWorkspaceExternalSync({
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
}: UseFileWorkspaceExternalSyncInput) {
  const refreshChangedPaths = useCallback(async (changedPaths: string[]) => {
    if (!workspaceKey) return;

    const parentPaths = new Set<string | null>();
    for (const path of changedPaths) {
      parentPaths.add(getParentWorkspacePath(path));
    }
    if (parentPaths.size === 0) return;

    if (parentPaths.has(null)) {
      await loadRootRef.current({ reloadExpandedChildren: false });
      if (activeWorkspaceKeyRef.current !== workspaceKey) return;
      parentPaths.delete(null);
    }

    for (const parentPath of parentPaths) {
      if (!parentPath) continue;
      const parentNode = findNode(treeDataRef.current, parentPath);
      if (
        !parentNode ||
        parentNode.kind !== "folder" ||
        !parentNode.isChildrenLoaded ||
        !expandedNodeIdsRef.current.has(parentPath)
      ) {
        continue;
      }
      await loadFolderChildrenNode(parentNode, { errorMessage: "文件夹刷新失败。" });
    }
  }, [activeWorkspaceKeyRef, expandedNodeIdsRef, loadFolderChildrenNode, loadRootRef, treeDataRef, workspaceKey]);

  const refreshLoadedTree = useCallback(async () => {
    if (!workspaceKey) return;

    await loadRoot({ restart: true, reloadExpandedChildren: false });
    if (activeWorkspaceKeyRef.current !== workspaceKey || searchKeywordRef.current.trim()) return;

    const expandedFolderIds = sortExpandedFolderIds(expandedNodeIdsRef.current);
    for (const nodeId of expandedFolderIds) {
      if (activeWorkspaceKeyRef.current !== workspaceKey) return;
      const node = findNode(treeDataRef.current, nodeId);
      if (!node || node.kind !== "folder" || !node.isChildrenLoaded) continue;
      await loadFolderChildrenNode(node, {
        errorMessage: "文件夹刷新失败。",
        silent: true,
      });
    }
  }, [
    activeWorkspaceKeyRef,
    expandedNodeIdsRef,
    loadFolderChildrenNode,
    loadRoot,
    searchKeywordRef,
    treeDataRef,
    workspaceKey,
  ]);

  const flushWatchRefresh = useCallback(() => {
    if (editingNodeIdRef.current) {
      pendingWatchRefreshRef.current = true;
      return;
    }

    if (pendingWatchOverflowRef.current) {
      pendingWatchOverflowRef.current = false;
      pendingWatchPathsRef.current.clear();
      void refreshLoadedTree();
      return;
    }

    const changedPaths = [...pendingWatchPathsRef.current];
    pendingWatchPathsRef.current.clear();
    if (changedPaths.length === 0 || searchKeywordRef.current.trim()) {
      void loadRootRef.current({ reloadExpandedChildren: false });
      return;
    }
    void refreshChangedPaths(changedPaths);
  }, [
    editingNodeIdRef,
    loadRootRef,
    pendingWatchPathsRef,
    pendingWatchOverflowRef,
    pendingWatchRefreshRef,
    refreshChangedPaths,
    refreshLoadedTree,
    searchKeywordRef,
  ]);

  const scheduleWatchRefresh = useCallback((changedPaths: string[] = []) => {
    for (const path of changedPaths) {
      pendingWatchPathsRef.current.add(path);
    }
    if (editingNodeIdRef.current) {
      pendingWatchRefreshRef.current = true;
      return;
    }
    if (watchRefreshTimerRef.current) {
      window.clearTimeout(watchRefreshTimerRef.current);
    }
    watchRefreshTimerRef.current = window.setTimeout(() => {
      watchRefreshTimerRef.current = null;
      flushWatchRefresh();
    }, 250);
  }, [editingNodeIdRef, flushWatchRefresh, pendingWatchPathsRef, pendingWatchRefreshRef, watchRefreshTimerRef]);

  const scheduleWatchOverflow = useCallback(() => {
    pendingWatchOverflowRef.current = true;
    pendingWatchPathsRef.current.clear();
    scheduleWatchRefresh();
  }, [pendingWatchOverflowRef, pendingWatchPathsRef, scheduleWatchRefresh]);

  useEffect(() => {
    if (!workspaceKey || !watchFileEvents) return undefined;
    return watchFileEvents({
      onChanged: scheduleWatchRefresh,
      onOverflow: scheduleWatchOverflow,
      onStatusChanged: (available) => {
        setWatchErrorMessage(
          available ? null : "文件自动刷新暂不可用，请使用刷新按钮。",
        );
      },
    });
  }, [scheduleWatchOverflow, scheduleWatchRefresh, setWatchErrorMessage, watchFileEvents, workspaceKey]);

  useEffect(() => {
    if (!workspaceKey || !subscribeMutations) return undefined;
    return subscribeMutations((mutation) => {
      if (mutation.workspaceKey !== workspaceKey) return;
      if (mutation.sourceId === mutationSourceIdRef.current) return;
      if (mutation.action === "delete") {
        if (searchKeywordRef.current.trim()) {
          void loadRootRef.current({ reloadExpandedChildren: false });
          return;
        }
        updateTreeData((prev) => removeNode(prev, mutation.path));
        setErrorMessage(null);
        return;
      }
      if (mutation.action === "move") {
        const browserNode = mapFileWorkspaceNode(mutation.node);
        if (searchKeywordRef.current.trim()) {
          void loadRootRef.current({ reloadExpandedChildren: false });
          return;
        }
        updateTreeData((prev) => upsertNode(removeNode(prev, mutation.previousPath), browserNode));
        setErrorMessage(null);
        return;
      }
      const browserNode = mapFileWorkspaceNode(mutation.node);
      if (searchKeywordRef.current.trim()) {
        void loadRootRef.current({ reloadExpandedChildren: false });
        return;
      }
      updateTreeData((prev) => upsertNode(prev, browserNode));
      setErrorMessage(null);
    });
  }, [
    loadRootRef,
    mutationSourceIdRef,
    searchKeywordRef,
    setErrorMessage,
    subscribeMutations,
    updateTreeData,
    workspaceKey,
  ]);

  useEffect(() => {
    if (editingNodeId || !pendingWatchRefreshRef.current) return;
    pendingWatchRefreshRef.current = false;
    scheduleWatchRefresh();
  }, [editingNodeId, pendingWatchRefreshRef, scheduleWatchRefresh]);

  return {
    refreshLoadedTree,
  };
}
