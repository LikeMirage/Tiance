import type { ProviderCustomModelEntry } from "../../../entities/llm-provider/model/providerCustomModel";
import {
  CUSTOM_MODEL_CAPABILITY_OPTIONS,
  deriveCustomModelCapabilities,
  normalizeCustomModelCapabilityTags,
  sortCustomModelCapabilities,
  type CustomModelCapabilityTag,
} from "./customModelCapabilities";
import {
  DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY,
  formatCustomModelPriceInput,
} from "./customModelPricing";
import type {
  AddedCustomModelEntry,
  AddedModelCategoryFilter,
  CustomModelCapabilityOverrides,
  CustomModelDraft,
} from "./modelManagementTypes";

export const EMPTY_CUSTOM_MODEL_DRAFT: CustomModelDraft = {
  capabilityTags: [],
  cacheHitPricePerMillion: "",
  displayName: "",
  familyGroup: "",
  inputPricePerMillion: "",
  manualCapabilityOverrides: {},
  modelId: "",
  note: "",
  outputPricePerMillion: "",
  priceCurrency: DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY,
};

export function isCustomModelDraftEmpty(draft: CustomModelDraft) {
  return (
    isCustomModelDraftContentEmpty(draft) &&
    Object.keys(draft.manualCapabilityOverrides ?? {}).length === 0
  );
}

export function isCustomModelDraftContentEmpty(draft: CustomModelDraft) {
  return (
    draft.capabilityTags.length === 0 &&
    draft.cacheHitPricePerMillion.trim().length === 0 &&
    draft.displayName.trim().length === 0 &&
    draft.familyGroup.trim().length === 0 &&
    draft.inputPricePerMillion.trim().length === 0 &&
    draft.modelId.trim().length === 0 &&
    draft.note.trim().length === 0 &&
    draft.outputPricePerMillion.trim().length === 0 &&
    draft.priceCurrency === DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY
  );
}

export function toggleCustomModelCapabilityInDraft(
  draft: CustomModelDraft,
  tag: CustomModelCapabilityTag,
): CustomModelDraft {
  const hasTag = draft.capabilityTags.includes(tag);
  const nextCapabilityTags = hasTag
    ? draft.capabilityTags.filter((currentTag) => currentTag !== tag)
    : sortCustomModelCapabilities([...draft.capabilityTags, tag]);
  const nextManualCapabilityOverrides = {
    ...(draft.manualCapabilityOverrides ?? {}),
    [tag]: !hasTag,
  };

  return {
    ...draft,
    capabilityTags: nextCapabilityTags,
    manualCapabilityOverrides: nextManualCapabilityOverrides,
  };
}

export function inferCustomModelCapabilityTags(draft: CustomModelDraft) {
  const inferredCapabilityTags = deriveCustomModelCapabilities(
    draft.modelId,
    draft.displayName,
  );
  return applyCustomModelCapabilityOverrides(
    inferredCapabilityTags,
    draft.manualCapabilityOverrides ?? {},
  );
}

export function areCapabilityTagsEqual(
  left: CustomModelCapabilityTag[],
  right: CustomModelCapabilityTag[],
) {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((tag, index) => tag === right[index]);
}

export function toAddedCustomModelEntry(
  model: ProviderCustomModelEntry,
): AddedCustomModelEntry {
  return {
    capabilityTags: normalizeCustomModelCapabilityTags(model.capability_tags),
    cacheHitPricePerMillion: model.cache_hit_price_per_million,
    displayName: model.display_name,
    familyGroup: model.family_group,
    inputPricePerMillion: model.input_price_per_million,
    modelId: model.model_id,
    note: model.note,
    outputPricePerMillion: model.output_price_per_million,
    priceCurrency: model.price_currency,
  };
}

export function toCustomModelDraft(model: AddedCustomModelEntry): CustomModelDraft {
  return {
    capabilityTags: model.capabilityTags,
    cacheHitPricePerMillion: formatCustomModelPriceInput(model.cacheHitPricePerMillion),
    displayName: model.displayName,
    familyGroup: model.familyGroup,
    inputPricePerMillion: formatCustomModelPriceInput(model.inputPricePerMillion),
    manualCapabilityOverrides: deriveCapabilityOverridesFromTags(model),
    modelId: model.modelId,
    note: model.note,
    outputPricePerMillion: formatCustomModelPriceInput(model.outputPricePerMillion),
    priceCurrency: model.priceCurrency,
  };
}

export function upsertAddedCustomModel(
  models: AddedCustomModelEntry[],
  nextModel: AddedCustomModelEntry,
) {
  const existingIndex = models.findIndex(
    (model) => model.modelId === nextModel.modelId,
  );
  if (existingIndex === -1) {
    return [...models, nextModel];
  }

  return models.map((model, index) =>
    index === existingIndex ? nextModel : model,
  );
}

export function matchesAddedModelFilters(
  model: AddedCustomModelEntry,
  filters: {
    categoryFilter: AddedModelCategoryFilter;
    searchQuery: string;
  },
) {
  if (
    filters.categoryFilter !== "all" &&
    !model.capabilityTags.includes(filters.categoryFilter)
  ) {
    return false;
  }

  const normalizedSearchQuery = filters.searchQuery.trim().toLowerCase();
  if (!normalizedSearchQuery) {
    return true;
  }

  return [
    model.displayName,
    model.modelId,
    model.familyGroup,
    model.note,
  ].some((segment) => segment.trim().toLowerCase().includes(normalizedSearchQuery));
}

function applyCustomModelCapabilityOverrides(
  inferredTags: CustomModelCapabilityTag[],
  overrides: CustomModelCapabilityOverrides,
) {
  const nextTags = new Set(inferredTags);
  const overrideEntries = Object.entries(overrides) as Array<
    [CustomModelCapabilityTag, boolean | undefined]
  >;

  overrideEntries.forEach(([tag, enabled]) => {
    if (enabled === true) {
      nextTags.add(tag);
      return;
    }

    if (enabled === false) {
      nextTags.delete(tag);
    }
  });

  return sortCustomModelCapabilities(Array.from(nextTags));
}

function deriveCapabilityOverridesFromTags(
  model: AddedCustomModelEntry,
): CustomModelCapabilityOverrides {
  const inferredTags = new Set(
    deriveCustomModelCapabilities(model.modelId, model.displayName),
  );

  return CUSTOM_MODEL_CAPABILITY_OPTIONS.reduce<CustomModelCapabilityOverrides>(
    (overrides, option) => {
      const isSelected = model.capabilityTags.includes(option.value);
      const isInferred = inferredTags.has(option.value);
      if (isSelected === isInferred) {
        return overrides;
      }

      return {
        ...overrides,
        [option.value]: isSelected,
      };
    },
    {},
  );
}
