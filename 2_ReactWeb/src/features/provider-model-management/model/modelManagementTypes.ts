import type { CustomModelCapabilityTag } from "./customModelCapabilities";

export type ModelManagementMode = "added" | "cloud" | "custom";
export type { CustomModelCapabilityTag } from "./customModelCapabilities";
export type AddedModelCategoryFilter = "all" | CustomModelCapabilityTag;

export type CustomModelCapabilityOverrides = Partial<
  Record<CustomModelCapabilityTag, boolean>
>;

export type CustomModelDraft = {
  capabilityTags: CustomModelCapabilityTag[];
  cacheHitPricePerMillion: string;
  displayName: string;
  familyGroup: string;
  inputPricePerMillion: string;
  manualCapabilityOverrides: CustomModelCapabilityOverrides;
  modelId: string;
  note: string;
  outputPricePerMillion: string;
  priceCurrency: string;
};

export type CustomModelDraftField = Exclude<
  keyof CustomModelDraft,
  "capabilityTags" | "manualCapabilityOverrides"
>;

export type AddedCustomModelEntry = {
  capabilityTags: CustomModelCapabilityTag[];
  cacheHitPricePerMillion: number | null;
  displayName: string;
  familyGroup: string;
  inputPricePerMillion: number | null;
  modelId: string;
  note: string;
  outputPricePerMillion: number | null;
  priceCurrency: string;
};
