export type FileWorkspaceEntryKind = "file" | "folder";

export type FileWorkspaceNode = {
  id: string;
  name: string;
  path: string;
  kind: FileWorkspaceEntryKind;
  has_children: boolean;
  mtime_ms?: number | null;
  children: FileWorkspaceNode[];
};

type FileWorkspaceMutationMeta = {
  sourceId?: string;
};

export type FileWorkspaceMutation =
  | ({
    action: "upsert";
    workspaceKey: string;
    node: FileWorkspaceNode;
  } & FileWorkspaceMutationMeta)
  | ({
    action: "move";
    workspaceKey: string;
    previousPath: string;
    node: FileWorkspaceNode;
  } & FileWorkspaceMutationMeta)
  | ({
    action: "delete";
    workspaceKey: string;
    path: string;
  } & FileWorkspaceMutationMeta);

export type FileWorkspaceTreeResponse = {
  parent_path?: string | null;
  truncated?: boolean;
  items: FileWorkspaceNode[];
};

export type FileWorkspaceCreateRequest = {
  kind: FileWorkspaceEntryKind;
  parent_path?: string | null;
  name?: string | null;
};

export type FileWorkspaceMoveRequest = {
  path: string;
  target_parent_path?: string | null;
};

export type FileWorkspaceCopyRequest = {
  path: string;
  target_parent_path?: string | null;
};

export type FileWorkspaceRevealRequest = {
  path: string;
};

export type FileWorkspaceOpenExternalRequest = {
  path: string;
};

export type FileWorkspaceOpenExternalResponse = {
  path: string;
  app_name: string;
  used_default_app: boolean;
};

export type FileWorkspaceContentResponse = {
  path: string;
  content: string;
  mtime_ms: number;
};
