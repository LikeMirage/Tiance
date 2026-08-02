import type {
  FileWorkspaceMutation,
  FileWorkspaceNode,
} from "../../file-workspace/model/fileWorkspace";

type ToolFolderFileMutationMeta = {
  sourceId?: string;
};

export type ToolFolderFileMutation =
  | ({
    action: "upsert";
    folderId: string;
    node: FileWorkspaceNode;
    toolsetId: string;
  } & ToolFolderFileMutationMeta)
  | ({
    action: "move";
    folderId: string;
    previousPath: string;
    node: FileWorkspaceNode;
    toolsetId: string;
  } & ToolFolderFileMutationMeta)
  | ({
    action: "delete";
    folderId: string;
    path: string;
    toolsetId: string;
  } & ToolFolderFileMutationMeta);

type ToolFolderFileMutationListener = (mutation: ToolFolderFileMutation) => void;

const listeners = new Set<ToolFolderFileMutationListener>();

export function getToolFolderWorkspaceKey(toolsetId: string, folderId: string) {
  return `tool-folder:${toolsetId}:${folderId}`;
}

export function parseToolFolderWorkspaceKey(key: string) {
  const parts = key.split(":");
  if (parts.length !== 3 || parts[0] !== "tool-folder") {
    return null;
  }
  return {
    toolsetId: parts[1],
    folderId: parts[2],
  };
}

export function publishToolFolderFileMutation(
  mutation: ToolFolderFileMutation,
) {
  for (const listener of listeners) {
    listener(mutation);
  }
}

export function subscribeToolFolderFileMutations(listener: ToolFolderFileMutationListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function toFileWorkspaceMutation(
  mutation: ToolFolderFileMutation,
): FileWorkspaceMutation {
  const workspaceKey = getToolFolderWorkspaceKey(mutation.toolsetId, mutation.folderId);
  if (mutation.action === "delete") {
    return {
      action: "delete",
      path: mutation.path,
      sourceId: mutation.sourceId,
      workspaceKey,
    };
  }
  if (mutation.action === "move") {
    return {
      action: "move",
      previousPath: mutation.previousPath,
      node: mutation.node,
      sourceId: mutation.sourceId,
      workspaceKey,
    };
  }
  return {
    action: "upsert",
    node: mutation.node,
    sourceId: mutation.sourceId,
    workspaceKey,
  };
}
