export type GlobalMemoryRecordStatus = "active" | "deleted";
export type GlobalMemoryRecordView = GlobalMemoryRecordStatus | "all";
export type GlobalMemoryOperation = "add" | "update" | "delete";

export type GlobalMemoryValue = {
  content: string;
  keywords: string[];
};

export type GlobalMemoryEvent = {
  event_index: number;
  operation: GlobalMemoryOperation;
  memory_id: string;
  source: string;
  created_at: string;
  reason: string;
  before: GlobalMemoryValue | null;
  after: GlobalMemoryValue | null;
};

export type GlobalMemoryRecord = {
  id: string;
  scope: "global";
  status: GlobalMemoryRecordStatus;
  content: string;
  keywords: string[];
  created_at: string;
  updated_at: string;
  deleted_at: string;
  source: string;
  last_operation: GlobalMemoryOperation;
  event_count: number;
  events: GlobalMemoryEvent[];
};

export type GlobalMemoryRecordListResponse = {
  scope: "global";
  status: GlobalMemoryRecordView;
  count: number;
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
  items: GlobalMemoryRecord[];
};

export type GlobalMemoryEventListResponse = {
  scope: "global";
  count: number;
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
  items: GlobalMemoryEvent[];
};

export type GlobalMemoryOperationInput = {
  operation: GlobalMemoryOperation;
  memory_id?: string;
  content?: string;
  keywords?: string[];
  reason: string;
};

export type GlobalMemoryOperationResponse = {
  operation: GlobalMemoryOperation;
  memory_id: string;
  memory: GlobalMemoryRecord;
};
