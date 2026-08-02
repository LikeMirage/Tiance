export type ToolCallRecord = {
  record_id: string;
  tool_project_id: string;
  tool_name: string;
  call_id: string;
  source_project_id: string | null;
  source_project_name: string;
  session_id: string | null;
  session_title: string;
  arguments_text: string;
  result_text: string;
  ok: boolean;
  error: string | null;
  created_at: string;
  elapsed_ms: number | null;
  dynamic: boolean | null;
};

export type ToolCallRecordListResponse = {
  category_id: string;
  project_id: string;
  count: number;
  items: ToolCallRecord[];
};

export type ToolCallRecordTopTool = {
  tool_name: string;
  display_name: string;
  call_count: number;
};

export type ToolCallRecordOverviewResponse = {
  total_call_count: number;
  top_tools: ToolCallRecordTopTool[];
};

export type ToolCallRecordSummaryItem = {
  project_id: string;
  category_id: string;
  project_name: string;
  tool_name: string;
  display_name: string;
  enabled: boolean | null;
  dynamic: boolean | null;
  parallel: boolean | null;
  call_count: number;
  success_count: number;
  failure_count: number;
  last_called_at: string | null;
  average_elapsed_ms: number | null;
  dynamic_count: number;
  full_load_count: number;
  full_injection_char_count: number;
  dynamic_injection_char_count: number;
  global_call_share: number;
};

export type ToolCallRecordSummaryResponse = {
  category_id: string;
  total_call_count: number;
  category_call_count: number;
  items: ToolCallRecordSummaryItem[];
};
