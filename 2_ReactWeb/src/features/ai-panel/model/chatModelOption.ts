import type { LlmModelCatalogEntry } from "../../../entities/llm-provider/model/modelCatalog";

export type ChatModelOption = {
  capabilityTags: readonly string[];
  familyGroup: string;
  providerId: string;
  providerLabel: string;
  modelId: string;
  modelLabel: string;
  source: string;
};

export function toChatModelOption(model: LlmModelCatalogEntry): ChatModelOption {
  return {
    capabilityTags: model.capability_tags,
    familyGroup: model.family_group,
    modelId: model.model_id,
    modelLabel: model.model_label || model.model_id,
    providerId: model.provider_id,
    providerLabel: model.provider_label || model.provider_id,
    source: model.source,
  };
}
