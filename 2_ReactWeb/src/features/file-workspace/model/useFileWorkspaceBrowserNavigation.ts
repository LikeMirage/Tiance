import { useCallback, type RefObject } from "react";

import type { FileWorkspaceApi } from "./fileWorkspaceApi";
import { getFileWorkspaceTreeWithTimeout } from "./fileWorkspaceBrowserFileLoader";
import {
  findNode,
  getAncestorFolderPaths,
  mapFileWorkspaceNode,
  normalizeWorkspacePath,
} from "./fileWorkspaceBrowserTreeModel";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";

type UseFileWorkspaceBrowserNavigationInput = {
  activeWorkspaceKeyRef: RefObject<string | null>;
  commitExpandedNodeIds: (
    nextExpandedNodeIds: Set<string>,
    options?: { persistAsUser?: boolean },
  ) => void;
  commitSelection: (nodeId: string | null, nodeIds: Set<string>) => void;
  commitTreeData: (nextTreeData: FileWorkspaceBrowserNode[]) => void;
  expandedNodeIdsRef: RefObject<Set<string>>;
  fileWorkspaceApi: FileWorkspaceApi | null;
  loadFolderChildrenNode: (
    node: FileWorkspaceBrowserNode,
    options?: {
      errorMessage?: string;
      silent?: boolean;
      shouldApply?: () => boolean;
      sourceNodes?: FileWorkspaceBrowserNode[];
    },
  ) => Promise<FileWorkspaceBrowserNode[] | null>;
  revealRequestIdRef: RefObject<number>;
  searchKeyword: string;
  setErrorMessage: (message: string | null) => void;
  treeDataRef: RefObject<FileWorkspaceBrowserNode[]>;
  workspaceKey: string | null;
};

export function useFileWorkspaceBrowserNavigation({
  activeWorkspaceKeyRef,
  commitExpandedNodeIds,
  commitSelection,
  commitTreeData,
  expandedNodeIdsRef,
  fileWorkspaceApi,
  loadFolderChildrenNode,
  revealRequestIdRef,
  searchKeyword,
  setErrorMessage,
  treeDataRef,
  workspaceKey,
}: UseFileWorkspaceBrowserNavigationInput) {
  const loadFolderChildren = useCallback(async (nodeId: string) => {
    if (!fileWorkspaceApi) return;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node || node.kind !== "folder") return;
    await loadFolderChildrenNode(node);
  }, [fileWorkspaceApi, loadFolderChildrenNode, treeDataRef]);

  const revealPath = useCallback(async (path: string) => {
    if (!fileWorkspaceApi || !workspaceKey || searchKeyword.trim()) return;

    const targetPath = normalizeWorkspacePath(path);
    if (!targetPath) return;

    const revealRequestId = ++revealRequestIdRef.current;
    let nodes = treeDataRef.current;

    if (nodes.length === 0) {
      try {
        const response = await getFileWorkspaceTreeWithTimeout(fileWorkspaceApi);
        if (revealRequestId !== revealRequestIdRef.current) return;
        if (activeWorkspaceKeyRef.current !== workspaceKey) return;
        nodes = response.items.map(mapFileWorkspaceNode);
        commitTreeData(nodes);
      } catch (err) {
        if (revealRequestId !== revealRequestIdRef.current) return;
        setErrorMessage(err instanceof Error ? err.message : "文件列表加载失败。");
        return;
      }
    }

    const ancestorFolderPaths = getAncestorFolderPaths(targetPath);
    const nextExpandedNodeIds = new Set(expandedNodeIdsRef.current);

    for (const folderPath of ancestorFolderPaths) {
      if (revealRequestId !== revealRequestIdRef.current) return;

      const folderNode = findNode(nodes, folderPath);
      if (!folderNode || folderNode.kind !== "folder") return;

      nextExpandedNodeIds.add(folderNode.id);
      commitExpandedNodeIds(new Set(nextExpandedNodeIds), { persistAsUser: false });

      if (folderNode.isChildrenLoaded) continue;
      const loadedNodes = await loadFolderChildrenNode(folderNode, {
        shouldApply: () => revealRequestId === revealRequestIdRef.current,
        sourceNodes: nodes,
      });
      if (!loadedNodes) {
        return;
      }
      nodes = loadedNodes;
    }

    if (revealRequestId !== revealRequestIdRef.current) return;

    const targetNode = findNode(nodes, targetPath);
    if (targetNode) {
      commitSelection(targetNode.id, new Set([targetNode.id]));
    }
  }, [
    activeWorkspaceKeyRef,
    commitExpandedNodeIds,
    commitSelection,
    commitTreeData,
    expandedNodeIdsRef,
    fileWorkspaceApi,
    loadFolderChildrenNode,
    revealRequestIdRef,
    searchKeyword,
    setErrorMessage,
    treeDataRef,
    workspaceKey,
  ]);

  const toggleNode = useCallback((nodeId: string) => {
    const current = expandedNodeIdsRef.current;
    const next = new Set(current);
    if (next.has(nodeId)) {
      next.delete(nodeId);
    } else {
      next.add(nodeId);
      const node = findNode(treeDataRef.current, nodeId);
      if (node && node.kind === "folder") {
        void loadFolderChildren(nodeId);
      }
    }
    commitExpandedNodeIds(next);
  }, [commitExpandedNodeIds, expandedNodeIdsRef, loadFolderChildren, treeDataRef]);

  const revealNode = useCallback(async (nodeId: string) => {
    if (!fileWorkspaceApi) return;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node) return;
    try {
      await fileWorkspaceApi.revealEntry({ path: node.path });
      setErrorMessage(null);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "无法在资源管理器中显示。");
      throw err;
    }
  }, [fileWorkspaceApi, setErrorMessage, treeDataRef]);

  return {
    loadFolderChildren,
    revealNode,
    revealPath,
    toggleNode,
  };
}
