import type { DsLlmReasoningMode } from "../../llm-runtime/model/generationParams";
import type {
  EditorFileReference,
  EditorImageReference,
  EditorTextReference,
} from "../../editor/model/editorReference";

export type ConversationMessageReference =
  | { type: "file"; reference: EditorFileReference }
  | { type: "image"; reference: EditorImageReference }
  | { type: "text"; reference: EditorTextReference };

export type ConversationMessageReferences = ConversationMessageReference[];

export type ChatCompletionMessageRole = "system" | "user" | "assistant" | "tool";

export type ChatCompletionMessageContentPart =
  | {
    type: "text";
    text: string;
  }
  | {
    type: "image_url";
    image_url: {
      url: string;
      detail?: "auto" | "low" | "high" | null;
    };
  }
  | {
    type: "image_ref";
    image_ref: {
      path: string;
      mime_type?: string | null;
      detail?: "auto" | "low" | "high" | null;
      name?: string | null;
      size_bytes?: number | null;
    };
  };

export type ChatCompletionMessageInput = {
  role: ChatCompletionMessageRole;
  content: string;
  message_id?: string | null;
  content_parts?: ChatCompletionMessageContentPart[];
  name?: string | null;
  tool_call_id?: string | null;
  tool_calls?: ChatToolCallEvent[];
  thinking_content?: string;
  references?: ConversationMessageReferences;
};

export type ChatCompletionRequest = {
  provider_id: string;
  model_id: string;
  project_id?: string | null;
  session_id?: string | null;
  messages: ChatCompletionMessageInput[];
  malformed_tool_call_recovery_enabled?: boolean;
  upstream_retry_count?: number;
  max_tool_calls?: number;
  client_capabilities?: ChatClientCapability[];
  generation?: {
    reasoning?: {
      mode: DsLlmReasoningMode;
      budget_tokens?: number | null;
    } | null;
    temperature?: number | null;
    top_p?: number | null;
    presence_penalty?: number | null;
    frequency_penalty?: number | null;
    max_output_tokens?: number | null;
  } | null;
};

export type ChatUsage = {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  prompt_cache_hit_tokens?: number | null;
  prompt_cache_miss_tokens?: number | null;
  reasoning_tokens?: number | null;
  estimated_fields?: string[];
};

export type ChatToolCallEvent = {
  call_id: string;
  name: string;
  arguments: string;
};

export type ChatToolResultEvent = {
  call_id: string;
  name: string;
  arguments: string;
  ok: boolean;
  content: string;
  error?: string | null;
  tool_project_id?: string | null;
};

export type ChatClientToolRequestEvent = {
  request_id: string;
  call_id: string;
  name: string;
  arguments: string;
  project_id?: string | null;
  session_id?: string | null;
  timeout_seconds?: number | null;
  model_context?: {
    provider_id?: string | null;
    model_id?: string | null;
    input_modalities?: string[];
  };
  client_capability?: {
    name: string;
    min_version: number;
  } | null;
};

export type ChatClientCapability = {
  name: string;
  version: number;
};

export type ChatToolPermissionFactEvent = {
  tool_name: string;
  parameter_name: string;
  permission_type: string;
  scope: string;
};

export type ChatToolPermissionRequestEvent = {
  request_id: string;
  call_id: string;
  name: string;
  project_id?: string | null;
  session_id?: string | null;
  facts: ChatToolPermissionFactEvent[];
};

export type ChatToolPermissionResolutionEvent = {
  request_id: string;
  call_id: string;
  decision: "allow" | "deny";
};

export type ChatCompletionResponse = {
  provider_id: string;
  model_id: string;
  message: {
    role: ChatCompletionMessageRole;
    content: string;
    content_parts?: ChatCompletionMessageContentPart[];
    thinking_content?: string;
  };
  thinking_content: string;
  finish_reason: string | null;
  usage?: ChatUsage | null;
  selected_key_id: string | null;
  selected_api_key_hint: string | null;
};

export type ChatStreamEvent = (
  | { kind: "conversation_resume_reset" }
  | {
    kind: "retry_reset";
    error?: string | null;
    error_code?: string | null;
    attempt_index?: number | null;
    attempt_count?: number | null;
  }
  | { kind: "conversation_run_started"; user_message_id: string }
  | {
    kind: "conversation_run_settled";
    user_message_id: string;
    assistant_message_id?: string | null;
    status: "done" | "error" | "cancelled";
  }
  | { kind: "delta"; content: string | null; finish_reason?: string | null; error?: string | null }
  | { kind: "thinking_delta"; content: string | null; finish_reason?: string | null; error?: string | null }
  | {
    kind: "tool_call_delta";
    content?: string | null;
    finish_reason?: string | null;
    error?: string | null;
    tool_call?: ChatToolCallEvent | null;
  }
  | {
    kind: "usage";
    content?: string | null;
    usage: ChatUsage;
    context_tokens?: number | null;
    context_tokens_estimated?: boolean;
    finish_reason?: string | null;
    error?: string | null;
  }
  | {
    kind: "tool_call";
    content?: string | null;
    tool_call: ChatToolCallEvent;
    finish_reason?: string | null;
    error?: string | null;
  }
  | {
    kind: "client_tool_request";
    content?: string | null;
    client_tool_request: ChatClientToolRequestEvent;
    finish_reason?: string | null;
    error?: string | null;
  }
  | {
    kind: "client_tool_request_cancelled";
    request_id: string;
  }
  | {
    kind: "tool_permission_request";
    tool_permission_request: ChatToolPermissionRequestEvent;
  }
  | {
    kind: "tool_permission_resolved";
    tool_permission_resolution: ChatToolPermissionResolutionEvent;
  }
  | {
    kind: "tool_permission_request_cancelled";
    request_id: string;
  }
  | {
    kind: "tool_result";
    content?: string | null;
    tool_result: ChatToolResultEvent;
    finish_reason?: string | null;
    error?: string | null;
  }
  | { kind: "done"; content?: string | null; finish_reason?: string | null; error?: string | null }
  | {
    kind: "error";
    content?: string | null;
    error: string;
    error_code?: string | null;
    finish_reason?: string | null;
  }
) & {
  run_sequence?: number;
  attempt_index?: number | null;
  attempt_count?: number | null;
};
