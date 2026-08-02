export type ProjectMemoryScope = "project" | "global";

export type ProjectMemoryEvent = {
  operation: string;
  memory_id: string;
  source: string;
  created_at: string;
  reason: string;
};

export type ProjectMemoryItem = {
  id: string;
  scope: string;
  content: string;
  keywords: string[];
  created_at: string;
  updated_at: string;
  source: string;
  last_operation: string;
  event_count: number;
  events: ProjectMemoryEvent[];
};

export type ProjectMemoryListResponse = {
  project_id: string;
  scope: string;
  count: number;
  items: ProjectMemoryItem[];
};

export type ProjectMemoryOperationInput = {
  scope: ProjectMemoryScope;
  operation: "add" | "update" | "delete";
  memory_id?: string | null;
  content?: string | null;
  keywords?: string[] | null;
  reason: string;
};

export type ProjectMemoryOperationResponse = {
  project_id: string;
  scope: string;
  operation: string;
  memory_id: string;
  memory: ProjectMemoryItem | null;
  items: ProjectMemoryItem[];
};
