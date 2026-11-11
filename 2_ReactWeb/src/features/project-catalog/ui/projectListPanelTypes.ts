export type ProjectDeleteMode = "delete" | "delete-local" | "mixed" | "remove";

export type PendingProjectDelete = {
  mode: ProjectDeleteMode;
  projectIds: string[];
  projectNames: string[];
  clearTianceData?: boolean;
} | null;

export type ProjectContextMenuState = {
  primaryProjectId: string;
  projectIds: string[];
  x: number;
  y: number;
} | null;
