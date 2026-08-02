import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { DiscoveredModelEntry } from "../../../entities/llm-provider/model/discoveredModel";
import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { saveProviderCustomModel } from "../../../services/llm/saveProviderCustomModel";
import { normalizeCustomModelCapabilityTags } from "./customModelCapabilities";
import { DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY } from "./customModelPricing";
import {
  toAddedCustomModelEntry,
  upsertAddedCustomModel,
} from "./modelManagementRules";
import type { AddedCustomModelEntry } from "./modelManagementTypes";

type ProviderIdRef = {
  current: string | null;
};

type UseDiscoveredModelImportInput = {
  addedCustomModels: AddedCustomModelEntry[];
  selectedProviderId: string | null;
  selectedProviderIdRef: ProviderIdRef;
  setAddedCustomModels: Dispatch<SetStateAction<AddedCustomModelEntry[]>>;
  setCustomModelError: Dispatch<SetStateAction<string | null>>;
};

export function useDiscoveredModelImport({
  addedCustomModels,
  selectedProviderId,
  selectedProviderIdRef,
  setAddedCustomModels,
  setCustomModelError,
}: UseDiscoveredModelImportInput) {
  const [addingDiscoveredModelIds, setAddingDiscoveredModelIds] = useState<string[]>([]);

  useEffect(() => {
    setAddingDiscoveredModelIds([]);
  }, [selectedProviderId]);

  const addDiscoveredModel = async (model: DiscoveredModelEntry) => {
    if (!selectedProviderId) {
      return;
    }

    const providerId = selectedProviderId;
    const modelId = model.model_id.trim();
    if (!modelId) {
      setCustomModelError("云模型缺少模型 ID，无法添加。");
      return;
    }

    if (
      addedCustomModels.some((item) => item.modelId === modelId) ||
      addingDiscoveredModelIds.includes(modelId)
    ) {
      return;
    }

    setCustomModelError(null);
    setAddingDiscoveredModelIds((current) => [...current, modelId]);

    try {
      const savedModel = await saveProviderCustomModel(providerId, {
        capability_tags: normalizeCustomModelCapabilityTags(model.capability_tags),
        display_name: model.display_name.trim(),
        family_group: model.family_group.trim() || model.provider_id,
        input_price_per_million: null,
        cache_hit_price_per_million: null,
        model_id: modelId,
        note: "",
        output_price_per_million: null,
        price_currency: DEFAULT_CUSTOM_MODEL_PRICE_CURRENCY,
      });

      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      setAddedCustomModels((current) =>
        upsertAddedCustomModel(current, toAddedCustomModelEntry(savedModel)),
      );
      emitLlmModelCatalogChanged({ providerId, modelId });
      emitLlmUsageChanged({ providerId, modelId });
    } catch (error) {
      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      setCustomModelError(
        error instanceof Error ? error.message : "添加云模型失败。",
      );
    } finally {
      if (selectedProviderIdRef.current === providerId) {
        setAddingDiscoveredModelIds((current) =>
          current.filter((currentModelId) => currentModelId !== modelId),
        );
      }
    }
  };

  return {
    addDiscoveredModel,
    addingDiscoveredModelIds,
  };
}
