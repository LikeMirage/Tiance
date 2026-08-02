export type LlmModelPickerOption = {
  annotation?: {
    notes?: readonly string[];
    summary: string;
  };
  capabilityTags?: readonly string[];
  familyGroup?: string;
  isUnavailable?: boolean;
  modelId: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
  source?: string;
};

export type LlmModelPickerModelLike = {
  annotation?: {
    notes?: readonly string[];
    summary: string;
  };
  capabilityTags?: readonly string[];
  familyGroup?: string;
  modelId: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
  source?: string;
};

export function getLlmModelPickerOptionKey(option: LlmModelPickerOption) {
  return buildLlmModelPickerKey(option.providerId, option.modelId);
}

export function buildLlmModelPickerKey(providerId: string, modelId: string) {
  return `${providerId}:${modelId}`;
}

export function toLlmModelPickerOption(
  model: LlmModelPickerModelLike,
): LlmModelPickerOption {
  return {
    annotation: model.annotation,
    capabilityTags: model.capabilityTags,
    familyGroup: model.familyGroup,
    modelId: model.modelId,
    modelLabel: model.modelLabel,
    providerId: model.providerId,
    providerLabel: model.providerLabel,
    source: model.source,
  };
}

export function toUnavailableLlmModelPickerOption(
  modelKey: string,
): LlmModelPickerOption | null {
  const parsed = parseLlmModelPickerKey(modelKey);
  if (!parsed) {
    return null;
  }

  return {
    isUnavailable: true,
    modelId: parsed.modelId,
    modelLabel: parsed.modelId,
    providerId: parsed.providerId,
    providerLabel: parsed.providerId,
  };
}

function parseLlmModelPickerKey(modelKey: string) {
  const separatorIndex = modelKey.indexOf(":");
  if (separatorIndex <= 0 || separatorIndex === modelKey.length - 1) {
    return null;
  }

  return {
    modelId: modelKey.slice(separatorIndex + 1),
    providerId: modelKey.slice(0, separatorIndex),
  };
}
