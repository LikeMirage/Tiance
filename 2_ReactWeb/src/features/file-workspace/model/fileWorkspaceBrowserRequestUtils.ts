import type { RefObject } from "react";

import { normalizeWorkspacePath } from "./fileWorkspaceBrowserTreeModel";

export function isCurrentWorkspaceRequest(
  workspaceKey: string,
  activeWorkspaceKeyRef: RefObject<string | null>,
  requestId: number,
  requestIdRef: RefObject<number>,
): boolean {
  return activeWorkspaceKeyRef.current === workspaceKey && requestId === requestIdRef.current;
}

export function sortExpandedFolderIds(nodeIds: Set<string>) {
  return [...nodeIds]
    .map(normalizeWorkspacePath)
    .filter(Boolean)
    .sort((left, right) => getPathDepth(left) - getPathDepth(right));
}

function getPathDepth(path: string) {
  return path.split("/").filter(Boolean).length;
}
