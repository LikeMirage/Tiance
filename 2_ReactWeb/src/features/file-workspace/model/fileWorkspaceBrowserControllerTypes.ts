import type { FileWorkspaceEntryKind } from "../../../entities/file-workspace/model/fileWorkspace";
import type { FileWorkspaceBrowserNode } from "./fileWorkspaceBrowserTreeModel";

export type LoadRootOptions = {
  reloadExpandedChildren?: boolean;
  restart?: boolean;
};

export type LoadFolderChildrenOptions = {
  errorMessage?: string;
  silent?: boolean;
  shouldApply?: () => boolean;
  sourceNodes?: FileWorkspaceBrowserNode[];
};

export type PendingCreateRequest = {
  kind: FileWorkspaceEntryKind;
  parentNodeId?: string;
};
