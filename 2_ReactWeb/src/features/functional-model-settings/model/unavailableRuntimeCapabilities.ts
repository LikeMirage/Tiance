import type { DsLlmRuntimeCapabilities } from "../../../entities/llm-runtime/model/runtimeCapabilities";

export const UNAVAILABLE_RUNTIME_CAPABILITIES: DsLlmRuntimeCapabilities = {
  inputModalities: [],
  maxOutputTokens: {
    max: null,
    min: 1,
    supported: false,
  },
  outputFormats: ["text"],
  providerProfileId: "unavailable",
  reasoning: {
    modes: ["off"],
    supported: false,
  },
  sampling: {
    disabledWhenReasoning: false,
    parameters: [],
    supported: false,
  },
  toolCalling: {
    supported: false,
  },
};

export function isRuntimeCapabilitiesUnavailable(capabilities: DsLlmRuntimeCapabilities) {
  return capabilities.providerProfileId === UNAVAILABLE_RUNTIME_CAPABILITIES.providerProfileId;
}
