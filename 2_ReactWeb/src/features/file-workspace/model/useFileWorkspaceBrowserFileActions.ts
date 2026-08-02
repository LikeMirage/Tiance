import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";

import type {
  FileWorkspaceEntryKind,
  FileWorkspaceCreateRequest,
  FileWorkspaceMutation,
} from "../../../entities/file-workspace/model/fileWorkspace";
import type { FileWorkspaceApi } from "./fileWorkspaceApi";
import type { PendingCreateRequest } from "./fileWorkspaceBrowserControllerTypes";
import {
  buildPendingNodeId,
  findNode,
  insertNode,
  mapFileWorkspaceNode,
  nextDefaultEntryName,
  removeNode,
  replaceNode,
  replaceNodeIdPrefix,
  resolveCreateParent,
  resolveTargetParentPath,
  upsertNode,
  validateSiblingEntryName,
} from "./fileWorkspaceBrowserTreeModel";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";
import { useFileWorkspaceBrowserNavigation } from "./useFileWorkspaceBrowserNavigation";

type SelectionSnapshot = {
  nodeId: string | null;
  nodeIds: Set<string>;
};

type UseFileWorkspaceBrowserFileActionsInput = {
  activeWorkspaceKeyRef: RefObject<string | null>;
  addExpandedNodeId: (nodeId: string) => void;
  commitExpandedNodeIds: (nextExpandedNodeIds: Set<string>) => void;
  commitSelection: (nodeId: string | null, nodeIds: Set<string>) => void;
  commitTreeData: (nextTreeData: FileWorkspaceBrowserNode[]) => void;
  createEntryRef: RefObject<(
    kind: FileWorkspaceEntryKind,
    parentNodeId?: string,
  ) => Promise<void>>;
  editingNodeIdRef: RefObject<string | null>;
  expandedNodeIdsRef: RefObject<Set<string>>;
  loadFolderChildrenNode: (
    node: FileWorkspaceBrowserNode,
    options?: {
      errorMessage?: string;
      silent?: boolean;
      shouldApply?: () => boolean;
      sourceNodes?: FileWorkspaceBrowserNode[];
    },
  ) => Promise<FileWorkspaceBrowserNode[] | null>;
  pendingCreateRef: RefObject<PendingCreateRequest | null>;
  fileWorkspaceApi: FileWorkspaceApi | null;
  prepareInlineCreate?: () => void;
  publishMutation?: (mutation: FileWorkspaceMutation) => void;
  revealRequestIdRef: RefObject<number>;
  searchKeyword: string;
  selectedNodeId: string | null;
  selectedNodeIdsRef: RefObject<Set<string>>;
  setEditingNodeId: Dispatch<SetStateAction<string | null>>;
  setErrorMessage: Dispatch<SetStateAction<string | null>>;
  treeDataRef: RefObject<FileWorkspaceBrowserNode[]>;
  updateTreeData: (
    updater: (currentTreeData: FileWorkspaceBrowserNode[]) => FileWorkspaceBrowserNode[],
  ) => void;
  workspaceKey: string | null;
};

export function useFileWorkspaceBrowserFileActions({
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
  publishMutation,
  revealRequestIdRef,
  searchKeyword,
  selectedNodeId,
  selectedNodeIdsRef,
  setEditingNodeId,
  setErrorMessage,
  treeDataRef,
  updateTreeData,
  workspaceKey,
}: UseFileWorkspaceBrowserFileActionsInput) {
  const {
    loadFolderChildren,
    revealNode,
    revealPath,
    toggleNode,
  } = useFileWorkspaceBrowserNavigation({
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
  });
  const selectionBeforePendingCreateRef = useRef<SelectionSnapshot | null>(null);
  const restoreSelectionBeforePendingCreate = useCallback(() => {
    const previousSelection = selectionBeforePendingCreateRef.current;
    selectionBeforePendingCreateRef.current = null;
    if (!previousSelection) return;

    const previousNodeId = previousSelection.nodeId && findNode(treeDataRef.current, previousSelection.nodeId)
      ? previousSelection.nodeId
      : null;
    const previousNodeIds = new Set(
      [...previousSelection.nodeIds].filter((selectedId) => findNode(treeDataRef.current, selectedId)),
    );
    commitSelection(previousNodeId, previousNodeIds);
  }, [commitSelection, treeDataRef]);

  const cancelInlineEdit = useCallback(() => {
    pendingCreateRef.current = null;
    const nodeId = editingNodeIdRef.current;
    if (nodeId) {
      const node = findNode(treeDataRef.current, nodeId);
      if (node?.isPendingCreate) {
        const nextTreeData = removeNode(treeDataRef.current, nodeId);
        commitTreeData(nextTreeData);
        restoreSelectionBeforePendingCreate();
      }
    }
    editingNodeIdRef.current = null;
    setEditingNodeId(null);
  }, [
    commitTreeData,
    editingNodeIdRef,
    pendingCreateRef,
    restoreSelectionBeforePendingCreate,
    setEditingNodeId,
    treeDataRef,
  ]);

  const runPendingCreate = useCallback(() => {
    const pendingCreate = pendingCreateRef.current;
    if (!pendingCreate) return;
    pendingCreateRef.current = null;
    window.setTimeout(() => {
      void createEntryRef.current(pendingCreate.kind, pendingCreate.parentNodeId);
    }, 0);
  }, [createEntryRef, pendingCreateRef]);

  const createEntry = useCallback(async (
    kind: FileWorkspaceEntryKind,
    parentNodeId?: string,
  ) => {
    if (!fileWorkspaceApi) return;
    const editingNodeId = editingNodeIdRef.current;
    if (editingNodeId) {
      if (findNode(treeDataRef.current, editingNodeId)) {
        pendingCreateRef.current = { kind, parentNodeId };
        return;
      }
      editingNodeIdRef.current = null;
      setEditingNodeId(null);
    }
    const resolvedParentId = parentNodeId ?? resolveCreateParent(treeDataRef.current, selectedNodeId);
    let parentNode = resolvedParentId ? findNode(treeDataRef.current, resolvedParentId) : null;

    if (parentNode && !parentNode.isChildrenLoaded) {
      const operationWorkspaceKey = workspaceKey;
      const loadedTreeData = await loadFolderChildrenNode(parentNode, {
        shouldApply: () => isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey),
      });
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        return;
      }
      if (!loadedTreeData) {
        return;
      }
      parentNode = findNode(loadedTreeData, resolvedParentId ?? "");
    }

    const pendingNodeId = buildPendingNodeId(kind);
    const siblingNodes = parentNode ? parentNode.children : treeDataRef.current;
    const newNode: FileWorkspaceBrowserNode = {
      id: pendingNodeId,
      name: nextDefaultEntryName(kind, siblingNodes),
      path: pendingNodeId,
      kind,
      hasChildren: false,
      children: [],
      isChildrenLoaded: true,
      isPendingCreate: true,
      pendingParentPath: parentNode?.path ?? null,
    };

    prepareInlineCreate?.();
    updateTreeData((prev) => insertNode(prev, resolvedParentId ?? null, newNode));
    selectionBeforePendingCreateRef.current = {
      nodeId: selectedNodeId,
      nodeIds: new Set(selectedNodeIdsRef.current),
    };

    if (resolvedParentId) {
      addExpandedNodeId(resolvedParentId);
    }

    commitSelection(newNode.id, new Set([newNode.id]));
    editingNodeIdRef.current = newNode.id;
    setEditingNodeId(newNode.id);
    setErrorMessage(null);
  }, [
    addExpandedNodeId,
    activeWorkspaceKeyRef,
    commitSelection,
    editingNodeIdRef,
    fileWorkspaceApi,
    loadFolderChildrenNode,
    pendingCreateRef,
    prepareInlineCreate,
    selectedNodeId,
    selectedNodeIdsRef,
    setEditingNodeId,
    setErrorMessage,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  ]);

  useEffect(() => {
    createEntryRef.current = createEntry;
  }, [createEntry, createEntryRef]);

  const deleteNode = useCallback(async (nodeId: string) => {
    if (!fileWorkspaceApi || !workspaceKey) return;
    const operationWorkspaceKey = workspaceKey;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node) return;

    await fileWorkspaceApi.deleteEntry(node.path);
    publishMutation?.({ action: "delete", workspaceKey: operationWorkspaceKey, path: node.path });
    if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
      return;
    }
    updateTreeData((prev) => removeNode(prev, nodeId));
    const nextExpandedNodeIds = filterOutPathPrefix(expandedNodeIdsRef.current, node.path);
    commitExpandedNodeIds(nextExpandedNodeIds);
    const nextSelectedNodeIds = filterOutPathPrefix(selectedNodeIdsRef.current, node.path);
    const nextSelectedNodeId = selectedNodeId && isSameOrDescendantPath(selectedNodeId, node.path)
      ? nextSelectedNodeIds.values().next().value ?? null
      : selectedNodeId;
    commitSelection(nextSelectedNodeId, nextSelectedNodeIds);
  }, [
    activeWorkspaceKeyRef,
    commitExpandedNodeIds,
    commitSelection,
    expandedNodeIdsRef,
    fileWorkspaceApi,
    publishMutation,
    selectedNodeId,
    selectedNodeIdsRef,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  ]);

  const renameNode = useCallback(async (nodeId: string, newName: string) => {
    if (!fileWorkspaceApi || !workspaceKey) return null;
    const operationWorkspaceKey = workspaceKey;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node) return null;
    const normalizedName = newName.trim();
    const validationError = validateSiblingEntryName(treeDataRef.current, node, normalizedName);
    if (validationError) {
      throw new Error(validationError);
    }
    if (!node.isPendingCreate && normalizedName === node.name) {
      editingNodeIdRef.current = null;
      setEditingNodeId(null);
      runPendingCreate();
      return node;
    }

    try {
      const renamedEntry = node.isPendingCreate
        ? await fileWorkspaceApi.createEntry({
            kind: node.kind,
            parent_path: node.pendingParentPath ?? null,
            name: normalizedName,
          } satisfies FileWorkspaceCreateRequest)
        : await fileWorkspaceApi.renameEntry(node.path, normalizedName);
      const renamed = mapFileWorkspaceNode(renamedEntry);
      const wasPendingCreate = Boolean(node.isPendingCreate);
      publishMutation?.(
        wasPendingCreate
          ? { action: "upsert", workspaceKey: operationWorkspaceKey, node: renamedEntry }
          : {
            action: "move",
            workspaceKey: operationWorkspaceKey,
            previousPath: node.path,
            node: renamedEntry,
          },
      );
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        return renamed;
      }
      const nextExpandedNodeIds = replaceNodeIdPrefix(expandedNodeIdsRef.current, node.path, renamed.path);
      commitExpandedNodeIds(nextExpandedNodeIds);
      updateTreeData((prev) => replaceNode(prev, nodeId, renamed));
      if (wasPendingCreate) {
        restoreSelectionBeforePendingCreate();
      } else {
        const nextSelectedNodeIds = replaceNodeIdPrefix(selectedNodeIdsRef.current, node.path, renamed.path);
        commitSelection(renamed.id, nextSelectedNodeIds);
      }
      editingNodeIdRef.current = null;
      setEditingNodeId(null);
      setErrorMessage(null);
      runPendingCreate();
      return renamed;
    } catch (err) {
      throw err;
    }
  }, [
    activeWorkspaceKeyRef,
    commitExpandedNodeIds,
    commitSelection,
    editingNodeIdRef,
    expandedNodeIdsRef,
    fileWorkspaceApi,
    publishMutation,
    restoreSelectionBeforePendingCreate,
    runPendingCreate,
    selectedNodeIdsRef,
    setEditingNodeId,
    setErrorMessage,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  ]);

  const copyNode = useCallback(async (nodeId: string, targetParentNodeId: string | null) => {
    if (!fileWorkspaceApi || !workspaceKey) return;
    const operationWorkspaceKey = workspaceKey;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node) return;

    const targetParentPath = resolveTargetParentPath(
      targetParentNodeId ? findNode(treeDataRef.current, targetParentNodeId) : null,
    );
    if (targetParentPath && isSameOrDescendantPath(targetParentPath, node.path)) {
      const message = "不能复制到自身或子文件夹中。";
      setErrorMessage(message);
      throw new Error(message);
    }
    try {
      const targetParentNode = targetParentPath
        ? findNode(treeDataRef.current, targetParentPath)
        : null;
      const copied = await fileWorkspaceApi.copyEntry({
        path: node.path,
        target_parent_path: targetParentPath,
      });
      publishMutation?.({ action: "upsert", workspaceKey: operationWorkspaceKey, node: copied });
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        return;
      }
      if (targetParentPath) {
        addExpandedNodeId(targetParentPath);
      }
      const copiedNode = mapFileWorkspaceNode(copied);
      let targetParentRefreshFailed = false;
      if (targetParentNode?.kind === "folder" && !targetParentNode.isChildrenLoaded) {
        const refreshedTargetParent = await loadFolderChildrenNode(
          targetParentNode,
          {
            errorMessage: "文件夹刷新失败。",
            shouldApply: () => isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey),
          },
        );
        if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
          return;
        }
        targetParentRefreshFailed = !refreshedTargetParent;
      }
      updateTreeData((prev) => upsertNode(prev, copiedNode));
      commitSelection(copiedNode.id, new Set([copiedNode.id]));
      if (!targetParentRefreshFailed) {
        setErrorMessage(null);
      }
    } catch (err) {
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        throw err;
      }
      setErrorMessage(err instanceof Error ? err.message : "复制失败。");
      throw err;
    }
  }, [
    addExpandedNodeId,
    activeWorkspaceKeyRef,
    commitSelection,
    fileWorkspaceApi,
    loadFolderChildrenNode,
    publishMutation,
    setErrorMessage,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  ]);

  const moveNode = useCallback(async (nodeId: string, targetParentNodeId: string | null) => {
    if (!fileWorkspaceApi || !workspaceKey) return;
    const operationWorkspaceKey = workspaceKey;
    const node = findNode(treeDataRef.current, nodeId);
    if (!node) return;

    const targetParentPath = resolveTargetParentPath(
      targetParentNodeId ? findNode(treeDataRef.current, targetParentNodeId) : null,
    );
    if (targetParentPath && isSameOrDescendantPath(targetParentPath, node.path)) {
      const message = "不能移动到自身或子文件夹中。";
      setErrorMessage(message);
      throw new Error(message);
    }
    try {
      const targetParentNode = targetParentPath
        ? findNode(treeDataRef.current, targetParentPath)
        : null;
      const moved = await fileWorkspaceApi.moveEntry({
        path: node.path,
        target_parent_path: targetParentPath,
      });
      publishMutation?.({
        action: "move",
        workspaceKey: operationWorkspaceKey,
        previousPath: node.path,
        node: moved,
      });
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        return;
      }
      const next = replaceNodeIdPrefix(expandedNodeIdsRef.current, node.path, moved.path);
      if (targetParentPath) {
        next.add(targetParentPath);
      }
      commitExpandedNodeIds(next);
      const movedNode = mapFileWorkspaceNode(moved);
      let targetParentRefreshFailed = false;
      if (targetParentNode?.kind === "folder" && !targetParentNode.isChildrenLoaded) {
        const refreshedTargetParent = await loadFolderChildrenNode(
          targetParentNode,
          {
            errorMessage: "文件夹刷新失败。",
            shouldApply: () => isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey),
          },
        );
        if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
          return;
        }
        targetParentRefreshFailed = !refreshedTargetParent;
      }
      updateTreeData((prev) => upsertNode(removeNode(prev, nodeId), movedNode));
      const nextSelectedNodeIds = replaceNodeIdPrefix(selectedNodeIdsRef.current, node.path, moved.path);
      commitSelection(movedNode.id, nextSelectedNodeIds);
      if (!targetParentRefreshFailed) {
        setErrorMessage(null);
      }
    } catch (err) {
      if (!isActiveWorkspace(activeWorkspaceKeyRef, operationWorkspaceKey)) {
        throw err;
      }
      setErrorMessage(err instanceof Error ? err.message : "移动失败。");
      throw err;
    }
  }, [
    activeWorkspaceKeyRef,
    commitExpandedNodeIds,
    commitSelection,
    expandedNodeIdsRef,
    fileWorkspaceApi,
    loadFolderChildrenNode,
    publishMutation,
    selectedNodeIdsRef,
    setErrorMessage,
    treeDataRef,
    updateTreeData,
    workspaceKey,
  ]);

  const createFile = useCallback(
    (parentNodeId?: string) => createEntry("file", parentNodeId),
    [createEntry],
  );
  const createFolder = useCallback(
    (parentNodeId?: string) => createEntry("folder", parentNodeId),
    [createEntry],
  );
  const startInlineEdit = useCallback((nodeId: string) => {
    setErrorMessage(null);
    setEditingNodeId(nodeId);
  }, [setEditingNodeId, setErrorMessage]);

  return useMemo(() => ({
    cancelInlineEdit,
    copyNode,
    createFile,
    createFolder,
    deleteNode,
    loadFolderChildren,
    moveNode,
    revealNode,
    revealPath,
    renameNode,
    startInlineEdit,
    toggleNode,
  }), [
    cancelInlineEdit,
    copyNode,
    createFile,
    createFolder,
    deleteNode,
    loadFolderChildren,
    moveNode,
    revealNode,
    revealPath,
    renameNode,
    startInlineEdit,
    toggleNode,
  ]);
}

function filterOutPathPrefix(nodeIds: Set<string>, removedPath: string): Set<string> {
  const next = new Set<string>();
  for (const nodeId of nodeIds) {
    if (!isSameOrDescendantPath(nodeId, removedPath)) {
      next.add(nodeId);
    }
  }
  return next;
}

function isSameOrDescendantPath(path: string, ancestorPath: string): boolean {
  const normalizedPath = path.toLocaleLowerCase();
  const normalizedAncestorPath = ancestorPath.toLocaleLowerCase();
  return normalizedPath === normalizedAncestorPath ||
    normalizedPath.startsWith(`${normalizedAncestorPath}/`);
}

function isActiveWorkspace(
  activeWorkspaceKeyRef: RefObject<string | null>,
  operationWorkspaceKey: string | null,
) {
  return Boolean(operationWorkspaceKey) && activeWorkspaceKeyRef.current === operationWorkspaceKey;
}
