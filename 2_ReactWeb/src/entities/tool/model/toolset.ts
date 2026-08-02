export type ToolsetScope = "local";

export type Toolset = {
  category_id: string;
  name: string;
  scope: ToolsetScope;
  root_path: string;
  readonly: boolean;
  created_at: string;
  updated_at: string;
};

export type ToolsetListResponse = {
  count: number;
  items: Toolset[];
};

export type ToolsetCreateRequest = {
  name?: string | null;
};

export type ToolsetRenameRequest = {
  name: string;
};

export type ToolFolder = {
  project_id: string;
  category_id: string;
  name: string;
  root_path: string;
  created_at: string;
  updated_at: string;
};

export type ToolFolderListResponse = {
  count: number;
  items: ToolFolder[];
};

export type ToolFolderCreateRequest = {
  name?: string | null;
};

export type ToolFolderRenameRequest = {
  name: string;
};

export type ToolFolderMoveRequest = {
  target_category_id: string;
};

export type ToolFolderDynamicLoadingRequest = {
  dynamic: boolean;
};

export type ToolFolderDynamicLoadingResponse = {
  category_id: string;
  project_id: string;
  dynamic: boolean;
  updated_at: string;
};
