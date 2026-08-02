export type DsLlmReasoningMode =
  | "default"
  | "auto"
  | "enabled"
  | "off"
  | "low"
  | "medium"
  | "high"
  | "max";

export type DsLlmOutputFormat = "text" | "json_object";

export type DsLlmReasoningOptions = {
  budgetTokens?: number;
  mode: DsLlmReasoningMode;
};

export type DsLlmGenerationParams = {
  frequencyPenalty?: number;
  maxOutputTokens?: number;
  presencePenalty?: number;
  reasoning?: DsLlmReasoningOptions;
  temperature?: number;
  topP?: number;
};

export type DsLlmOutputOptions = {
  format: DsLlmOutputFormat;
};
