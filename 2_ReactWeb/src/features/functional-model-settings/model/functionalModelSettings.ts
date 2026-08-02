import type {
  DsLlmGenerationParams,
  DsLlmOutputOptions,
  DsLlmReasoningMode,
} from "../../../entities/llm-runtime/model/generationParams";
import {
  DEFAULT_FUNCTIONAL_MODEL_GENERATION,
  DEFAULT_FUNCTIONAL_MODEL_SETTINGS,
  MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
  MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
  DEFAULT_NAMING_PROMPT,
  type FunctionalModelMemoryCompressionSettings,
  type FunctionalModelMemoryManagementSettings,
  type FunctionalModelNamingSettings,
  type FunctionalModelSettings,
} from "./functionalModelSettingsDefaults";

export {
  DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS,
  DEFAULT_FUNCTIONAL_MODEL_GENERATION,
  DEFAULT_FUNCTIONAL_MODEL_OUTPUT,
  DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS,
  DEFAULT_FUNCTIONAL_MODEL_SETTINGS,
  DEFAULT_MEMORY_COMPRESSION_MAX_OUTPUT_TOKENS,
  DEFAULT_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
  DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
  MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
  MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
  DEFAULT_MEMORY_COMPRESSION_PROMPT,
  DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT,
  DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT,
  DEFAULT_NAMING_MAX_OUTPUT_TOKENS,
  DEFAULT_NAMING_PROMPT,
  FUNCTIONAL_MODEL_SETTINGS_VERSION,
} from "./functionalModelSettingsDefaults";

export type {
  FunctionalModelMemoryCompressionSettings,
  FunctionalModelMemoryManagementSettings,
  FunctionalModelNamingSettings,
  FunctionalModelOption,
  FunctionalModelProfileKey,
  FunctionalModelProfileSettingsMap,
  FunctionalModelSettings,
} from "./functionalModelSettingsDefaults";

type StoredFunctionalModelSettings = Partial<FunctionalModelSettings> & {
  version?: unknown;
};

export function normalizeFunctionalModelSettings(
  input: unknown,
): FunctionalModelSettings {
  if (!isObjectRecord(input)) {
    return DEFAULT_FUNCTIONAL_MODEL_SETTINGS;
  }

  if (isCurrentSettingsShape(input)) {
    return normalizeCurrentSettings(input as StoredFunctionalModelSettings);
  }

  throw new Error("功能模型设置结构无效。");
}

export function normalizeInteger(
  value: unknown,
  defaultValue: number,
  min: number,
  max?: number,
) {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return defaultValue;
  const minBounded = Math.max(min, Math.round(parsed));
  return max === undefined ? minBounded : Math.min(max, minBounded);
}

export function normalizeNumber(value: unknown, defaultValue: number, min: number, max?: number) {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return defaultValue;
  const minBounded = Math.max(min, parsed);
  return max === undefined ? minBounded : Math.min(max, minBounded);
}

function normalizeCurrentSettings(input: StoredFunctionalModelSettings): FunctionalModelSettings {
  return {
    globalMemoryManagement: normalizeMemoryManagementSettings(
      input.globalMemoryManagement,
      DEFAULT_FUNCTIONAL_MODEL_SETTINGS.globalMemoryManagement,
    ),
    memoryCompression: normalizeMemoryCompressionSettings(input.memoryCompression),
    naming: normalizeNamingSettings(input.naming),
    projectMemoryManagement: normalizeMemoryManagementSettings(
      input.projectMemoryManagement,
      DEFAULT_FUNCTIONAL_MODEL_SETTINGS.projectMemoryManagement,
    ),
  };
}

function isCurrentSettingsShape(
  input: Record<string, unknown>,
): input is StoredFunctionalModelSettings {
  return "generation" in input
    || "globalMemoryManagement" in input
    || "memoryCompression" in input
    || "naming" in input
    || "projectMemoryManagement" in input;
}

function normalizeNamingSettings(input: unknown): FunctionalModelNamingSettings {
  const defaults = DEFAULT_FUNCTIONAL_MODEL_SETTINGS.naming;
  const record = isObjectRecord(input) ? input : {};
  const modelKey = typeof record.modelKey === "string" ? record.modelKey : "";

  return {
    generation: normalizeGenerationSettings(record.generation, defaults.generation),
    modelKey,
    modelSource: record.modelSource === "dedicated" ? "dedicated" : defaults.modelSource,
    output: normalizeOutputSettings(record.output),
    prompt: normalizePrompt(record.prompt, DEFAULT_NAMING_PROMPT),
    triggerTokenThreshold: normalizeInteger(
      record.triggerTokenThreshold,
      defaults.triggerTokenThreshold,
      1,
    ),
  };
}

function normalizeMemoryManagementSettings(
  input: unknown,
  defaults: FunctionalModelMemoryManagementSettings,
): FunctionalModelMemoryManagementSettings {
  const record = isObjectRecord(input) ? input : {};

  return {
    blockingEnabled: typeof record.blockingEnabled === "boolean"
      ? record.blockingEnabled
      : defaults.blockingEnabled,
    failureRetryCount: normalizeInteger(
      record.failureRetryCount,
      defaults.failureRetryCount,
      0,
      MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
    ),
    generation: normalizeGenerationSettings(record.generation, defaults.generation),
    modelKey: typeof record.modelKey === "string" ? record.modelKey : "",
    modelSource: record.modelSource === "dedicated" ? "dedicated" : "session",
    output: normalizeOutputSettings(record.output),
    prompt: normalizePrompt(record.prompt, defaults.prompt),
    triggerTokenThreshold: normalizeInteger(
      record.triggerTokenThreshold,
      defaults.triggerTokenThreshold,
      1,
    ),
  };
}

function normalizeMemoryCompressionSettings(
  input: unknown,
): FunctionalModelMemoryCompressionSettings {
  const defaults = DEFAULT_FUNCTIONAL_MODEL_SETTINGS.memoryCompression;
  const record = isObjectRecord(input) ? input : {};
  const generation = normalizeGenerationSettings(record.generation, defaults.generation);
  const modelKey = typeof record.modelKey === "string" && record.modelKey.trim()
    ? record.modelKey
    : "";

  return {
    blockingEnabled: typeof record.blockingEnabled === "boolean"
      ? record.blockingEnabled
      : defaults.blockingEnabled,
    failureRetryCount: normalizeInteger(
      record.failureRetryCount,
      defaults.failureRetryCount,
      0,
      MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
    ),
    generation,
    modelKey,
    modelSource: record.modelSource === "dedicated" ? "dedicated" : "session",
    output: normalizeOutputSettings(record.output),
    prompt: normalizePrompt(record.prompt, defaults.prompt),
  };
}

function normalizeGenerationSettings(
  input: unknown,
  defaults: DsLlmGenerationParams = DEFAULT_FUNCTIONAL_MODEL_GENERATION,
): DsLlmGenerationParams {
  const record = isObjectRecord(input) ? input : {};
  const reasoning = isObjectRecord(record.reasoning) ? record.reasoning : {};

  return {
    maxOutputTokens: normalizeMaxOutputTokens(
      record.maxOutputTokens,
      defaults.maxOutputTokens ?? 100,
      32,
    ),
    reasoning: {
      mode: normalizeReasoningMode(reasoning.mode),
    },
    temperature: normalizeNumber(record.temperature, defaults.temperature ?? 0.2, 0),
    topP: normalizeNumber(record.topP, defaults.topP ?? 1, 0),
  };
}

function normalizeOutputSettings(input: unknown): DsLlmOutputOptions {
  const record = isObjectRecord(input) ? input : {};
  return {
    format: record.format === "text" ? "text" : "json_object",
  };
}

function normalizePrompt(value: unknown, defaultValue: string) {
  return typeof value === "string" && value.trim() ? value : defaultValue;
}

function normalizeReasoningMode(value: unknown): DsLlmReasoningMode {
  if (
    value === "default" ||
    value === "auto" ||
    value === "enabled" ||
    value === "off" ||
    value === "low" ||
    value === "medium" ||
    value === "high" ||
    value === "max"
  ) {
    return value;
  }

  return "off";
}

function normalizeMaxOutputTokens(
  value: unknown,
  defaultValue: number,
  min: number,
  max?: number,
) {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return defaultValue;
  const minBounded = Math.max(min, Math.round(parsed));
  return max === undefined ? minBounded : Math.min(max, minBounded);
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
