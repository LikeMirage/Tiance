import type {
  DsLlmInputModality,
  DsLlmRuntimeCapabilities,
  DsLlmSamplingParameter,
} from "../../entities/llm-runtime/model/runtimeCapabilities";
import { fetchJson } from "../http/httpClient";

type RuntimeCapabilitiesResponse = {
  input_modalities: string[];
  max_output_tokens: {
    max: number | null;
    min: number | null;
    supported: boolean;
  };
  output_formats: Array<"text" | "json_object">;
  provider_profile_id: string;
  reasoning: {
    modes: Array<"default" | "auto" | "enabled" | "off" | "low" | "medium" | "high" | "max">;
    supported: boolean;
  };
  sampling: {
    disabled_reason_when_reasoning?: string | null;
    disabled_when_reasoning: boolean;
    parameters: string[];
    supported: boolean;
  };
  tool_calling: {
    supported: boolean;
  };
};

export function getRuntimeCapabilities(providerId: string, modelId?: string | null) {
  const params = new URLSearchParams({ provider_id: providerId });
  if (modelId) {
    params.set("model_id", modelId);
  }

  return fetchJson<RuntimeCapabilitiesResponse>(`/api/llm/runtime/capabilities?${params.toString()}`)
    .then(toRuntimeCapabilities);
}

function toRuntimeCapabilities(response: RuntimeCapabilitiesResponse): DsLlmRuntimeCapabilities {
  return {
    inputModalities: response.input_modalities
      .map(toInputModality)
      .filter(isInputModality),
    maxOutputTokens: {
      max: response.max_output_tokens.max,
      min: response.max_output_tokens.min ?? 1,
      supported: response.max_output_tokens.supported,
    },
    outputFormats: response.output_formats,
    providerProfileId: response.provider_profile_id,
    reasoning: {
      modes: response.reasoning.modes,
      supported: response.reasoning.supported,
    },
    sampling: {
      disabledReasonWhenReasoning: response.sampling.disabled_reason_when_reasoning ?? undefined,
      disabledWhenReasoning: response.sampling.disabled_when_reasoning,
      parameters: response.sampling.parameters.map(toSamplingParameter).filter(isSamplingParameter),
      supported: response.sampling.supported,
    },
    toolCalling: {
      supported: response.tool_calling.supported,
    },
  };
}

function toInputModality(modality: string): DsLlmInputModality | null {
  switch (modality) {
    case "text":
      return "text";
    case "image":
      return "image";
    default:
      return null;
  }
}

function toSamplingParameter(parameter: string): DsLlmSamplingParameter | null {
  switch (parameter) {
    case "temperature":
      return "temperature";
    case "top_p":
      return "topP";
    case "presence_penalty":
      return "presencePenalty";
    case "frequency_penalty":
      return "frequencyPenalty";
    default:
      return null;
  }
}

function isInputModality(modality: DsLlmInputModality | null): modality is DsLlmInputModality {
  return modality !== null;
}

function isSamplingParameter(parameter: DsLlmSamplingParameter | null): parameter is DsLlmSamplingParameter {
  return parameter !== null;
}
