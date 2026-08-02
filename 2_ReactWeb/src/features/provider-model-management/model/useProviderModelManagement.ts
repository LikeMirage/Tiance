import { useEffect, useMemo, useRef, useState } from "react";

import type { DiscoveredModelEntry } from "../../../entities/llm-provider/model/discoveredModel";
import type {
  ProviderModelUsageSummary,
  ProviderUsageSummary,
} from "../../../entities/llm-usage/model/providerModelUsage";
import type {
  AddedCustomModelEntry,
  AddedModelCategoryFilter,
  CustomModelDraft,
  CustomModelDraftField,
  ModelManagementMode,
  ModelManagementTransitionDirection,
  CustomModelCapabilityTag,
} from "./modelManagementTypes";
import { useAddedCustomModelFilters } from "./useAddedCustomModelFilters";
import { useAddedCustomModels } from "./useAddedCustomModels";
import { useCustomModelDeletion } from "./useCustomModelDeletion";
import { useCustomModelDraft } from "./useCustomModelDraft";
import { useDiscoveredModelImport } from "./useDiscoveredModelImport";
import { useModelManagementMode } from "./useModelManagementMode";
import { useProviderUsageSummary } from "./useProviderUsageSummary";

export type {
  AddedCustomModelEntry,
  AddedModelCategoryFilter,
  CustomModelCapabilityTag,
  CustomModelDraft,
  CustomModelDraftField,
  ModelManagementMode,
  ModelManagementTransitionDirection,
} from "./modelManagementTypes";

export interface UseProviderModelManagementResult {
  activeMode: ModelManagementMode;
  addDiscoveredModel: (model: DiscoveredModelEntry) => Promise<void>;
  addedModelCategoryFilter: AddedModelCategoryFilter;
  addedModelSearchQuery: string;
  addedCustomModels: AddedCustomModelEntry[];
  addingDiscoveredModelIds: string[];
  canSaveCustomModelDraft: boolean;
  clearCustomModelDraft: () => void;
  customModelError: string | null;
  customModelDraft: CustomModelDraft;
  deleteCustomModel: (modelId: string) => Promise<void>;
  deletingCustomModelIds: string[];
  editingCustomModelId: string | null;
  filteredAddedCustomModels: AddedCustomModelEntry[];
  modelUsageByModelId: Map<string, ProviderModelUsageSummary>;
  inferCustomModelCapabilities: () => void;
  isLoadingAddedCustomModels: boolean;
  isSavingCustomModel: boolean;
  providerUsageSummary: ProviderUsageSummary | null;
  saveCustomModelDraft: () => Promise<void>;
  selectAddedModelCategoryFilter: (filter: AddedModelCategoryFilter) => void;
  selectAddedMode: () => void;
  selectCloudMode: () => void;
  selectCustomMode: () => void;
  startEditingCustomModel: (modelId: string) => void;
  toggleCustomModelCapability: (tag: CustomModelCapabilityTag) => void;
  transitionDirection: ModelManagementTransitionDirection;
  updateAddedModelSearchQuery: (value: string) => void;
  updateCustomModelDraft: (field: CustomModelDraftField, value: string) => void;
}

export type UseModelManagementPanelResult = UseProviderModelManagementResult;

export function useProviderModelManagement(
  selectedProviderId: string | null,
  {
    isActive = true,
  }: {
    isActive?: boolean;
  } = {},
): UseProviderModelManagementResult {
  const selectedProviderIdRef = useRef(selectedProviderId);
  const [customModelError, setCustomModelError] = useState<string | null>(null);
  const modelManagementMode = useModelManagementMode(selectedProviderId);
  const { providerUsageSummary } = useProviderUsageSummary(selectedProviderId, { isActive });
  const {
    addedCustomModels,
    isLoadingAddedCustomModels,
    setAddedCustomModels,
  } = useAddedCustomModels({ selectedProviderId, setCustomModelError });
  const addedModelFilters = useAddedCustomModelFilters({
    addedCustomModels,
    selectedProviderId,
  });

  useEffect(() => {
    selectedProviderIdRef.current = selectedProviderId;
  }, [selectedProviderId]);

  const modelUsageByModelId = useMemo(() => {
    return new Map(
      (providerUsageSummary?.by_models ?? [])
        .filter((summary) => summary.model_id)
        .map((summary) => [summary.model_id as string, summary]),
    );
  }, [providerUsageSummary]);

  const customModelDraft = useCustomModelDraft({
    addedCustomModels,
    selectAddedMode: modelManagementMode.selectAddedMode,
    selectCustomMode: modelManagementMode.selectCustomMode,
    selectedProviderId,
    selectedProviderIdRef,
    setAddedCustomModels,
    setCustomModelError,
  });
  const discoveredModelImport = useDiscoveredModelImport({
    addedCustomModels,
    selectedProviderId,
    selectedProviderIdRef,
    setAddedCustomModels,
    setCustomModelError,
  });
  const customModelDeletion = useCustomModelDeletion({
    onDeletedEditingModel: customModelDraft.clearDeletedEditingModel,
    selectedProviderId,
    selectedProviderIdRef,
    setAddedCustomModels,
    setCustomModelError,
  });

  return {
    activeMode: modelManagementMode.activeMode,
    addDiscoveredModel: discoveredModelImport.addDiscoveredModel,
    addedModelCategoryFilter: addedModelFilters.addedModelCategoryFilter,
    addedModelSearchQuery: addedModelFilters.addedModelSearchQuery,
    addedCustomModels,
    addingDiscoveredModelIds: discoveredModelImport.addingDiscoveredModelIds,
    canSaveCustomModelDraft: customModelDraft.canSaveCustomModelDraft,
    clearCustomModelDraft: customModelDraft.clearCustomModelDraft,
    customModelError,
    customModelDraft: customModelDraft.customModelDraft,
    deleteCustomModel: customModelDeletion.deleteCustomModel,
    deletingCustomModelIds: customModelDeletion.deletingCustomModelIds,
    editingCustomModelId: customModelDraft.editingCustomModelId,
    filteredAddedCustomModels: addedModelFilters.filteredAddedCustomModels,
    modelUsageByModelId,
    inferCustomModelCapabilities: customModelDraft.inferCustomModelCapabilities,
    isLoadingAddedCustomModels,
    isSavingCustomModel: customModelDraft.isSavingCustomModel,
    providerUsageSummary,
    saveCustomModelDraft: customModelDraft.saveCustomModelDraft,
    selectAddedModelCategoryFilter: addedModelFilters.selectAddedModelCategoryFilter,
    selectAddedMode: modelManagementMode.selectAddedMode,
    selectCloudMode: modelManagementMode.selectCloudMode,
    selectCustomMode: modelManagementMode.selectCustomMode,
    startEditingCustomModel: customModelDraft.startEditingCustomModel,
    toggleCustomModelCapability: customModelDraft.toggleCustomModelCapability,
    transitionDirection: modelManagementMode.transitionDirection,
    updateAddedModelSearchQuery: addedModelFilters.updateAddedModelSearchQuery,
    updateCustomModelDraft: customModelDraft.updateCustomModelDraft,
  };
}
