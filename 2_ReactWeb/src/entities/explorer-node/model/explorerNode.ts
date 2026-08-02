export type ExplorerNodeKind = "folder" | "file";

export interface ExplorerNode {
  id: string;
  name: string;
  path: string;
  kind: ExplorerNodeKind;
  children?: ExplorerNode[];
  mtimeMs?: number | null;
}

export type ExplorerTreeOpenState = Readonly<Record<string, boolean>>;

export function findExplorerNodeById(
  nodes: readonly ExplorerNode[],
  nodeId: string,
): ExplorerNode | null {
  for (const node of nodes) {
    if (node.id === nodeId) {
      return node;
    }

    if (node.children) {
      const match = findExplorerNodeById(node.children, nodeId);
      if (match) {
        return match;
      }
    }
  }

  return null;
}
