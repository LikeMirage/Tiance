import type { UseProviderModelDiscoveryResult } from "../../../features/provider-model-discovery/model/useProviderModelDiscovery";
import type { UseModelManagementPanelResult } from "../model/useProviderModelManagement";
import { DiscoveredModelCatalog } from "./DiscoveredModelCatalog";
import { ModelManagementError } from "./ModelManagementError";
import type { ModelCheckState } from "./providerModelManagementUiTypes";

type CloudModelsViewProps = {
  hasAnyProviderApiKey: boolean;
  modelCheckStates: Record<string, ModelCheckState>;
  modelManagementPanel: UseModelManagementPanelResult;
  onTestModel: (modelId: string, label: string) => Promise<void>;
  providerModelDiscovery: UseProviderModelDiscoveryResult;
  testingModelIds: string[];
};

export function CloudModelsView({
  hasAnyProviderApiKey,
  modelCheckStates,
  modelManagementPanel,
  onTestModel,
  providerModelDiscovery,
  testingModelIds,
}: CloudModelsViewProps) {
  return (
    <div className="provider-canvas__added-model-stack">
      <ModelManagementError message={modelManagementPanel.customModelError} />
      <DiscoveredModelCatalog
        addedModelIds={modelManagementPanel.addedCustomModels.map((model) => model.modelId)}
        addingModelIds={modelManagementPanel.addingDiscoveredModelIds}
        deletingModelIds={modelManagementPanel.deletingCustomModelIds}
        isTestingDisabled={!hasAnyProviderApiKey}
        modelCheckStates={modelCheckStates}
        onTestModel={onTestModel}
        providerModelDiscovery={providerModelDiscovery}
        onAddModel={(model) => modelManagementPanel.addDiscoveredModel(model)}
        onRemoveModel={(modelId) => modelManagementPanel.deleteCustomModel(modelId)}
        testingModelIds={testingModelIds}
      />
    </div>
  );
}
