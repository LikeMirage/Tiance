export type FileWorkspaceContextMenuState =
  | {
      mode: "root";
      x: number;
      y: number;
    }
  | {
      mode: "node";
      nodeId: string;
      x: number;
      y: number;
    }
  | {
      mode: "selection";
      nodeIds: string[];
      x: number;
      y: number;
    }
  | null;

export type FileWorkspaceClipboardState = {
  mode: "copy" | "cut";
  nodeIds: string[];
  systemSourcePaths?: string[];
} | null;

export function getFileWorkspaceTreeItemId(nodeId: string) {
  return `fwt-node-${encodeURIComponent(nodeId)}`;
}
