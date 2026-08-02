import type {
  FileWorkspaceContentResponse,
  FileWorkspaceCopyRequest,
  FileWorkspaceCreateRequest,
  FileWorkspaceMoveRequest,
  FileWorkspaceNode,
  FileWorkspaceRevealRequest,
  FileWorkspaceTreeResponse,
} from "./fileWorkspace";

export type FileWorkspaceListOptions = {
  parentPath?: string | null;
  query?: string;
};

export type FileWorkspaceApi = {
  copyEntry: (payload: FileWorkspaceCopyRequest) => Promise<FileWorkspaceNode>;
  createEntry: (payload: FileWorkspaceCreateRequest) => Promise<FileWorkspaceNode>;
  deleteEntry: (path: string) => Promise<void>;
  listTree: (
    options?: FileWorkspaceListOptions,
    init?: Pick<RequestInit, "signal">,
  ) => Promise<FileWorkspaceTreeResponse>;
  moveEntry: (payload: FileWorkspaceMoveRequest) => Promise<FileWorkspaceNode>;
  readTextFile: (path: string) => Promise<FileWorkspaceContentResponse>;
  renameEntry: (path: string, name: string) => Promise<FileWorkspaceNode>;
  revealEntry: (payload: FileWorkspaceRevealRequest) => Promise<void>;
  saveTextFile: (
    path: string,
    content: string,
    options?: Pick<RequestInit, "signal"> & { expectedMtimeMs?: number | null },
  ) => Promise<FileWorkspaceNode>;
  workspaceKey: string;
};
