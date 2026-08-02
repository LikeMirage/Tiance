import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { emitLlmUsageChanged } from "../../../entities/llm-usage/model/usageRefreshEvents";
import { deleteProviderCustomModel } from "../../../services/llm/deleteProviderCustomModel";
import { useI18n } from "../../../shared/i18n";
import type { AddedCustomModelEntry } from "./modelManagementTypes";

type ProviderIdRef = {
  current: string | null;
};

type UseCustomModelDeletionInput = {
  onDeletedEditingModel: (providerId: string, modelId: string) => void;
  selectedProviderId: string | null;
  selectedProviderIdRef: ProviderIdRef;
  setAddedCustomModels: Dispatch<SetStateAction<AddedCustomModelEntry[]>>;
  setCustomModelError: Dispatch<SetStateAction<string | null>>;
};

export function useCustomModelDeletion({
  onDeletedEditingModel,
  selectedProviderId,
  selectedProviderIdRef,
  setAddedCustomModels,
  setCustomModelError,
}: UseCustomModelDeletionInput) {
  const { t } = useI18n();
  const [deletingCustomModelIds, setDeletingCustomModelIds] = useState<string[]>([]);

  useEffect(() => {
    setDeletingCustomModelIds([]);
  }, [selectedProviderId]);

  const deleteCustomModel = async (modelId: string) => {
    if (!selectedProviderId) {
      return;
    }

    const providerId = selectedProviderId;
    const normalizedModelId = modelId.trim();
    if (!normalizedModelId) {
      return;
    }

    setCustomModelError(null);
    setDeletingCustomModelIds((current) =>
      current.includes(normalizedModelId)
        ? current
        : [...current, normalizedModelId],
    );

    try {
      await deleteProviderCustomModel(providerId, normalizedModelId);
      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      setAddedCustomModels((current) =>
        current.filter((model) => model.modelId !== normalizedModelId),
      );
      emitLlmModelCatalogChanged({ providerId, modelId: normalizedModelId });
      emitLlmUsageChanged({ providerId, modelId: normalizedModelId });
      onDeletedEditingModel(providerId, normalizedModelId);
    } catch (error) {
      if (selectedProviderIdRef.current !== providerId) {
        return;
      }

      setCustomModelError(
        error instanceof Error
          ? error.message
          : t("providerCanvas.modelManagement.custom.deleteFailed"),
      );
    } finally {
      if (selectedProviderIdRef.current === providerId) {
        setDeletingCustomModelIds((current) =>
          current.filter((currentModelId) => currentModelId !== normalizedModelId),
        );
      }
    }
  };

  return {
    deleteCustomModel,
    deletingCustomModelIds,
  };
}
