import type { DsLlmReasoningMode } from "../../llm-runtime/model/generationParams";
import type {
  ChatCompletionMessageContentPart,
  ConversationMessageReferences,
} from "./chatCompletion";
export type ConversationSessionSettings = {
  global_memory_enabled: boolean;
  global_memory_extraction_enabled: boolean;
  memory_compression_enabled: boolean;
  memory_context_token_trigger_threshold: number;
  memory_raw_context_token_reserve: number;
  project_memory_enabled: boolean;
  project_memory_extraction_enabled: boolean;
  return_cancelled_messages: boolean;
  return_user_before_cancelled: boolean;
  streaming_enabled: boolean;
  auto_collapse_assistant_process: boolean;
  malformed_tool_call_recovery_enabled: boolean;
  upstream_retry_count: number;
  inject_message_timestamps: boolean;
  system_prompt: string;
  max_output_tokens: number;
  temperature: number | null;
  top_p: number | null;
  tools_enabled: boolean;
  enabled_tool_names: string[] | null;
  max_tool_calls: number;
  tool_approval_mode: "follow_tool_policy" | "auto_allow_ask";
};

export type ConversationSession = {
  session_id: string;
  sequence_number: number;
  title: string;
  provider_id: string | null;
  model_id: string | null;
  reasoning_mode: DsLlmReasoningMode | null;
  manual_title: boolean;
  settings: ConversationSessionSettings;
  created_at: string;
  updated_at: string;
  message_count: number;
  pinned: boolean;
  role_project_id: string | null;
  role_status: "selected" | "custom";
};

export type ConversationRuntimeStatus = "idle" | "running" | "error";

export type ConversationDraftReferences = ConversationMessageReferences;

export type ConversationSessionState = {
  runtime_status: ConversationRuntimeStatus;
  draft: string;
  references?: ConversationDraftReferences;
  updated_at: string;
  runtime_updated_at?: string;
};

export type ConversationSessionListResponse = {
  project_id: string;
  revision: number;
  count: number;
  active_session_id: string | null;
  session_states: Record<string, ConversationSessionState>;
  items: ConversationSession[];
  branch_nodes: ConversationBranchNode[];
  message_variants: ConversationMessageVariant[];
};

export type ConversationBranchNode = {
  branch_id: string;
  tree_id: string;
  session_id: string;
  parent_branch_id: string | null;
  parent_session_id: string | null;
  relation_kind: "root" | "child" | "fork" | "functional";
  function_type:
    | "automatic_naming"
    | "global_memory_management"
    | "memory_compaction"
    | "project_memory_management"
    | null;
  created_by: "user" | "ai" | "system";
  history_mode: "empty" | "fork" | "copy";
  source_message_id: string | null;
  sibling_index: number;
  created_at: string;
  deleted_at: string | null;
};

export type ConversationMessageVariant = {
  variant_group_id: string;
  variant_index: number;
  branch_id: string;
  session_id: string;
  message_id: string | null;
  origin_message_id: string | null;
  created_at: string;
  deleted_at: string | null;
};

export type ConversationMessage = {
  message_id: string;
  session_id: string;
  role: "system" | "user" | "assistant" | "error" | "tool";
  content: string;
  content_parts?: ChatCompletionMessageContentPart[];
  references?: ConversationMessageReferences;
  thinking_content?: string;
  name?: string | null;
  tool_call_id?: string | null;
  tool_calls?: Array<{
    call_id: string;
    name: string;
    arguments: string;
  }>;
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
    prompt_cache_hit_tokens?: number | null;
    prompt_cache_miss_tokens?: number | null;
    reasoning_tokens?: number | null;
    estimated_fields?: string[];
  } | null;
  context_tokens?: number | null;
  context_tokens_estimated?: boolean;
  provider_id: string | null;
  model_id: string | null;
  target_provider_id?: string | null;
  target_model_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  origin_message_id: string;
  variant_group_id?: string | null;
  variant_index?: number;
};

export type ConversationForkResponse = {
  session: ConversationSession;
  state: ConversationSessionState;
  branch: ConversationBranchNode;
  source_message: ConversationMessage;
  branch_nodes: ConversationBranchNode[];
  message_variants: ConversationMessageVariant[];
};

export type ConversationMessageListResponse = {
  project_id: string;
  session_id: string;
  count: number;
  total_count?: number | null;
  has_more: boolean;
  next_before_message_id: string | null;
  items: ConversationMessage[];
  run_outcomes: ConversationRunOutcome[];
  run_attempt_failures: ConversationRunAttemptFailure[];
};

export type ConversationMessageTurnResponse = {
  project_id: string;
  session_id: string;
  user_message_id: string;
  count: number;
  items: ConversationMessage[];
  run_outcomes: ConversationRunOutcome[];
  run_attempt_failures: ConversationRunAttemptFailure[];
};

export type ConversationRunAttemptFailure = {
  event_id: number;
  run_id: string;
  session_id: string;
  user_message_id: string;
  error_code: string | null;
  error_message: string;
  attempt_index: number;
  attempt_count: number;
  occurred_at: string;
};

export type ConversationRunOutcome = {
  run_id: string;
  session_id: string;
  user_message_id: string;
  status: "error";
  error_code: string | null;
  error_message: string;
  attempt_count: number;
  started_at: string;
  settled_at: string;
};

export type ConversationBranchGroup = {
  group_id: string;
  root_session_id: string;
  title: string;
  updated_at: string;
  session_ids: string[];
  is_branched: boolean;
};

export type ConversationBranchGroupListResponse = {
  project_id: string;
  count: number;
  items: ConversationBranchGroup[];
};

export type ConversationBranchTurnTarget = {
  session_id: string;
  message_id: string;
};

export type ConversationBranchTurnNode = {
  node_id: string;
  variant_group_id: string;
  variant_index: number;
  user_preview: string;
  assistant_preview: string;
  reply_status: "done" | "running" | "missing" | "error";
  created_at: string;
  targets: ConversationBranchTurnTarget[];
};

export type ConversationBranchTurnEdge = {
  source_node_id: string;
  target_node_id: string;
};

export type ConversationBranchGroupDetailResponse = {
  project_id: string;
  group: ConversationBranchGroup;
  node_count: number;
  edge_count: number;
  nodes: ConversationBranchTurnNode[];
  edges: ConversationBranchTurnEdge[];
};
