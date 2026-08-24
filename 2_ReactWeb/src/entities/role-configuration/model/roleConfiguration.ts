export const ROLE_CONFIGURATION_SECTIONS = [
  "profile",
  "model",
  "generation",
  "prompt",
  "response",
  "context",
  "memory",
  "tools",
] as const;

export type RoleConfigurationSection = typeof ROLE_CONFIGURATION_SECTIONS[number];

export type RoleProfileConfiguration = {
  description: string;
};

export type RoleModelConfiguration = {
  provider_id: string;
  model_id: string;
  reasoning_mode: string | null;
};

export type RoleGenerationConfiguration = {
  temperature: number | null;
  top_p: number | null;
  max_output_tokens: number;
};

export type RolePromptConfiguration = {
  system_prompt: string;
};

export type RoleResponseConfiguration = {
  return_cancelled_messages: boolean;
  return_user_before_cancelled: boolean;
  streaming_enabled: boolean;
  auto_collapse_assistant_process: boolean;
  malformed_tool_call_recovery_enabled: boolean;
  upstream_retry_count: number;
};

export type RoleContextConfiguration = {
  inject_message_timestamps: boolean;
};

export type RoleMemoryConfiguration = {
  global_memory_enabled: boolean;
  global_memory_extraction_enabled: boolean;
  project_memory_enabled: boolean;
  project_memory_extraction_enabled: boolean;
  memory_compression_enabled: boolean;
  memory_context_token_trigger_threshold: number;
  memory_raw_context_token_reserve: number;
};

export type RoleToolsConfiguration = {
  tools_enabled: boolean;
  enabled_tool_names: string[] | null;
  max_tool_calls: number;
  tool_approval_mode: "follow_tool_policy" | "auto_allow_ask";
};

export type RoleConfiguration = {
  profile: RoleProfileConfiguration;
  model: RoleModelConfiguration;
  generation: RoleGenerationConfiguration;
  prompt: RolePromptConfiguration;
  response: RoleResponseConfiguration;
  context: RoleContextConfiguration;
  memory: RoleMemoryConfiguration;
  tools: RoleToolsConfiguration;
};

export type RoleConfigurationSectionValueMap = {
  [Section in RoleConfigurationSection]: RoleConfiguration[Section];
};

export type ConversationRoleCategory = {
  category_id: string;
  name: string;
  sort_order: number;
};

export type ConversationRoleCatalogItem = {
  role_project_id: string;
  name: string;
  category_id: string;
  description: string | null;
  is_default: boolean;
  sort_order: number;
};

export type ConversationRoleCatalog = {
  default_role_project_id: string;
  categories: ConversationRoleCategory[];
  roles: ConversationRoleCatalogItem[];
};

export const ROLE_CONFIGURATION_FILE_NAMES: Record<RoleConfigurationSection, string> = {
  profile: "profile.json",
  model: "model.json",
  generation: "generation.json",
  prompt: "prompt.json",
  response: "response.json",
  context: "context.json",
  memory: "memory.json",
  tools: "tools.json",
};

export function parseRoleConfigurationSection<Section extends RoleConfigurationSection>(
  section: Section,
  content: string,
): RoleConfigurationSectionValueMap[Section] {
  let payload: unknown;
  try {
    payload = JSON.parse(content);
  } catch {
    throw new Error(`${ROLE_CONFIGURATION_FILE_NAMES[section]} 不是有效的 JSON。`);
  }
  if (!isRecord(payload)) {
    throw new Error(`${ROLE_CONFIGURATION_FILE_NAMES[section]} 的根节点必须是对象。`);
  }
  return parseSectionPayload(section, payload);
}

export function formatRoleConfigurationSection<Section extends RoleConfigurationSection>(
  value: RoleConfigurationSectionValueMap[Section],
) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function parseSectionPayload<Section extends RoleConfigurationSection>(
  section: Section,
  payload: Record<string, unknown>,
): RoleConfigurationSectionValueMap[Section] {
  switch (section) {
    case "profile":
      return {
        description: stringValue(payload.description),
      } as RoleConfigurationSectionValueMap[Section];
    case "model":
      return {
        provider_id: stringValue(payload.provider_id),
        model_id: stringValue(payload.model_id),
        reasoning_mode: nullableStringValue(payload.reasoning_mode),
      } as RoleConfigurationSectionValueMap[Section];
    case "generation":
      return {
        temperature: nullableNumberValue(payload.temperature),
        top_p: nullableNumberValue(payload.top_p),
        max_output_tokens: integerValue(payload.max_output_tokens, 1),
      } as RoleConfigurationSectionValueMap[Section];
    case "prompt":
      return {
        system_prompt: stringValue(payload.system_prompt),
      } as RoleConfigurationSectionValueMap[Section];
    case "response":
      return {
        return_cancelled_messages: booleanValue(payload.return_cancelled_messages),
        return_user_before_cancelled: booleanValue(payload.return_user_before_cancelled),
        streaming_enabled: booleanValue(payload.streaming_enabled),
        auto_collapse_assistant_process: booleanValue(payload.auto_collapse_assistant_process),
        malformed_tool_call_recovery_enabled: booleanValue(
          payload.malformed_tool_call_recovery_enabled,
        ),
        upstream_retry_count: typeof payload.upstream_retry_count === "number"
          ? integerValue(payload.upstream_retry_count, 0)
          : 1,
      } as RoleConfigurationSectionValueMap[Section];
    case "context":
      return {
        inject_message_timestamps: booleanValue(payload.inject_message_timestamps),
      } as RoleConfigurationSectionValueMap[Section];
    case "memory":
      return {
        global_memory_enabled: booleanValue(payload.global_memory_enabled),
        global_memory_extraction_enabled: booleanValue(
          payload.global_memory_extraction_enabled,
        ),
        project_memory_enabled: booleanValue(payload.project_memory_enabled),
        project_memory_extraction_enabled: booleanValue(
          payload.project_memory_extraction_enabled,
        ),
        memory_compression_enabled: booleanValue(payload.memory_compression_enabled),
        memory_context_token_trigger_threshold: integerValue(
          payload.memory_context_token_trigger_threshold,
          1,
        ),
        memory_raw_context_token_reserve: integerValue(
          payload.memory_raw_context_token_reserve,
          0,
        ),
      } as RoleConfigurationSectionValueMap[Section];
    case "tools":
      return {
        tools_enabled: booleanValue(payload.tools_enabled),
        enabled_tool_names: nullableStringArrayValue(payload.enabled_tool_names),
        max_tool_calls: integerValue(payload.max_tool_calls, 1),
        tool_approval_mode: toolApprovalModeValue(payload.tool_approval_mode),
      } as RoleConfigurationSectionValueMap[Section];
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function nullableStringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function booleanValue(value: unknown) {
  return value === true;
}

function nullableNumberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function integerValue(value: unknown, minimum: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return minimum;
  }
  return Math.max(minimum, Math.round(value));
}

function nullableStringArrayValue(value: unknown) {
  if (value === null) return null;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
}

function toolApprovalModeValue(value: unknown): "follow_tool_policy" | "auto_allow_ask" {
  return value === "follow_tool_policy" ? "follow_tool_policy" : "auto_allow_ask";
}
