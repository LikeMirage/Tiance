import { useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { saveProviderCustomModel } from "../../../services/llm/saveProviderCustomModel";
import { useI18n } from "../../../shared/i18n";
import {
  DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY,
  parseCustomModelPriceInput,
} from "./customModelPricing";
import {
  EMPTY_CUSTOM_MODEL_DRAFT,
  areCapabilityTagsEqual,
  inferCustomModelCapabilityTags,
  isCustomModelDraftContentEmpty,
  isCustomModelDraftEmpty,
  toAddedCustomModelEntry,
  toCustomModelDraft,
  toggleCustomModelCapabilityInDraft,
  upsertAddedCustomModel,
} from "./modelManagementRules";
import type {
  AddedCustomModelEntry,
  CustomModelCapabilityTag,
  CustomModelDraft,
  CustomModelDraftField,
} from "./modelManagementTypes";

type ProviderIdRef = {
  current: string | null;
};

type UseCustomModelDraftInput = {
  addedCustomModels: AddedCustomModelEntry[];
  selectAddedMode: () => void;
  selectCustomMode: () => void;
  selectedProviderId: string | null;
  selectedProviderIdRef: ProviderIdRef;
  setAddedCustomModels: Dispatch<SetStateAction<AddedCustomModelEntry[]>>;
  setCustomModelError: Dispatch<SetStateAction<string | null>>;
};

export function useCustomModelDraft({
  addedCustomModels,
  selectAddedMode,
  selectCustomMode,
  selectedProviderId,
  selectedProviderIdRef,
  setAddedCustomModels,
  setCustomModelError,
}: UseCustomModelDraftInput) {
  const { t } = useI18n();
  const [customModelDrafts, setCustomModelDrafts] = useState<
    Record<string, CustomModelDraft>
  >({});
  const [editingCustomModelIds, setEditingCustomModelIds] = useState<
    Record<string, string | null>
  >({});
  const [isSavingCustomModel, setIsSavingCustomModel] = useState(false);

  const customModelDraft = useMemo(() => {
    if (!selectedProviderId) {
      return EMPTY_CUSTOM_MODEL_DRAFT;
    }

    return customModelDrafts[selectedProviderId] ?? EMPTY_CUSTOM_MODEL_DRAFT;
  }, [customModelDrafts, selectedProviderId]);

  const editingCustomModelId = selectedProviderId
    ? (editingCustomModelIds[selectedProviderId] ?? null)
    : null;
  const canSaveCustomModelDraft =
    customModelDraft.modelId.trim().length > 0 && !isSavingCustomModel;

  const updateCustomModelDraft = (
    field: CustomModelDraftField,
    value: string,
  ) => {
    if (!selectedProviderId) {
      return;
    }

    setCustomModelDrafts((current) => {
      const currentDraft = current[selectedProviderId] ?? EMPTY_CUSTOM_MODEL_DRAFT;

      if (currentDraft[field] === value) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: {
          ...currentDraft,
          [field]: value,
        },
      };
    });
  };

  const toggleCustomModelCapability = (tag: CustomModelCapabilityTag) => {
    if (!selectedProviderId) {
      return;
    }

    setCustomModelDrafts((current) => {
      const currentDraft = current[selectedProviderId] ?? EMPTY_CUSTOM_MODEL_DRAFT;

      return {
        ...current,
        [selectedProviderId]: toggleCustomModelCapabilityInDraft(currentDraft, tag),
      };
    });
  };

  const inferCustomModelCapabilities = () => {
    if (!selectedProviderId) {
      return;
    }

    setCustomModelDrafts((current) => {
      const currentDraft = current[selectedProviderId] ?? EMPTY_CUSTOM_MODEL_DRAFT;
      const nextCapabilityTags = inferCustomModelCapabilityTags(currentDraft);

      if (areCapabilityTagsEqual(currentDraft.capabilityTags, nextCapabilityTags)) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: {
          ...currentDraft,
          capabilityTags: nextCapabilityTags,
        },
      };
    });
  };

  const clearCustomModelDraft = () => {
    if (!selectedProviderId) {
      return;
    }

    const wasEditing = Boolean(editingCustomModelIds[selectedProviderId]);

    setCustomModelError(null);
    setCustomModelDrafts((current) => {
      const currentDraft = current[selectedProviderId];
      if (!currentDraft) {
        return current;
      }

      if (isCustomModelDraftEmpty(currentDraft)) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: EMPTY_CUSTOM_MODEL_DRAFT,
      };
    });
    setEditingCustomModelIds((current) => {
      if (!(selectedProviderId in current)) {
        return current;
      }

      return {
        ...current,
        [selectedProviderId]: null,
      };
    });

    if (wasEditing) {
      selectAddedMode();
    }
  };

  const startEditingCustomModel = (modelId: string) => {
    if (!selectedProviderId) {
      return;
    }

    const normalizedModelId = modelId.trim();
    if (!normalizedModelId) {
      return;
    }

    const existingModel = addedCustomModels.find(
      (item) => item.modelId === normalizedModelId,
    );
    if (!existingModel) {
      return;
    }

    setCustomModelError(null);
    setCustomModelDrafts((current) => ({
      ...current,
      [selectedProviderId]: toCustomModelDraft(existingModel),
    }));
    setEditingCustomModelIds((current) => ({
      ...current,
      [selectedProviderId]: normalizedModelId,
    }));
    selectCustomMode();
  };

  const clearDeletedEditingModel = (providerId: string, modelId: string) => {
    if (editingCustomModelIds[providerId] !== modelId) {
      return;
    }

    setCustomModelDrafts((current) => ({
      ...current,
      [providerId]: EMPTY_CUSTOM_MODEL_DRAFT,
    }));
    setEditingCustomModelIds((current) => ({
      ...current,
      [providerId]: null,
    }));
  };

  const saveCustomModelDraft = async () => {
    if (!selectedProviderId) {
      return;
    }

    const providerId = selectedProviderId;
    const draft = customModelDrafts[providerId] ?? EMPTY_CUSTOM_MODEL_DRAFT;
    const editingModelId = (editingCustomModelIds[providerId] ?? "").trim();
    const modelId = editingModelId || draft.modelId.trim();
    if (isCustomModelDraftContentEmpty(draft)) {
      return;
    }

    if (!modelId) {
      setCustomModelError(t("providerCanvas.modelManagement.custom.modelIdRequired"));
      return;
    }

    let inputPricePerMillion: number | null;
    let cacheHitPricePerMillion: number | null;
    let outputPricePerMillion: number | null;
    try {
      inputPricePerMillion = parseCustomModelPriceInput(
        draft.inputPricePerMillion,
        t("providerCanvas.modelManagement.custom.priceMustBeNonNegative", {
          field: t("providerCanvas.modelManagement.custom.inputPrice"),
        }),
      );
      cacheHitPricePerMillion = parseCustomModelPriceInput(
        draft.cacheHitPricePerMillion,
        t("providerCanvas.modelManagement.custom.priceMustBeNonNegative", {
          field: t("providerCanvas.modelManagement.custom.cacheHitPrice"),
        }),
      );
      outputPricePerMillion = parseCustomModelPriceInput(
        draft.outputPricePerMillion,
        t("providerCanvas.modelManagement.custom.priceMustBeNonNegative", {
          field: t("providerCanvas.modelManagement.custom.outputPrice"),
        }),
      );
    } catch (error) {
      setCustomModelError(
        error instanceof Error
          ? error.message
          : t("providerCanvas.modelManagement.custom.invalidPriceFormat"),
      );
      return;
    }

    setCustomModelError(null);
    setIsSavingCustomModel(true);
    try {
      const savedModel = await saveProviderCustomModel(providerId, {
        capability_tags: draft.capabilityTags,
        cache_hit_price_per_million: cacheHitPricePerMillion,
        display_name: draft.displayName.trim(),
        family_group: draft.familyGroup.trim(),
        input_price_per_million: inputPricePerMillion,
        model_id: modelId,
        note: draft.note.trim(),
        output_price_per_million: outputPricePerMillion,
        price_currency: draft.priceCurrency.trim() || DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY,
      });

      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      const nextModel = toAddedCustomModelEntry(savedModel);
      setAddedCustomModels((current) =>
        upsertAddedCustomModel(current, nextModel),
      );

      setCustomModelDrafts((current) => ({
        ...current,
        [providerId]: EMPTY_CUSTOM_MODEL_DRAFT,
      }));
      setEditingCustomModelIds((current) => ({
        ...current,
        [providerId]: null,
      }));
      emitLlmModelCatalogChanged({ providerId, modelId });
      emitLlmUsageChanged({ providerId, modelId });
      selectAddedMode();
    } catch (error) {
      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      setCustomModelError(
        error instanceof Error
          ? error.message
          : t("providerCanvas.modelManagement.custom.saveFailed"),
      );
    } finally {
      if (selectedProviderIdRef.current === providerId) {
        setIsSavingCustomModel(false);
      }
    }
  };

  return {
    canSaveCustomModelDraft,
    clearCustomModelDraft,
    clearDeletedEditingModel,
    customModelDraft,
    editingCustomModelId,
    inferCustomModelCapabilities,
    isSavingCustomModel,
    saveCustomModelDraft,
    startEditingCustomModel,
    toggleCustomModelCapability,
    updateCustomModelDraft,
  };
}
