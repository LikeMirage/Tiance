import type {
  DsLlmGenerationParams,
  DsLlmOutputOptions,
} from "../../../entities/llm-runtime/model/generationParams";

export type FunctionalModelNamingSettings = {
  generation: DsLlmGenerationParams;
  modelKey: string;
  modelSource: "session" | "dedicated";
  output: DsLlmOutputOptions;
  prompt: string;
  triggerTokenThreshold: number;
};

export type FunctionalModelMemoryCompressionSettings = {
  blockingEnabled: boolean;
  failureRetryCount: number;
  generation: DsLlmGenerationParams;
  modelKey: string;
  modelSource: "session" | "dedicated";
  output: DsLlmOutputOptions;
  prompt: string;
};

export type FunctionalModelMemoryManagementSettings = {
  blockingEnabled: boolean;
  failureRetryCount: number;
  generation: DsLlmGenerationParams;
  modelKey: string;
  modelSource: "session" | "dedicated";
  output: DsLlmOutputOptions;
  prompt: string;
  triggerTokenThreshold: number;
};

export type FunctionalModelSettings = {
  globalMemoryManagement: FunctionalModelMemoryManagementSettings;
  memoryCompression: FunctionalModelMemoryCompressionSettings;
  naming: FunctionalModelNamingSettings;
  projectMemoryManagement: FunctionalModelMemoryManagementSettings;
};

export type FunctionalModelOption = {
  capabilityTags: string[];
  modelId: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
};

export type FunctionalModelProfileKey = keyof FunctionalModelSettings;

export type FunctionalModelProfileSettingsMap = {
  globalMemoryManagement: FunctionalModelMemoryManagementSettings;
  memoryCompression: FunctionalModelMemoryCompressionSettings;
  naming: FunctionalModelNamingSettings;
  projectMemoryManagement: FunctionalModelMemoryManagementSettings;
};

export const FUNCTIONAL_MODEL_SETTINGS_VERSION = 25;

export const DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS = 32768;
export const DEFAULT_NAMING_MAX_OUTPUT_TOKENS = DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS;
export const DEFAULT_MEMORY_COMPRESSION_MAX_OUTPUT_TOKENS = DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS;
export const DEFAULT_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT = 0;
export const MAX_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT = 10;
export const DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT = 0;
export const MAX_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT = 10;

export const DEFAULT_FUNCTIONAL_MODEL_GENERATION: DsLlmGenerationParams = {
  maxOutputTokens: DEFAULT_NAMING_MAX_OUTPUT_TOKENS,
  reasoning: {
    mode: "off",
  },
  temperature: 0.2,
  topP: 1,
};

function createDefaultGeneration(maxOutputTokens: number): DsLlmGenerationParams {
  return {
    ...DEFAULT_FUNCTIONAL_MODEL_GENERATION,
    maxOutputTokens,
    reasoning: {
      mode: "off",
    },
  };
}

function createDefaultMemoryCompressionGeneration(): DsLlmGenerationParams {
  return {
    ...createDefaultGeneration(DEFAULT_MEMORY_COMPRESSION_MAX_OUTPUT_TOKENS),
    reasoning: {
      mode: "high",
    },
  };
}

export const DEFAULT_FUNCTIONAL_MODEL_OUTPUT: DsLlmOutputOptions = {
  format: "json_object",
};

export const DEFAULT_NAMING_PROMPT = "";

export const DEFAULT_MEMORY_COMPRESSION_PROMPT = "";
export const DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT = "";
export const DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT = "";

export const DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS = {
  memoryCompression: {
    blockingEnabled: false,
    failureRetryCount: DEFAULT_MEMORY_COMPRESSION_FAILURE_RETRY_COUNT,
    generation: createDefaultMemoryCompressionGeneration(),
    modelKey: "",
    modelSource: "session",
    output: DEFAULT_FUNCTIONAL_MODEL_OUTPUT,
    prompt: DEFAULT_MEMORY_COMPRESSION_PROMPT,
  },
  projectMemoryManagement: {
    blockingEnabled: false,
    failureRetryCount: DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
    generation: createDefaultGeneration(DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS),
    modelKey: "",
    modelSource: "session",
    output: {
      format: "text",
    },
    prompt: DEFAULT_PROJECT_MEMORY_MANAGEMENT_PROMPT,
    triggerTokenThreshold: 50_000,
  },
  globalMemoryManagement: {
    blockingEnabled: false,
    failureRetryCount: DEFAULT_LONG_TERM_MEMORY_FAILURE_RETRY_COUNT,
    generation: createDefaultGeneration(DEFAULT_FUNCTIONAL_MAX_OUTPUT_TOKENS),
    modelKey: "",
    modelSource: "session",
    output: {
      format: "text",
    },
    prompt: DEFAULT_GLOBAL_MEMORY_MANAGEMENT_PROMPT,
    triggerTokenThreshold: 100_000,
  },
  naming: {
    generation: createDefaultGeneration(DEFAULT_NAMING_MAX_OUTPUT_TOKENS),
    modelKey: "",
    modelSource: "session",
    output: {
      format: "text",
    },
    prompt: DEFAULT_NAMING_PROMPT,
    triggerTokenThreshold: 20_000,
  },
} satisfies FunctionalModelProfileSettingsMap;

export const DEFAULT_FUNCTIONAL_MODEL_SETTINGS: FunctionalModelSettings = {
  globalMemoryManagement:
    DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS.globalMemoryManagement,
  memoryCompression: DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS.memoryCompression,
  naming: {
    ...DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS.naming,
    triggerTokenThreshold: 20_000,
  },
  projectMemoryManagement:
    DEFAULT_FUNCTIONAL_MODEL_PROFILE_SETTINGS.projectMemoryManagement,
};
