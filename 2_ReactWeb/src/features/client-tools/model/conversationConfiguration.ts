import type {
  ConversationSession,
  ConversationSessionSettings,
} from "../../../entities/llm-chat/model/conversation";
import type { DsLlmReasoningMode } from "../../../entities/llm-runtime/model/generationParams";
import { getModelCatalog } from "../../../services/llm/getModelCatalog";
import { getRuntimeCapabilities } from "../../../services/llm/getRuntimeCapabilities";
import type { CreateProjectConversationInput } from "../../../services/project/createProjectConversation";
import type { UpdateProjectConversationInput } from "../../../services/project/updateProjectConversation";
import { toChatModelOption } from "../../ai-panel/model/chatModelOption";
import { isJsonRecord, type JsonRecord } from "./conversationClientToolValues";

type ConfigurableConversationSettings = ConversationSessionSettings;

export type ConversationConfiguration = {
  model_id?: string | null;
  provider_id?: string | null;
  reasoning_mode?: DsLlmReasoningMode | null;
  settings?: Partial<ConfigurableConversationSettings> | null;
  title?: string | null;
};

const CONFIGURABLE_SETTING_KEYS = [
  "global_memory_enabled",
  "global_memory_extraction_enabled",
  "memory_compression_enabled",
  "memory_context_token_trigger_threshold",
  "memory_raw_context_token_reserve",
  "project_memory_enabled",
  "project_memory_extraction_enabled",
  "return_cancelled_messages",
  "return_user_before_cancelled",
  "streaming_enabled",
  "auto_collapse_assistant_process",
  "malformed_tool_call_recovery_enabled",
  "upstream_retry_count",
  "inject_message_timestamps",
  "system_prompt",
  "max_output_tokens",
  "temperature",
  "top_p",
  "tools_enabled",
  "enabled_tool_names",
  "max_tool_calls",
  "tool_approval_mode",
] as const satisfies readonly (keyof ConfigurableConversationSettings)[];

type MissingConfigurableSettingKey = Exclude<
  keyof ConfigurableConversationSettings,
  (typeof CONFIGURABLE_SETTING_KEYS)[number]
>;
const CONFIGURABLE_SETTING_KEYS_ARE_EXHAUSTIVE:
  MissingConfigurableSettingKey extends never ? true : never = true;

export function readConversationConfiguration(value: unknown): ConversationConfiguration {
  if (value === undefined || value === null) return {};
  if (!isJsonRecord(value)) {
    throw new Error("configuration 必须是 JSON 对象。");
  }
  const settings = value.settings;
  if (settings !== undefined && settings !== null && !isJsonRecord(settings)) {
    throw new Error("configuration.settings 必须是 JSON 对象。");
  }
  const configuration = { ...value } as ConversationConfiguration;
  if (hasOwn(configuration, "title")) {
    if (typeof configuration.title !== "string" || !configuration.title.trim()) {
      throw new Error("configuration.title 不能为空。");
    }
    configuration.title = configuration.title.trim();
  }
  return configuration;
}

export async function buildChildConversationCreateInput(
  source: ConversationSession,
  configuration: ConversationConfiguration,
): Promise<CreateProjectConversationInput> {
  const providerId = configuration.provider_id ?? source.provider_id;
  const modelId = configuration.model_id ?? source.model_id;
  const settings = { ...(configuration.settings ?? {}) };
  if (!requiresRuntimeValidation(configuration)) {
    return {
      ...(hasOwn(configuration, "title") ? { title: configuration.title ?? null } : {}),
      ...(Object.keys(settings).length > 0 ? { settings } : {}),
    };
  }
  ensureModelPair(configuration, providerId, modelId);
  const effectiveSettings = {
    ...pickConfigurableSettings(source.settings),
    ...settings,
  };
  const validated = await validateEffectiveConfiguration({
    modelId,
    providerId,
    requestedReasoningMode: hasOwn(configuration, "reasoning_mode")
      ? configuration.reasoning_mode ?? null
      : source.reasoning_mode,
    reasoningModeWasExplicit: hasOwn(configuration, "reasoning_mode"),
    settings: effectiveSettings,
  });
  return {
    ...(hasOwn(configuration, "title") ? { title: configuration.title ?? null } : {}),
    ...(hasOwn(configuration, "provider_id") ? { provider_id: providerId } : {}),
    ...(hasOwn(configuration, "model_id") ? { model_id: modelId } : {}),
    ...(
      hasOwn(configuration, "reasoning_mode")
      || hasOwn(configuration, "provider_id")
      || hasOwn(configuration, "model_id")
        ? { reasoning_mode: validated.reasoningMode }
        : {}
    ),
    ...(Object.keys(settings).length > 0 ? { settings } : {}),
  };
}

export async function buildConversationUpdateInput(
  session: ConversationSession,
  configuration: ConversationConfiguration,
): Promise<UpdateProjectConversationInput> {
  const providerId = configuration.provider_id ?? session.provider_id;
  const modelId = configuration.model_id ?? session.model_id;
  const settings = { ...(configuration.settings ?? {}) };
  if (!requiresRuntimeValidation(configuration)) {
    return {
      ...(hasOwn(configuration, "title") ? { title: configuration.title ?? null } : {}),
      ...(Object.keys(settings).length > 0 ? { settings } : {}),
    };
  }
  ensureModelPair(configuration, providerId, modelId);
  const effectiveSettings = {
    ...pickConfigurableSettings(session.settings),
    ...(configuration.settings ?? {}),
  };
  const validated = await validateEffectiveConfiguration({
    modelId,
    providerId,
    requestedReasoningMode: hasOwn(configuration, "reasoning_mode")
      ? configuration.reasoning_mode ?? null
      : session.reasoning_mode,
    reasoningModeWasExplicit: hasOwn(configuration, "reasoning_mode"),
    settings: effectiveSettings,
  });
  return {
    ...(hasOwn(configuration, "title") ? { title: configuration.title ?? null } : {}),
    ...(providerId !== session.provider_id ? { provider_id: providerId } : {}),
    ...(modelId !== session.model_id ? { model_id: modelId } : {}),
    ...(validated.reasoningMode !== session.reasoning_mode || hasOwn(configuration, "reasoning_mode")
      ? { reasoning_mode: validated.reasoningMode }
      : {}),
    ...(Object.keys(settings).length > 0 ? { settings } : {}),
  };
}

function requiresRuntimeValidation(configuration: ConversationConfiguration): boolean {
  if (
    hasOwn(configuration, "provider_id")
    || hasOwn(configuration, "model_id")
    || hasOwn(configuration, "reasoning_mode")
  ) {
    return true;
  }
  const settings = configuration.settings ?? {};
  return ["temperature", "top_p", "max_output_tokens"].some((key) => hasOwn(settings, key));
}

export function serializeConversationConfiguration(session: ConversationSession) {
  return {
    provider_id: session.provider_id,
    model_id: session.model_id,
    reasoning_mode: session.reasoning_mode,
    settings: pickConfigurableSettings(session.settings),
  };
}

function ensureModelPair(
  configuration: ConversationConfiguration,
  providerId: string | null,
  modelId: string | null,
) {
  const changesProvider = hasOwn(configuration, "provider_id");
  const changesModel = hasOwn(configuration, "model_id");
  if (changesProvider !== changesModel) {
    throw new Error("切换模型时必须同时提供 provider_id 和 model_id。");
  }
  if (!providerId || !modelId) {
    throw new Error("会话没有可用的 provider_id 和 model_id。");
  }
}

async function validateEffectiveConfiguration(input: {
  modelId: string | null;
  providerId: string | null;
  requestedReasoningMode: DsLlmReasoningMode | null;
  reasoningModeWasExplicit: boolean;
  settings: ConfigurableConversationSettings;
}) {
  if (!input.providerId || !input.modelId) {
    throw new Error("会话没有可用的模型配置。");
  }
  const catalog = await getModelCatalog({ kind: "chat" });
  const entry = catalog.items.find((item) =>
    item.provider_id === input.providerId && item.model_id === input.modelId,
  );
  if (!entry) {
    throw new Error("指定模型不在聊天面板可用模型列表中。");
  }
  const capabilities = await getRuntimeCapabilities(input.providerId, input.modelId);
  const reasoningModes = capabilities.reasoning.supported
    ? [...capabilities.reasoning.modes]
    : [];
  if (
    input.reasoningModeWasExplicit &&
    input.requestedReasoningMode !== null &&
    !reasoningModes.includes(input.requestedReasoningMode)
  ) {
    throw new Error("reasoning_mode 不是该模型当前可选的推理模式。");
  }
  const reasoningMode = reasoningModes.length > 0
    ? input.requestedReasoningMode && reasoningModes.includes(input.requestedReasoningMode)
      ? input.requestedReasoningMode
      : reasoningModes[0]
    : null;
  validateSamplingSettings(input.settings, reasoningMode, capabilities.sampling);
  if (capabilities.maxOutputTokens.supported) {
    const maxOutputTokens = input.settings.max_output_tokens;
    const maximum = capabilities.maxOutputTokens.max;
    if (
      maxOutputTokens < capabilities.maxOutputTokens.min ||
      (maximum !== null && maxOutputTokens > maximum)
    ) {
      throw new Error(
        `max_output_tokens 超出模型范围 ${capabilities.maxOutputTokens.min}-${maximum ?? "无限制"}。`,
      );
    }
  }
  return {
    model: toChatModelOption(entry),
    reasoningMode,
  };
}

function validateSamplingSettings(
  settings: ConfigurableConversationSettings,
  reasoningMode: DsLlmReasoningMode | null,
  capabilities: Awaited<ReturnType<typeof getRuntimeCapabilities>>["sampling"],
) {
  const requestedParameters = [
    ["temperature", settings.temperature, "temperature"],
    ["top_p", settings.top_p, "topP"],
  ] as const;
  for (const [settingName, value, capabilityName] of requestedParameters) {
    if (value === null || value === undefined) continue;
    if (!capabilities.supported || !capabilities.parameters.includes(capabilityName)) {
      throw new Error(`${settingName} 不被该模型当前运行能力支持。`);
    }
    if (capabilities.disabledWhenReasoning && reasoningMode && reasoningMode !== "off") {
      throw new Error(
        capabilities.disabledReasonWhenReasoning
          ?? `${settingName} 在当前推理模式下不可用。`,
      );
    }
  }
}

function pickConfigurableSettings(
  settings: ConversationSessionSettings,
): ConfigurableConversationSettings {
  void CONFIGURABLE_SETTING_KEYS_ARE_EXHAUSTIVE;
  const result = {} as ConfigurableConversationSettings;
  for (const key of CONFIGURABLE_SETTING_KEYS) {
    (result as JsonRecord)[key] = settings[key];
  }
  return result;
}

function hasOwn(record: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}
