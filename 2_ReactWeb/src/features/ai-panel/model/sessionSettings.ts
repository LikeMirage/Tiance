import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../../entities/llm-chat/model/conversation";

export const DEFAULT_SESSION_SETTINGS: ConversationSessionSettings = {
  global_memory_enabled: true,
  global_memory_extraction_enabled: true,
  memory_compression_enabled: true,
  memory_context_token_trigger_threshold: 250000,
  memory_raw_context_token_reserve: 30000,
  project_memory_enabled: true,
  project_memory_extraction_enabled: true,
  return_thinking_content: false,
  return_cancelled_messages: true,
  return_user_before_cancelled: true,
  streaming_enabled: true,
  auto_collapse_assistant_process: true,
  inject_message_timestamps: true,
  system_prompt: "",
  max_output_tokens: 32768,
  temperature: null,
  top_p: null,
  tools_enabled: true,
  enabled_tool_names: null,
  max_tool_calls: 99999,
};

export function resolveSessionSettings(
  session: ConversationSession | null,
): ConversationSessionSettings {
  return {
    ...DEFAULT_SESSION_SETTINGS,
    ...(session?.settings ?? {}),
  };
}

export function normalizeSessionTitleInput(value: string) {
  return value.trim().replace(/\s+/g, " ") || "新对话";
}
