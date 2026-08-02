import {
  findNode,
  type FileWorkspaceBrowserNode,
} from "../model/fileWorkspaceBrowserTreeModel";
import type { UseFileWorkspaceBrowserResult } from "../model/fileWorkspaceBrowserTypes";
import type { FileWorkspaceClipboardState } from "./fileWorkspaceTreeUiTypes";

export async function pasteClipboard(
  browser: UseFileWorkspaceBrowserResult,
  clipboard: FileWorkspaceClipboardState,
  targetParentNodeId: string | null,
  setClipboard: (state: FileWorkspaceClipboardState) => void,
  resolveSystemClipboardPaste?: (
    clipboard: FileWorkspaceClipboardState,
  ) => Promise<"internal" | "handled">,
) {
  if (resolveSystemClipboardPaste) {
    const result = await resolveSystemClipboardPaste(clipboard);
    if (result === "handled") {
      setClipboard(null);
      return;
    }
  }
  if (!clipboard) {
    return;
  }

  const nodeIds = getActionNodeIds(browser, clipboard.nodeIds);
  for (const nodeId of nodeIds) {
    if (clipboard.mode === "copy") {
      await browser.copyNode(nodeId, targetParentNodeId);
    } else {
      await browser.moveNode(nodeId, targetParentNodeId);
    }
  }

  if (clipboard.mode === "cut") {
    setClipboard(null);
  }
}

export function copyToClipboard(
  browser: UseFileWorkspaceBrowserResult,
  nodeIds: string[],
  setClipboard: (state: FileWorkspaceClipboardState) => void,
  copyNodesToSystemClipboard?: (nodes: FileWorkspaceBrowserNode[]) => Promise<string[] | null>,
) {
  const actionNodeIds = getActionNodeIds(browser, nodeIds);
  if (actionNodeIds.length === 0) return;
  setClipboard({ mode: "copy", nodeIds: actionNodeIds });
  if (!copyNodesToSystemClipboard) return;

  const nodes = actionNodeIds
    .map((nodeId) => findNode(browser.treeData, nodeId))
    .filter((node): node is FileWorkspaceBrowserNode => node !== null);
  void copyNodesToSystemClipboard(nodes)
    .then((systemSourcePaths) => {
      if (!systemSourcePaths) return;
      setClipboard({
        mode: "copy",
        nodeIds: actionNodeIds,
        systemSourcePaths,
      });
    })
    .catch(() => undefined);
}

export async function deleteNodes(
  nodeIds: string[],
  onDeleteNode: (nodeId: string) => Promise<void> | void,
): Promise<DeleteNodeFailure[]> {
  const failures: DeleteNodeFailure[] = [];
  for (const nodeId of nodeIds) {
    try {
      await onDeleteNode(nodeId);
    } catch (error) {
      failures.push({ nodeId, error });
    }
  }
  return failures;
}

export type DeleteNodeFailure = {
  error: unknown;
  nodeId: string;
};

export function getActionNodeIds(
  browser: UseFileWorkspaceBrowserResult,
  nodeIds: string[],
): string[] {
  const nodes = [...new Set(nodeIds)]
    .map((nodeId) => findNode(browser.treeData, nodeId))
    .filter((node): node is FileWorkspaceBrowserNode =>
      node !== null && !node.isPendingCreate,
    );

  return nodes
    .filter((node) =>
      !nodes.some((candidate) =>
        candidate.id !== node.id && isDescendantPath(node.path, candidate.path),
      ),
    )
    .sort((left, right) => getPathDepth(right.path) - getPathDepth(left.path))
    .map((node) => node.id);
}

function isDescendantPath(path: string, ancestorPath: string) {
  const normalizedPath = path.toLocaleLowerCase();
  const normalizedAncestorPath = ancestorPath.toLocaleLowerCase();
  return normalizedPath.startsWith(`${normalizedAncestorPath}/`);
}

function getPathDepth(path: string) {
  return path.split("/").filter(Boolean).length;
}
