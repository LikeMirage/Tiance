import type {
  DsLlmOutputFormat,
  DsLlmReasoningMode,
} from "./generationParams";

export type DsLlmSamplingParameter =
  | "temperature"
  | "topP"
  | "presencePenalty"
  | "frequencyPenalty";

export type DsLlmInputModality = "text" | "image";

export type DsLlmRuntimeCapabilities = {
  inputModalities: DsLlmInputModality[];
  maxOutputTokens: {
    max: number | null;
    min: number;
    supported: boolean;
  };
  outputFormats: DsLlmOutputFormat[];
  providerProfileId: string;
  reasoning: {
    modes: DsLlmReasoningMode[];
    supported: boolean;
  };
  sampling: {
    disabledReasonWhenReasoning?: string;
    disabledWhenReasoning: boolean;
    parameters: DsLlmSamplingParameter[];
    supported: boolean;
  };
  toolCalling: {
    supported: boolean;
  };
};
