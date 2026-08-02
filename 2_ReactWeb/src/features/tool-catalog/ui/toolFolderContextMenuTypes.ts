export type ToolFolderContextMenuState = {
  folderId: string;
  x: number;
  y: number;
} | null;

export type PendingToolFolderDelete = {
  folderId: string;
  folderName: string;
} | null;
